# Napari Capture

A simple Python interface based on [Napari](https://napari.org/) for capturing photos from a digital camera (Nikon/Canon DSLR) or a webcam.

![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

<!-- Placeholder for a screenshot -->
<!-- ![Application Screenshot](path/to/screenshot.png) -->

## Table of Contents
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Interface Description](#interface-description)
- [Notes for Windows Users](#notes-for-windows-users)

## Features

*   **Dual Capture Source**: Control DSLR cameras via `gphoto2` (Linux/macOS) with automatic fallback to a webcam (via OpenCV) if no DSLR is detected. A "dummy" mode is used if no camera is found.
*   **Live Preview**: A real-time video stream from the camera is displayed directly in the interface.
*   **File Organization**:
    *   Mandatory definition of a save folder.
    *   Incremental file naming (`prefix_0001.tiff`, `prefix_0002.tiff`, etc.). The counter automatically adjusts based on existing files.
*   **Layer Management**:
    *   Each capture is added as a new layer in Napari.
    *   A checkbox allows choosing whether the preview or the last capture is displayed in the foreground.
    *   Deleting a capture layer in Napari also deletes the corresponding file on disk.
    *   The preview layer is "locked" and cannot be deleted.
*   **External Configuration**:
    *   Automatic loading of a `camera_settings.json` settings file present in the save folder.
    *   Ability to apply a custom color calibration script (`calibration.py`) to captured images.
*   **Session Loading**: Existing images in the save folder are automatically loaded when the application starts.
*   **Advanced Calibration**:
    *   **Automatic Calibration**: Detects a color checker chart in the image and applies color correction automatically.
    *   **Manual Calibration**: If automatic detection fails, you can manually select 6 key color points (White, Mid-Gray, Black, Red, Green, Blue) for calibration.
    *   **Batch Calibration**: Apply the last successful calibration to all other images in the session.

## Installation

### Prerequisites

*   Python 3.8 or higher
*   For DSLR support on Linux/macOS, `libgphoto2` must be installed. On Debian/Ubuntu systems:
    ```bash
    sudo apt-get update && sudo apt-get install libgphoto2-dev
    ```

### Installation

You can install `napari-capture` directly from this repository using pip.

1.  **Clone the repository**:
    ```bash
    git clone <URL_OF_THE_GIT_REPOSITORY>
    cd napari-capture
    ```

2.  **Install the package**:
    For regular use:
    ```bash
    pip install .
    ```
    For development (installs in editable mode):
    ```bash
    pip install -e .
    ```

## Usage

### Launching the Application

Once installed, you can launch the application by simply running this command in your terminal:
```bash
napari-capture
```

### Configuration (Optional)

Before launching, you can still configure the application by placing specific files in your chosen save directory.

1.  **Device Settings (`camera_settings.json`)**

    Create a `camera_settings.json` file in the save folder. The application will automatically load these settings and apply them to a connected DSLR. The parameter names (`iso`, `f-number`, etc.) are specific to your camera model.

    Example:
    ```json
    {
      "iso": "200",
      "f-number": "8",
      "shutterspeed": "1/125",
      "imageformat": "Large Fine JPEG"
    }
    ```

2.  **Calibration Script (`calibration.py`)**

    The application's `calibration.py` module contains functions for color calibration. You can modify these functions to implement your own image processing algorithms if you install the package in editable mode.

## Interface Description

*   **Capture Control**:
    *   `Save Folder`: Choose the directory where images will be saved.
    *   `File Prefix`: Set the prefix for filenames.
    *   `Capture Image`: Triggers the capture.

*   **Display Options**:
    *   `Preview on Top`: Check this box to keep the live video stream always visible above the captures. Uncheck it to show the last capture in the foreground.

*   **Device Settings**:
    *   Allows manually loading a `.json` settings file and applying it to the connected DSLR device.

*   **Calibration**:
    *   **Simple Calibration**: Applies a basic contrast stretch to selected layers.
    *   **Checker Calibration**: A two-step process to calibrate using a color checker.
    *   **Batch Calibration**: Applies the last saved calibration to all other images.

## Notes for Windows Users

The `python-gphoto2` library is not compatible with Windows. The application is designed to handle this situation:

*   The application will not attempt to install `gphoto2` on Windows.
*   On startup, the script will detect the absence of a DSLR and will automatically fall back to the computer's **webcam**.
*   If no webcam is found, the application will start in "dummy" mode with a randomly generated image.
*   Device settings features (via `camera_settings.json`) are only available for DSLR devices and will therefore be inoperative under Windows.