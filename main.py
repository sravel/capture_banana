# main.py

import napari
from napari.utils.notifications import show_info, show_error
from napari.qt import thread_worker
from napari.layers import Image, Layer
from qtpy.QtCore import QTimer

from magicgui import magic_factory
from pathlib import Path
import numpy as np
import imageio.v2 as imageio
import json
import traceback
import time
import os
import re

# Import pour la webcam
import cv2

# On importe notre fonction de calibration
from calibration import apply_color_calibration

# Essayer d'importer gphoto2
try:
    import gphoto2 as gp

    GPHOTO2_INSTALLED = True
except ImportError:
    GPHOTO2_INSTALLED = False

# --- Constantes ---
LIVE_VIEW_NAME = "Prévisualisation en direct"
DEFAULT_SETTINGS_FILENAME = "camera_settings.json"


class CameraController:
    # --- Cette classe est inchangée ---
    def __init__(self, viewer: napari.Viewer):
        self.viewer = viewer
        self.camera_type = 'mock'
        self.camera = None
        self.webcam = None
        self.live_view_worker = None
        self.live_layer = None
        self.capture_count = 1
        self.preview_on_top = True

        if GPHOTO2_INSTALLED:
            try:
                self.camera = gp.Camera()
                self.camera.init()
                self.camera_type = 'gphoto2'
                show_info("Appareil photo DSLR détecté.")
                return
            except gp.GPhoto2Error:
                self.camera = None
        try:
            self.webcam = cv2.VideoCapture(0)
            if self.webcam.isOpened():
                self.camera_type = 'opencv'
                show_info("DSLR non trouvé. Utilisation de la webcam.")
            else:
                self.webcam.release()
                self.webcam = None
                raise IOError("Webcam non accessible")
        except Exception:
            self.camera_type = 'mock'
            show_info("Aucune caméra détectée. Passage en mode factice.")

    def _get_live_frame(self) -> np.ndarray:
        if self.camera_type == 'gphoto2':
            capture = self.camera.capture_preview()
            img_bytes = np.frombuffer(capture.get_data_and_size(), dtype=np.uint8)
            return imageio.imread(img_bytes)
        elif self.camera_type == 'opencv':
            ret, frame = self.webcam.read()
            if ret:
                return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return np.zeros((480, 640, 3), dtype=np.uint8)
        else:  # 'mock'
            img = np.random.randint(0, 50, size=(512, 512, 3), dtype=np.uint8)
            x, y = int(time.time() * 50) % 512, int(time.time() * 25) % 512
            img[y:y + 50, x:x + 50, :] = [255, 0, 255]
            return img

    @thread_worker
    def _live_view_updater(self):
        while True:
            frame = self._get_live_frame()
            yield frame
            time.sleep(1 / 30)

    def start_live_view(self):
        # if self.live_view_worker is not None:
        #     self.stop_live_view()
        initial_frame = self._get_live_frame()
        self.live_layer = self.viewer.add_image(initial_frame, name=LIVE_VIEW_NAME, rgb=True)
        self.live_view_worker = self._live_view_updater()
        self.live_view_worker.yielded.connect(self._update_layer_data)
        self.live_view_worker.start()

    def _update_layer_data(self, frame: np.ndarray):
        if self.live_layer:
            self.live_layer.data = frame

    def stop_live_view(self):
        if self.live_view_worker:
            self.live_view_worker.quit()
            self.live_view_worker = None

    def release_hardware(self):
        """Libère les ressources matérielles (webcam, DSLR)."""
        if self.webcam:
            self.webcam.release()
            print("Webcam libérée.")
        if self.camera:
            # Pour gphoto2, .exit() est la bonne pratique
            self.camera.exit()
            print("Appareil DSLR libéré.")

    def capture_high_res_image(self) -> np.ndarray:
        show_info("Capture haute résolution en cours...")
        is_running = self.live_view_worker is not None
        if is_running:
            self.live_view_worker.pause()
            time.sleep(0.5)
        if self.camera_type == 'gphoto2':
            file_path = self.camera.capture(gp.GP_CAPTURE_IMAGE)
            camera_file = self.camera.file_get(file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL)
            file_data = np.frombuffer(camera_file.get_data_and_size(), dtype=np.uint8)
            image = imageio.imread(file_data)
        elif self.camera_type == 'opencv':
            image = self._get_live_frame()
        else:  # mock
            image = (np.random.rand(1024, 1024, 3) * 255).astype(np.uint8)
        if is_running:
            self.live_view_worker.resume()
        show_info("Capture terminée.")
        return image

    def load_and_apply_settings(self, settings_path: Path):
        if self.camera_type != 'gphoto2':
            show_error("Les réglages ne peuvent être appliqués qu'à un appareil DSLR (gphoto2).")
            return
        try:
            with open(settings_path, 'r') as f:
                settings = json.load(f)
            config = self.camera.get_config()
            for key, value in settings.items():
                try:
                    widget = config.get_child_by_name(key)
                    widget.set_value(str(value))
                    print(f"Réglage appliqué : {key} = {value}")
                except gp.GPhoto2Error as ex:
                    print(f"AVERTISSEMENT: Impossible de régler '{key}'. Erreur: {ex}")
            self.camera.set_config(config)
            show_info(f"Paramètres chargés depuis {settings_path.name} et appliqués.")
        except Exception as e:
            show_error(f"Erreur lors du chargement des paramètres : {e}")
            traceback.print_exc()

    def set_next_capture_count(self, directory: Path, prefix: str):
        max_num = 0
        pattern = re.compile(rf"{re.escape(prefix)}_(\d{{4}})\.png")
        for f in directory.glob(f"{prefix}_*.png"):
            match = pattern.match(f.name)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num
        self.capture_count = max_num + 1
        show_info(f"Prochaine capture sera numérotée : {self.capture_count:04d}")


class NapariCaptureApp:
    def __init__(self, viewer: napari.Viewer):
        self.viewer = viewer
        self.camera_controller = CameraController(viewer)

        self._setup_widgets()
        self._connect_events()

        # Le chargement initial se fait via l'événement `changed` du widget
        # pour s'assurer qu'il a une valeur de départ.
        self._auto_load_settings(self.capture_w.save_directory.value)

    def _setup_widgets(self):
        self.capture_w = self._create_capture_widget()
        self.settings_w = self._create_settings_widget()
        self.calibration_w = self._create_calibration_widget()
        self.view_mode_w = self._create_view_mode_widget()

        # Lie l'instance de la classe (self) au paramètre 'self' de chaque widget
        self.capture_w.self.bind(self)
        self.settings_w.self.bind(self)
        self.calibration_w.self.bind(self)
        self.view_mode_w.self.bind(self)

        self.viewer.window.add_dock_widget(self.capture_w, area="right", name="Contrôle de Capture")
        self.viewer.window.add_dock_widget(self.view_mode_w, area="right", name="Options d'affichage")
        self.viewer.window.add_dock_widget(self.settings_w, area="right", name="Réglages Appareil")
        self.viewer.window.add_dock_widget(self.calibration_w, area="right", name="Calibration")

    def _connect_events(self):
        self.viewer.layers.events.removed.connect(self._on_layer_removed)
        self.capture_w.save_directory.changed.connect(self._auto_load_settings)
        self.capture_w.file_prefix.changed.connect(
            lambda prefix: self.camera_controller.set_next_capture_count(self.capture_w.save_directory.value, prefix)
        )
        self.view_mode_w.preview_first.changed.connect(self._on_view_mode_change)

    # --- Widgets ---

    @magic_factory(
        # On supprime le bouton "Run" inutile en spécifiant call_button=""
        call_button="",
        preview_first={"label": "Prévisualisation en tête de liste", "widget_type": "CheckBox"})
    def _create_view_mode_widget(self, preview_first: bool = True):
        pass

    @magic_factory(
        save_directory={"label": "Dossier de sauvegarde", "mode": "d"},
        file_prefix={"label": "Préfixe du nom de fichier"},
        call_button="Capturer l'image"
    )
    def _create_capture_widget(self, save_directory: Path = Path.home(), file_prefix: str = "capture"):
        if not save_directory or not save_directory.is_dir():
            show_error("Veuillez définir un dossier de sauvegarde valide.")
            return

        try:
            image_data = self.camera_controller.capture_high_res_image()
        except Exception as e:
            show_error(f"Échec de la capture : {e}")
            return

        filename = f"{file_prefix}_{self.camera_controller.capture_count:04d}.png"
        full_path = save_directory / filename

        new_layer = self.viewer.add_image(
            image_data, name=filename, rgb=True, metadata={'filepath': str(full_path)}
        )

        # **CORRECTION LOGIQUE CHECKBOX**
        if self.camera_controller.preview_on_top:
            try:
                self.viewer.layers.move(self.viewer.layers.index(LIVE_VIEW_NAME), -1)
            except ValueError:
                pass
        else:
            self.viewer.layers.move(self.viewer.layers.index(new_layer), -2)

        try:
            imageio.imwrite(full_path, image_data)
            show_info(f"Image sauvegardée : {filename}")
            self.camera_controller.capture_count += 1
        except Exception as e:
            show_error(f"Échec de la sauvegarde de l'image : {e}")

    @magic_factory(
        settings_file={"label": "Charger les réglages", "mode": "r", "filter": "*.json"},
        call_button="Appliquer"
    )
    def _create_settings_widget(self, settings_file: Path):
        if settings_file and settings_file.exists():
            self.camera_controller.load_and_apply_settings(settings_file)
        else:
            show_error("Fichier de réglages non valide.")

    @magic_factory(call_button="Appliquer la calibration")
    def _create_calibration_widget(self):
        selected_layers = [layer for layer in self.viewer.layers.selection if layer.name != LIVE_VIEW_NAME]
        if not selected_layers:
            show_error("Veuillez sélectionner au moins une image capturée.")
            return

        for layer in selected_layers:
            if isinstance(layer, Image):
                try:
                    calibrated_data = apply_color_calibration(layer.data)
                    self.viewer.add_image(calibrated_data, name=f"{layer.name}_calibrated")
                except Exception as e:
                    show_error(f"Erreur de calibration sur '{layer.name}': {e}")

    # --- Gestionnaires d'événements ---

    def _on_layer_removed(self, event):
        """
        Gestionnaire pour la suppression de calques.
        Protège le calque de prévisualisation et supprime les fichiers associés aux captures.
        """
        layer: Layer = event.value

        if layer.name == LIVE_VIEW_NAME:
            show_info("La prévisualisation en direct ne peut pas être supprimée. Relance...")

            # ÉTAPE 1: On arrête l'ancien processus immédiatement.
            self.camera_controller.stop_live_view()

            # ÉTAPE 2: On demande à l'interface de démarrer un nouveau processus dès que possible.
            QTimer.singleShot(1, self.camera_controller.start_live_view)
            return

        if 'filepath' in layer.metadata:
            # ... le reste de la fonction est inchangé
            filepath = Path(layer.metadata['filepath'])
            try:
                if filepath.exists():
                    os.remove(filepath)
                    show_info(f"Fichier supprimé du disque : {filepath.name}")

                    prefix = self.capture_w.file_prefix.value
                    expected_last_name = f"{prefix}_{self.camera_controller.capture_count - 1:04d}.png"
                    if layer.name == expected_last_name and self.camera_controller.capture_count > 1:
                        self.camera_controller.capture_count -= 1
                        show_info(f"Compteur de capture réajusté à {self.camera_controller.capture_count}")

            except Exception as e:
                show_error(f"Impossible de supprimer le fichier {filepath.name}: {e}")

    def _auto_load_settings(self, directory: Path):
        show_info(f"Dossier sélectionné : {directory}")
        prefix = self.capture_w.file_prefix.value

        # **NOUVEAU: Appel au chargement des images existantes**
        self._load_existing_images(directory, prefix)

        self.camera_controller.set_next_capture_count(directory, prefix)

        settings_file = directory / DEFAULT_SETTINGS_FILENAME
        if settings_file.exists():
            self.camera_controller.load_and_apply_settings(settings_file)
        else:
            show_info(f"Aucun fichier '{DEFAULT_SETTINGS_FILENAME}' trouvé dans le dossier.")

    # **NOUVEAU: Méthode pour charger les images du disque**
    def _load_existing_images(self, directory: Path, prefix: str):
        """Scanne un dossier, charge les images correspondantes et les ajoute à Napari."""
        show_info("Recherche d'images existantes...")

        # Regex pour extraire le numéro du fichier
        pattern = re.compile(rf"{re.escape(prefix)}_(\d{{4}})\.png")

        # Trouve et trie les fichiers par leur numéro
        image_files = []
        for f in directory.glob(f"{prefix}_*.png"):
            match = pattern.match(f.name)
            if match:
                num = int(match.group(1))
                image_files.append((num, f))

        image_files.sort()  # Trie par le numéro (le premier élément du tuple)

        if not image_files:
            show_info("Aucune image existante trouvée.")
            return

        for num, path in image_files:
            # Évite de recharger une image déjà présente
            if path.name in self.viewer.layers:
                continue

            try:
                image_data = imageio.imread(path)
                self.viewer.add_image(
                    image_data,
                    name=path.name,
                    rgb=True,
                    metadata={'filepath': str(path)}
                )
            except Exception as e:
                show_error(f"Impossible de charger l'image {path.name}: {e}")

        show_info(f"{len(image_files)} image(s) chargée(s) depuis le disque.")

    def _on_view_mode_change(self, is_preview_first: bool):
        """
        Gestionnaire pour la checkbox, utilisant le nom de la dernière capture pour le basculement.
        """
        self.camera_controller.preview_on_top = is_preview_first
        layers = self.viewer.layers

        if is_preview_first:
            # === CAS 1: La case est COCHÉE ===
            # On veut la prévisualisation en tête de liste (index 0).
            try:
                layers.move(layers.index(LIVE_VIEW_NAME), -1)
                show_info("Affichage : Prévisualisation en tête de liste.")
            except ValueError:
                pass  # Le calque de prévisualisation n'existe pas
        else:
            # === CAS 2: La case est DÉCOCHÉE ===
            # On veut la DERNIÈRE image capturée en tête de liste.

            # Détermine le nom de la dernière image capturée
            last_capture_num = self.camera_controller.capture_count - 1
            if last_capture_num < 1:
                show_info("Aucune capture n'a encore été réalisée.")
                self.view_mode_w.preview_first.value = True  # On recoche la case
                return

            prefix = self.capture_w.file_prefix.value
            last_capture_name = f"{prefix}_{last_capture_num:04d}.png"

            try:
                # On cherche le calque par son nom exact
                last_capture_layer = layers[last_capture_name]
                # On le déplace en tête de liste (index 0)
                layers.move(layers.index(last_capture_layer), -1)
                show_info(f"Affichage : '{last_capture_name}' en tête de liste.")
            except KeyError:
                # Le calque de la dernière capture n'a pas été trouvé (peut-être supprimé)
                show_info(f"La dernière capture ('{last_capture_name}') n'est pas dans la liste.")
                self.view_mode_w.preview_first.value = True  # On recoche la case

    def start(self):
        self.camera_controller.start_live_view()

    def close(self):
        """Nettoie et arrête les processus en cours à la fermeture de l'application."""
        print("Fenêtre Napari fermée, arrêt des processus...")
        # 1. On arrête le thread de lecture
        self.camera_controller.stop_live_view()
        # 2. On libère le matériel
        self.camera_controller.release_hardware()
        print("Nettoyage terminé.")


if __name__ == "__main__":
    viewer = napari.Viewer(title="Interface de Capture Photo")
    app = NapariCaptureApp(viewer)
    app.start()
    napari.run()
    app.close()