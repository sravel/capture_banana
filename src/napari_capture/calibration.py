# calibration.py (mis à jour)

import numpy as np
from skimage import exposure
import colour

from colour_checker_detection import detect_colour_checkers_segmentation

# Valeurs de référence pour la charte "ColorChecker Classic 24" (inchangé)
REFERENCE_SWATCHES_SRGB = np.array([
    [0.1180, 0.0812, 0.0581],  # 0: dark skin
    [0.7833, 0.6264, 0.4934],  # 1: light skin
    [0.3793, 0.4843, 0.6322],  # 2: blue sky
    [0.2191, 0.3663, 0.1783],  # 3: foliage
    [0.5402, 0.4303, 0.6909],  # 4: blue flower
    [0.4033, 0.7394, 0.3345],  # 5: bluish green
    [0.8541, 0.4975, 0.1650],  # 6: orange
    [0.2650, 0.2936, 0.7259],  # 7: purplish blue
    [0.6983, 0.3121, 0.2985],  # 8: moderate red
    [0.2031, 0.1251, 0.4578],  # 9: purple
    [0.5182, 0.6471, 0.1973],  # 10: yellow green
    [0.8228, 0.7025, 0.1539],  # 11: orange yellow
    [0.1600, 0.1843, 0.6272],  # 12: blue
    [0.2842, 0.6128, 0.2520],  # 13: green
    [0.5833, 0.1911, 0.1650],  # 14: red
    [0.8732, 0.8128, 0.0591],  # 15: yellow
    [0.5843, 0.2872, 0.5448],  # 16: magenta
    [0.1000, 0.3544, 0.6970],  # 17: cyan
    [0.9532, 0.9627, 0.9734],  # 18: white
    [0.5960, 0.6000, 0.6088],  # 19: neutral 8
    [0.3686, 0.3715, 0.3774],  # 20: neutral 6.5
    [0.1980, 0.2000, 0.2048],  # 21: neutral 5
    [0.0882, 0.0882, 0.0891],  # 22: neutral 3.5
    [0.0353, 0.0353, 0.0353],  # 23: black
])


def simple_contrast_stretch(image: np.ndarray) -> np.ndarray:
    image_float = image.astype(np.float32) / 255.0
    p2, p98 = np.percentile(image_float, (2, 98))
    stretched_image = exposure.rescale_intensity(image_float, in_range=(p2, p98))
    return (stretched_image * 255).astype(np.uint8)


def calibrate_with_color_checker(image: np.ndarray, bounding_box) -> np.ndarray:
    image_float = image.astype(np.float32) / 255.0
    y_min, x_min = np.min(bounding_box, axis=0).astype(int)
    y_max, x_max = np.max(bounding_box, axis=0).astype(int)
    roi_image = image_float[y_min:y_max, x_min:x_max]

    # On renvoie aussi l'image ROI pour le débogage
    swatches_data = detect_colour_checkers_segmentation(roi_image)

    if not swatches_data:
        # On lève une ValueError si la détection échoue, pour déclencher le mode manuel
        raise ValueError("Détection automatique échouée.")

    detected_swatches_rgb = swatches_data[0]

    calibrated_image = colour.characterisation.colour_correction(
        image_float, detected_swatches_rgb, REFERENCE_SWATCHES_SRGB, method='Finlayson 2015'
    )
    calibrated_image = np.clip(calibrated_image, 0, 1)

    print("Calibration automatique par charte terminée avec succès.")
    return (calibrated_image * 255).astype(np.uint8), roi_image


# NOUVEAU : Fonction pour la calibration manuelle avec des points
def calibrate_with_manual_points(image: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Calibre une image en utilisant 6 points clés sélectionnés manuellement."""
    if len(points) != 6:
        raise ValueError(f"6 points sont attendus, mais {len(points)} ont été fournis.")

    image_float = image.astype(np.float32) / 255.0

    # Indices des patchs de référence dans REFERENCE_SWATCHES_SRGB
    # Ordre : Blanc, Gris 50%, Noir, Rouge, Vert, Bleu
    reference_indices = [18, 21, 23, 14, 13, 12]

    # On récupère les couleurs de référence correspondantes
    target_colors = REFERENCE_SWATCHES_SRGB[reference_indices]

    # On récupère les couleurs mesurées aux emplacements des points
    # Les coordonnées des points sont (y, x), il faut les inverser pour l'indexation
    measured_colors = []
    for y, x in points:
        # On prend une petite moyenne autour du point pour plus de stabilité
        patch = image_float[int(y) - 2:int(y) + 3, int(x) - 2:int(x) + 3]
        measured_colors.append(np.mean(patch, axis=(0, 1)))

    measured_colors = np.array(measured_colors)

    # On calcule la correction avec ce sous-ensemble de couleurs
    calibrated_image = colour.characterisation.colour_correction(
        image_float, measured_colors, target_colors, method='Finlayson 2015'
    )

    calibrated_image = np.clip(calibrated_image, 0, 1)
    print("Calibration manuelle par points terminée avec succès.")
    return (calibrated_image * 255).astype(np.uint8)