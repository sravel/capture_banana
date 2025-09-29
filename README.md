==============
Capture Napari
==============

Une interface Python simple basée sur `Napari <https://napari.org/>`_ pour la capture de photos depuis un appareil photo numérique (DSLR Nikon/Canon) ou une webcam.

.. image:: https://img.shields.io/badge/python-3.8+-blue.svg
   :target: https://www.python.org/downloads/
.. image:: https://img.shields.io/badge/license-MIT-green.svg
   :target: https://opensource.org/licenses/MIT

.. contents:: Table des matières
.. sectnum::

Fonctionnalités
---------------

* **Double source de capture** : Contrôle des appareils photo DSLR via `gphoto2` (Linux/macOS) avec repli automatique sur la webcam (via OpenCV) si aucun DSLR n'est détecté. Un mode "factice" est utilisé si aucune caméra n'est trouvée.
* **Prévisualisation en direct** : Un flux vidéo en temps réel de la caméra est affiché directement dans l'interface.
* **Organisation des fichiers** :
    * Définition d'un dossier de sauvegarde obligatoire.
    * Nommage incrémentiel des fichiers (`prefixe_0001.png`, `prefixe_0002.png`, etc.). Le compteur s'ajuste automatiquement en fonction des fichiers existants.
* **Gestion des calques** :
    * Chaque capture est ajoutée comme un nouveau calque dans Napari.
    * Une checkbox permet de choisir si la prévisualisation ou la dernière capture doit être affichée au premier plan.
    * La suppression d'un calque de capture dans Napari supprime également le fichier correspondant sur le disque.
    * Le calque de prévisualisation est "verrouillé" et ne peut pas être supprimé.
* **Configuration externe** :
    * Chargement automatique d'un fichier de paramètres `camera_settings.json` présent dans le dossier de sauvegarde.
    * Possibilité d'appliquer un script de calibration de couleur personnalisé (`calibration.py`) aux images capturées.
* **Chargement de session** : Les images existantes dans le dossier de sauvegarde sont automatiquement chargées au démarrage de l'application.


Installation
------------

Prérequis
^^^^^^^^^

* Python 3.8 ou supérieur
* Git
* `libgphoto2` installé sur le système (pour Linux/macOS). Sur les systèmes Debian/Ubuntu :
    .. code-block:: bash

        sudo apt-get update && sudo apt-get install libgphoto2-dev

Étapes d'installation
^^^^^^^^^^^^^^^^^^^^^

1.  Clonez ce dépôt :

    .. code-block:: bash

        git clone <URL_DU_DEPOT_GIT>
        cd <NOM_DU_DOSSIER>

2.  Créez et activez un environnement virtuel Python :

    .. code-block:: bash

        python3 -m venv venv
        source venv/bin/activate  # Sur Linux/macOS
        # venv\Scripts\activate    # Sur Windows

3.  Installez les dépendances requises :

    .. code-block:: bash

        pip install -r requirements.txt


Utilisation
-----------

Avant de lancer l'application, vous pouvez configurer deux fichiers.

Configuration (Optionnel)
^^^^^^^^^^^^^^^^^^^^^^^^^

1.  **Réglages de l'appareil (`camera_settings.json`)**

    Créez un fichier `camera_settings.json` à la racine du dossier de sauvegarde que vous utiliserez. Ce fichier sera chargé automatiquement. Les noms des paramètres (`iso`, `f-number`, etc.) dépendent de votre modèle d'appareil photo.

    Exemple :

    .. code-block:: json

        {
          "iso": "200",
          "f-number": "8",
          "shutterspeed": "1/125",
          "imageformat": "Large Fine JPEG"
        }

2.  **Script de calibration (`calibration.py`)**

    Modifiez la fonction `apply_color_calibration` dans le fichier `calibration.py` pour y insérer votre propre algorithme de traitement d'image.

    .. code-block:: python

        import numpy as np
        from skimage import exposure

        def apply_color_calibration(image: np.ndarray) -> np.ndarray:
            """
            REMPLACEZ CE CONTENU AVEC VOTRE PROPRE ALGORITHME.
            """
            p2, p98 = np.percentile(image, (2, 98))
            calibrated_image = exposure.rescale_intensity(image, in_range=(p2, p98))
            return (calibrated_image * 255).astype(np.uint8)


Lancer l'application
^^^^^^^^^^^^^^^^^^^^

Assurez-vous que votre environnement virtuel est activé, puis lancez le script principal :

.. code-block:: bash

    python main.py

Description de l'interface
^^^^^^^^^^^^^^^^^^^^^^^^^^

* **Contrôle de Capture** :
    * `Dossier de sauvegarde` : Choisissez le dossier où les images seront enregistrées.
    * `Préfixe du nom de fichier` : Définissez le préfixe pour les noms de fichiers.
    * `Capturer l'image` : Déclenche la prise de vue.

* **Options d'affichage** :
    * `Prévisualisation au premier plan` : Cochez cette case pour que le flux vidéo en direct reste toujours visible au-dessus des captures. Décochez-la pour que la dernière capture soit affichée au premier plan.

* **Réglages Appareil** :
    * Permet de charger manuellement un fichier de réglages `.json` et de les appliquer à l'appareil DSLR connecté.

* **Calibration** :
    * Sélectionnez un ou plusieurs calques d'images capturées dans la liste des calques de Napari, puis cliquez sur `Appliquer la calibration` pour exécuter le script `calibration.py`.


Notes pour les utilisateurs Windows
-----------------------------------

La bibliothèque `python-gphoto2` n'est pas compatible avec Windows. L'application a été conçue pour gérer cette situation :

* Le fichier `requirements.txt` n'essaiera pas d'installer `gphoto2` sur Windows.
* Au démarrage, le script détectera l'absence de DSLR et se rabattra automatiquement sur la **webcam** de l'ordinateur.
* Si aucune webcam n'est trouvée, l'application démarrera en mode "factice" avec une image générée aléatoirement.
* Les fonctionnalités de réglages de l'appareil (via `camera_settings.json`) ne sont disponibles que pour les appareils DSLR et seront donc inopérantes sous Windows.