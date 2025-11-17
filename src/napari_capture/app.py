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
from .calibration import simple_contrast_stretch, calibrate_with_color_checker, calibrate_with_manual_points

# Essayer d'importer gphoto2
try:
    import gphoto2 as gp

    GPHOTO2_INSTALLED = True
except ImportError:
    GPHOTO2_INSTALLED = False

# --- Constantes ---
LIVE_VIEW_NAME = "Prévisualisation en direct"
DEFAULT_SETTINGS_FILENAME = "camera_settings.json"
CALIBRATION_FILENAME = "last_calibration.json"


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

        # NOUVEAU : Attributs pour mémoriser la dernière calibration
        self.last_calibration_method = None  # Sera 'auto' ou 'manual'
        self.last_calibration_data = None  # Stockera la zone ou les points

        self._setup_widgets()
        self._connect_events()

        # Le chargement initial se fait via l'événement `changed` du widget
        # pour s'assurer qu'il a une valeur de départ.
        self._auto_load_settings(self.capture_w.save_directory.value)

    def _setup_widgets(self):
        self.capture_w = self._create_capture_widget()
        self.settings_w = self._create_settings_widget()
        self.simple_calibration_w = self._create_simple_calibration_widget()
        self.checker_calibration_w = self._create_checker_calibration_widget()
        self.view_mode_w = self._create_view_mode_widget()
        # Widget pour la calibration en série
        self.batch_calibration_w = self._create_batch_calibration_widget()
        # Lie l'instance de la classe (self) au paramètre 'self' de chaque widget
        self.capture_w.self.bind(self)
        self.settings_w.self.bind(self)
        self.simple_calibration_w.self.bind(self)
        self.checker_calibration_w.self.bind(self)
        self.batch_calibration_w.self.bind(self)
        self.view_mode_w.self.bind(self)

        # Ajout des widgets au dock
        self.viewer.window.add_dock_widget(self.capture_w, area="right", name="Contrôle de Capture")
        self.viewer.window.add_dock_widget(self.view_mode_w, area="right", name="Options d'affichage")
        self.viewer.window.add_dock_widget(self.settings_w, area="right", name="Réglages Appareil")
        # On ajoute les deux widgets de calibration
        self.viewer.window.add_dock_widget(self.checker_calibration_w, area="right", name="Calibration par Charte")
        # NOUVEAU
        self.viewer.window.add_dock_widget(self.batch_calibration_w, area="right", name="Calibration en Série")
        self.viewer.window.add_dock_widget(self.simple_calibration_w, area="right", name="Calibration Simple")

    def _connect_events(self):
        self.viewer.layers.events.removed.connect(self._on_layer_removed)
        self.capture_w.save_directory.changed.connect(self._auto_load_settings)
        self.capture_w.file_prefix.changed.connect(
            lambda prefix: self.camera_controller.set_next_capture_count(self.capture_w.save_directory.value, prefix)
        )
        self.view_mode_w.preview_first.changed.connect(self._on_view_mode_change)
        self.checker_calibration_w.step1_button.changed.connect(self._on_checker_step1_click)
        self.checker_calibration_w.step2_button.changed.connect(self._on_checker_step2_click)
        # NOUVEAU : Connexion pour le bouton de calibration en série
        self.batch_calibration_w.apply_to_all_button.changed.connect(self._on_apply_calibration_to_all)

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
    def _create_capture_widget(self, save_directory: Path = Path.home().joinpath("bana_test"),
                               file_prefix: str = "capture"):
        if not save_directory or not save_directory.is_dir():
            show_error("Veuillez définir un dossier de sauvegarde valide.")
            return
        save_directory.mkdir(exist_ok=True)

        try:
            image_data = self.camera_controller.capture_high_res_image()
        except Exception as e:
            show_error(f"Échec de la capture : {e}")
            return

        filename = f"{file_prefix}_{self.camera_controller.capture_count:04d}.tiff"
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

    @magic_factory(call_button="Appliquer Contraste Auto")
    def _create_simple_calibration_widget(self):
        selected_layers = [layer for layer in self.viewer.layers.selection if layer.name != LIVE_VIEW_NAME]
        if not selected_layers:
            show_error("Veuillez sélectionner au moins une image capturée.")
            return

        for layer in selected_layers:
            if isinstance(layer, Image):
                try:
                    # On appelle maintenant la fonction de contraste simple
                    calibrated_data = simple_contrast_stretch(layer.data)
                    self.viewer.add_image(calibrated_data, name=f"{layer.name}_contraste")
                except Exception as e:
                    show_error(f"Erreur de calibration sur '{layer.name}': {e}")

    @magic_factory(
        # On définit les deux boutons qui composent le widget
        step1_button={"widget_type": "PushButton", "text": "Étape 1: Créer la zone de sélection"},
        step2_button={"widget_type": "PushButton", "text": "Étape 2: Calibrer depuis la zone"},
        # On supprime le bouton "Run" qui est inutile ici
        call_button=False
    )
    def _create_checker_calibration_widget(self, step1_button=False, step2_button=False):
        """
        Crée le widget pour la calibration par charte.
        La logique est maintenant déportée dans les gestionnaires d'événements.
        """
        pass

    @magic_factory(
        apply_to_all_button={"widget_type": "PushButton", "text": "Appliquer la calibration mémorisée à tout"},
        call_button=False
    )
    def _create_batch_calibration_widget(self, apply_to_all_button=False):
        pass

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
                    expected_last_name = f"{prefix}_{self.camera_controller.capture_count - 1:04d}.tiff"
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
        pattern = re.compile(rf"{re.escape(prefix)}_(\d{{4}})\.tiff")

        # Trouve et trie les fichiers par leur numéro
        image_files = []
        for f in directory.glob(f"{prefix}_*.tiff"):
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
            last_capture_name = f"{prefix}_{last_capture_num:04d}.tiff"

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

    def _on_checker_step1_click(self):
        """Crée un calque de formes pour que l'utilisateur dessine un rectangle."""
        # On vérifie si un calque de zone existe déjà pour ne pas en créer plusieurs
        if 'Zone de la charte' not in self.viewer.layers:
            shapes_layer = self.viewer.add_shapes(
                name="Zone de la charte",
                shape_type='rectangle',
                edge_color='yellow',
                face_color='transparent'
            )
            shapes_layer.mode = 'add_rectangle'
            show_info("Dessinez un rectangle autour de la charte de couleurs, puis passez à l'étape 2.")
        else:
            show_info("Un calque 'Zone de la charte' existe déjà. Vous pouvez modifier le rectangle existant.")

        # NOUVEAU : La logique de l'étape 2 est maintenant dans sa propre méthode

    def _on_checker_step2_click(self):
        """
        Lance la calibration. Tente l'auto-détection, passe en manuel si échec,
        et mémorise les données de calibration en cas de succès.
        """
        # --- Vérifications initiales ---
        selected_layers = [layer for layer in self.viewer.layers.selection if
                           isinstance(layer, Image) and layer.name != LIVE_VIEW_NAME]
        if not selected_layers:
            show_error("Veuillez sélectionner l'image à calibrer dans la liste des calques.")
            return
        source_image_layer = selected_layers[0]

        # --- CAS 1: L'utilisateur a déjà placé des points manuels ---
        try:
            points_layer = self.viewer.layers['Points de calibration']
            if len(points_layer.data) == 6:
                show_info("6 points détectés, lancement de la calibration manuelle...")
                try:
                    calibrated_data = calibrate_with_manual_points(source_image_layer.data, points_layer.data)
                    self.viewer.add_image(calibrated_data, name=f"{source_image_layer.name}_calibré_manuel")

                    # NOUVEAU : Mémorisation
                    self.last_calibration_method = 'manual'
                    self.last_calibration_data = points_layer.data
                    self._save_calibration_data()  # NOUVEAU: Sauvegarde
                    show_info("Calibration manuelle réussie et sauvegardée !")

                    self.viewer.layers.pop(self.viewer.layers.index('Points de calibration'))
                    show_info("Calibration manuelle terminée !")
                except Exception as e:
                    show_error(f"Échec de la calibration manuelle : {e}")
                return
            else:
                show_error(f"Le calque 'Points de calibration' contient {len(points_layer.data)} points au lieu de 6.")
                return
        except KeyError:
            # Le calque de points n'existe pas, on passe à la détection automatique.
            pass

        # Cas 2: Calibration automatique à partir de la zone
        try:
            shapes_layer = self.viewer.layers['Zone de la charte']
            if not shapes_layer.data:
                show_error("Aucune zone n'a été dessinée. Compléter l'étape 1.")
                return
            bounding_box = shapes_layer.data[-1]
        except KeyError:
            show_error("Le calque 'Zone de la charte' n'existe pas. Lancez l'étape 1.")
            return

        try:
            show_info("Tentative de détection automatique de la charte...")
            # On récupère l'image calibrée ET l'image ROI pour le débogage
            calibrated_data, roi_image_debug = calibrate_with_color_checker(source_image_layer.data, bounding_box)

            # Affichage de l'image ROI pour le débogage
            self.viewer.add_image(roi_image_debug, name="[Debug] Zone analysée", rgb=True)
            self.viewer.add_image(calibrated_data, name=f"{source_image_layer.name}_calibré_auto")

            self.last_calibration_method = 'auto'
            self.last_calibration_data = bounding_box
            self._save_calibration_data()  # NOUVEAU: Sauvegarde
            show_info("Calibration automatique réussie et sauvegardée !")

            self.viewer.layers.pop(self.viewer.layers.index('Zone de la charte'))
            show_info("Calibration automatique terminée avec succès !")

        except ValueError as e:
            # --- CAS 3: La détection automatique a échoué, on passe en mode manuel ---
            show_error(f"Échec de la détection automatique : {e}")
            show_info("Veuillez maintenant sélectionner 6 points manuellement.")

            # On crée un calque de points pour l'utilisateur
            points_layer = self.viewer.add_points(name="Points de calibration", size=20, ndim=2)
            points_layer.mode = 'add'
            # On donne des instructions claires
            show_info(
                "Cliquez dans l'ordre sur le CENTRE des patchs suivants : "
                "1.BLANC, 2.GRIS MOYEN, 3.NOIR, 4.ROUGE, 5.VERT, 6.BLEU. "
                "Puis, cliquez à nouveau sur 'Étape 2: Calibrer'."
            )

    # MODIFIÉ : _auto_load_settings charge maintenant la calibration
    def _auto_load_settings(self, directory: Path):
        show_info(f"Dossier sélectionné : {directory}")
        prefix = self.capture_w.file_prefix.value

        self._load_existing_images(directory, prefix)
        self.camera_controller.set_next_capture_count(directory, prefix)

        settings_file = directory / DEFAULT_SETTINGS_FILENAME
        if settings_file.exists():
            self.camera_controller.load_and_apply_settings(settings_file)
        else:
            show_info(f"Aucun fichier '{DEFAULT_SETTINGS_FILENAME}' trouvé dans le dossier.")

        # NOUVEAU : On charge la calibration sauvegardée pour ce dossier
        self._load_calibration_data(directory)

    # NOUVELLE méthode pour sauvegarder la calibration
    def _save_calibration_data(self):
        """Sauvegarde la dernière calibration réussie dans un fichier JSON."""
        save_dir = self.capture_w.save_directory.value
        if not save_dir or not self.last_calibration_data is not None:
            return

        filepath = save_dir / CALIBRATION_FILENAME

        # On convertit les arrays numpy en listes pour la sauvegarde JSON
        data_to_save = {
            "method": self.last_calibration_method,
            "data": self.last_calibration_data.tolist()
        }

        try:
            with open(filepath, 'w') as f:
                json.dump(data_to_save, f, indent=4)
            show_info(f"Données de calibration sauvegardées dans {filepath.name}")
        except Exception as e:
            show_error(f"Impossible de sauvegarder la calibration : {e}")

    # NOUVELLE méthode pour charger la calibration
    def _load_calibration_data(self, directory: Path):
        """Charge les données de calibration depuis un fichier JSON si il existe."""
        filepath = directory / CALIBRATION_FILENAME
        if filepath.exists():
            try:
                with open(filepath, 'r') as f:
                    calib_data = json.load(f)

                self.last_calibration_method = calib_data["method"]
                # On reconvertit les listes en arrays numpy
                self.last_calibration_data = np.array(calib_data["data"])

                show_info(
                    f"Calibration précédente (méthode: {self.last_calibration_method}) chargée depuis le fichier.")
            except Exception as e:
                show_error(f"Impossible de charger le fichier de calibration : {e}")
                self.last_calibration_data = None
        else:
            # S'il n'y a pas de fichier, on réinitialise la mémoire
            self.last_calibration_data = None

    # NOUVEAU : Logique pour le bouton "Appliquer à tout"
    def _on_apply_calibration_to_all(self):
        """Applique la dernière calibration réussie à toutes les images non calibrées."""
        if self.last_calibration_data is None:
            show_error("Aucune calibration n'est en mémoire. Veuillez d'abord calibrer une image.")
            return

        # On identifie toutes les images qui ont besoin d'être calibrées
        images_to_calibrate = [
            layer for layer in self.viewer.layers
            if isinstance(layer, Image) and
               layer.name != LIVE_VIEW_NAME and
               not layer.name.startswith("[Debug]") and
               not layer.name.endswith(("_calibré_auto", "_calibré_manuel", "_contraste"))
        ]

        if not images_to_calibrate:
            show_info("Toutes les images sont déjà calibrées.")
            return

        show_info(f"Application de la calibration mémorisée à {len(images_to_calibrate)} image(s)...")

        for layer in images_to_calibrate:
            try:
                if self.last_calibration_method == 'auto':
                    calibrated_data, _ = calibrate_with_color_checker(layer.data, self.last_calibration_data)
                    suffix = "_calibré_auto"
                elif self.last_calibration_method == 'manual':
                    calibrated_data = calibrate_with_manual_points(layer.data, self.last_calibration_data)
                    suffix = "_calibré_manuel"

                # On ajoute le nouveau calque calibré
                self.viewer.add_image(calibrated_data, name=f"{layer.name}{suffix}")
            except Exception as e:
                show_error(f"Erreur lors de la calibration de '{layer.name}': {e}")

        show_info("Calibration en série terminée.")

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


def main():
    """Lancement de l'application Napari."""
    viewer = napari.Viewer(title="Interface de Capture Photo")
    app = NapariCaptureApp(viewer)
    app.start()

    # Le `napari.run()` est bloquant. On connecte la fermeture de la fenêtre à notre nettoyage.
    viewer.window.qt_viewer.destroyed.connect(app.close)

    napari.run()

if __name__ == "__main__":
    main()