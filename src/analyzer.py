# analyzer.py
"""Image quality analysis utilities and scoring composition."""

import ast
import json
import os
import time
import traceback
import numpy as np
import cv2
import math
import datetime
from datetime import datetime
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from ai_edge_litert.interpreter import Interpreter
from config import MODELS_PATH
from logger import Logger
from utils import pil_from_bytes

interpreter = Interpreter(model_path=os.path.join(MODELS_PATH, "nima_mobilenet.tflite"))
interpreter.allocate_tensors()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

LOGGER = Logger(log_file_name="analyzer.log")


def preprocess(img):
    """Prepare image tensor expected by the aesthetic TFLite model."""
    img = img.resize((224, 224))  # required input size

    img_array = np.array(img).astype("float32")
    # img_array = (img_array / 127.5) - 1

    # Add batch dimension
    img_array = np.expand_dims(img_array, axis=0)

    return img_array


def aesthetic_score(input_img):
    """Run the NIMA model and return normalized aesthetic score [0, 1]."""
    LOGGER.info("getting aesthetic score..")
    input_data = preprocess(input_img)

    interpreter.set_tensor(input_details[0]['index'], input_data)
    interpreter.invoke()

    output = interpreter.get_tensor(output_details[0]['index'])
    scores = np.arange(1, 11)  # 1 to 10
    mean_score = np.sum(output[0] * scores)
    variance = np.sum(output[0] * ((scores - mean_score) ** 2))
    return (0.8 * (mean_score / 10) + 0.2 * min(1, variance / 8))  # normalize to 0–1


def variance_of_laplacian(img_pil):
    """Return Laplacian variance, a common blur/sharpness proxy."""
    arr = np.array(img_pil.convert("L"))
    lap = cv2.Laplacian(arr, cv2.CV_64F)
    return float(lap.var())


def estimate_noise(image):
    """
    Estimate noise level using Laplacian-based MAD method
    Works well for natural images and is lightweight
    """
    gray = np.array(image.convert("L"))

    # Apply Laplacian (high-frequency component)
    lap = cv2.Laplacian(gray, cv2.CV_64F)

    # Median Absolute Deviation (robust to edges)
    med = np.median(lap)
    mad = np.median(np.abs(lap - med))

    # Convert MAD to standard deviation estimate
    noise_sigma = 1.4826 * mad

    return noise_sigma


def sharpness_score(img_pil):
    """Compute noise-adjusted sharpness score."""
    LOGGER.info("getting sharpness score..")
    sharp = variance_of_laplacian(img_pil)
    noise = estimate_noise(img_pil)
    sharpness = sharp / (noise + 1e-6)
    sharp_norm = math.tanh(sharpness / 50)
    return sharp_norm


def exposure_score(img_pil):
    """Estimate exposure/contrast quality score from grayscale statistics."""
    LOGGER.info("getting exposure score..")
    arr = np.array(img_pil.convert("L"))
    mean = np.mean(arr)
    std = np.std(arr)

    exp_score = 1 - abs(mean - 127) / 127
    contrast_score = std / 64

    final_exposure = 0.7 * exp_score + 0.3 * contrast_score
    return final_exposure


def sat_hue_info(image):
    """Extract dominant hue, top hue bins, and average saturation."""
    LOGGER.info("getting sat hue info..")
    hsv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2HSV)

    hue = hsv[:, :, 0]
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]

    # Filter low-quality pixels
    mask = (sat > 40) & (val > 40)

    if np.sum(mask) == 0:
        return None, [], None  # fallback case

    filtered_hue = hue[mask]

    hist = cv2.calcHist([filtered_hue.astype('uint8')], [0], None, [36], [0, 180])

    dominant_bin = np.argmax(hist)
    dom_hue = dominant_bin * 5

    hist = hist.flatten()
    top_bins = hist.argsort()[-3:][::-1]
    top_hues = [b * (180 // 36) for b in top_bins]

    avg_sat = np.mean(sat)

    return dom_hue, top_hues, avg_sat


def hue_distance(h1, h2):
    """Return circular hue distance in OpenCV hue range [0, 180)."""
    diff = abs(h1 - h2)
    return min(diff, 180 - diff)


def color_harmony_score(hues):
    """Heuristic color harmony score from primary hue relationships."""
    LOGGER.info("getting color harmony score..")
    if len(hues) < 2:
        return 0.5  # neutral

    d12 = hue_distance(hues[0], hues[1])

    # analogous (close colors)
    if d12 < 20:
        return 0.8

    # complementary (~90 in OpenCV scale)
    elif 70 < d12 < 110:
        return 0.9

    # triadic (~60)
    elif 40 < d12 < 80:
        return 0.7

    else:
        return 0.5


def face_count(img_pil):
    """Return face-based score (penalizes overly crowded frames)."""
    LOGGER.info("getting face score..")
    model_asset_path = os.path.join(MODELS_PATH, 'blaze_face_short_range.tflite')
    options = vision.FaceDetectorOptions(
        base_options=python.BaseOptions(model_asset_path=model_asset_path),
        running_mode=vision.RunningMode.IMAGE
    )
    faces = []
    try:
        with vision.FaceDetector.create_from_options(options) as detector:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.array(img_pil))

            # 5. Perform face detection
            detection_result = detector.detect(mp_image)

            faces = detection_result.detections
    except Exception as err:
        LOGGER.error(f"Face count failed: {err}")
        LOGGER.error(f"{traceback.format_exc()}")

    return math.exp(-0.5 * max(0, int(len(faces))-3))


def get_season(month):
    """Map month to simple meteorological season bucket."""
    if month in [12, 1, 2]:
        return "winter"
    elif month in [3, 4, 5]:
        return "spring"
    elif month in [6, 7, 8]:
        return "summer"
    else:
        return "autumn"


def season_match_score(dominant_hue, avg_sat):
    """Score whether dominant palette fits current season heuristics."""
    season = get_season(datetime.now().month)
    if dominant_hue is None:
        return 0.5

    # Winter → cool, muted
    if season == "winter":
        if 90 <= dominant_hue <= 140 and avg_sat < 100:
            return 0.9
        return 0.4

    # Spring → green, fresh
    elif season == "spring":
        if 45 <= dominant_hue <= 100:
            return 0.9
        return 0.5

    # Summer → vibrant, high saturation
    elif season == "summer":
        return 0.6 + 0.4 * (avg_sat / 255)

    # Autumn → warm tones
    elif season == "autumn":
        if 10 <= dominant_hue <= 45:
            return 0.9
        return 0.5


def edge_density_score(image):
    """Compute visual complexity score based on Canny edge density."""
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)

    edges = cv2.Canny(gray, 100, 200)

    density = np.sum(edges > 0) / edges.size

    # Ideal range ~0.05–0.15
    score = np.exp(-((density - 0.1) ** 2) / 0.002)

    return score


def get_saliency_map(image):
    """Generate saliency map used by composition heuristics."""
    saliency = cv2.saliency.StaticSaliencySpectralResidual_create()
    success, saliency_map = saliency.computeSaliency(np.array(image))

    if not success:
        return None

    return saliency_map


def rule_of_thirds_score(saliency_map):
    """Score proximity of most salient point to thirds intersections."""
    if saliency_map is None:
        return 0.5

    h, w = saliency_map.shape

    # Find most salient point
    y, x = np.unravel_index(np.argmax(saliency_map), saliency_map.shape)

    # Thirds positions
    thirds = [(w / 3, h / 3), (w / 3, 2 * h / 3), (2 * w / 3, h / 3), (2 * w / 3, 2 * h / 3)]
    min_dist = min(np.sqrt((x - tx) ** 2 + (y - ty) ** 2) for tx, ty in thirds)
    diag = np.sqrt(w**2 + h**2)
    return np.exp(-(min_dist / (0.15 * diag)) ** 2)


def leading_lines_score(image):
    """Placeholder for future leading lines composition heuristic."""
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100, minLineLength=50, maxLineGap=10)
    if lines is None:
        return 0.3
    angles = []
    for line in lines[:50]:
        x1, y1, x2, y2 = line[0]
        angle = math.atan2(y2 - y1, x2 - x1)
        angles.append(angle)
    if not angles:
        return 0.3
    angle_std = np.std(angles)
    score = np.exp(-angle_std)
    return float(score)


def aspect_ratio_score(image, lines_score):
    w, h = image.size
    aspect = w / h
    # portrait
    if aspect < 0.9:
        return 0.7 + 0.3 * lines_score
    
    # square-ish
    elif 0.9 <= aspect <= 1.2:
        return 0.8
    
    # landscape
    else:
        return 0.75
    

def visual_balance_score(image, saliency_map):
    if saliency_map is None:
        return 0.5

    h, w = saliency_map.shape
    center_x, center_y = w / 2, h / 2

    y_indices, x_indices = np.indices(saliency_map.shape)
    distances = np.sqrt((x_indices - center_x) ** 2 + (y_indices - center_y) ** 2)

    weighted_dist = np.sum(saliency_map * distances) / np.sum(saliency_map)
    max_dist = np.sqrt(center_x**2 + center_y**2)

    score = 1 - (weighted_dist / max_dist)
    return float(score)


def composition_score(image):
    """Blend edge-density and thirds-based composition signals."""
    LOGGER.info("getting composition score..")
    saliency_map = get_saliency_map(image)

    edge_score = edge_density_score(image)
    thirds_score = rule_of_thirds_score(saliency_map)
    leading_line_score = leading_lines_score(image)
    aspect_score = aspect_ratio_score(image, leading_line_score)
    balance_score = visual_balance_score(image, saliency_map)

    # Weighted combination
    comp_score = (
        0.35 * thirds_score +
        0.25 * leading_line_score +
        0.20 * balance_score +
        0.10 * edge_score +
        0.10 * aspect_score
    )

    return comp_score


def get_or_compute(cache, key, fn):
    """Return cached metric or compute it lazily with `fn`."""
    return cache[key] if key in cache else fn()


def compute_score(image_bytes, filename, cache_score=None):
    """Compute aggregate photo score and return metric breakdown dictionary."""
    start_time = time.time()
    try:
        if not cache_score:
            LOGGER.info(f"{filename} cache not found")
            cache_score = {}
        LOGGER.info(f"{filename} score cache : {cache_score}")
        img = pil_from_bytes(image_bytes)

        if all(k in cache_score for k in ["dom", "avg_sat", "top_hue"]):
            dom = cache_score["dom"]
            avg_sat = cache_score["avg_sat"]
            top_hue = cache_score["top_hue"]

            try:
                top_hue = ast.literal_eval(top_hue)
            except Exception:
                # Cache value may be malformed from older rows; fallback safely.
                top_hue = []
        else:
            dom, top_hue, avg_sat = sat_hue_info(img)
        LOGGER.info(f"dom: {dom}, top_hue: {top_hue}, avg_sat: {avg_sat}")

        aesthetic = get_or_compute(cache_score, "aesthetic", lambda: aesthetic_score(img))
        sharp_norm = get_or_compute(cache_score, "sharpness", lambda: sharpness_score(img))
        exposure = get_or_compute(cache_score, "exposure", lambda: exposure_score(img))
        color_harmony = get_or_compute(cache_score, "color_harmony", lambda: color_harmony_score(top_hue))
        faces = get_or_compute(cache_score, "face", lambda: face_count(img))
        comp_score = get_or_compute(cache_score, "composition", lambda: composition_score(img))

        face_norm = min(1.0, faces / 3.0)
        face_penalty = 0 if faces <= 3 else -0.15 * (faces - 3)

        season = season_match_score(dom, avg_sat)

        score = (
            0.35 * aesthetic +   # DL model
            0.20 * sharp_norm +
            0.15 * exposure +
            0.05 * comp_score +
            0.10 * color_harmony +
            0.15 * season +
            0.05 * face_norm
        )
        score += face_penalty
        LOGGER.info(f"time taken to analyze {filename}: {time.time() - start_time}")

        return {
            "score": float(score),
            "aesthetic": float(aesthetic),
            "sharpness": float(sharp_norm),
            "exposure": float(exposure),
            "composition": float(comp_score),
            "color_harmony": float(color_harmony),
            "face": float(face_norm),
            "face_count": int(faces),
            "dom": float(dom),
            "avg_sat": float(avg_sat),
            "top_hue": str(top_hue),
            "season_score": float(season)
        }
    except Exception as err:
        LOGGER.error(f"Analyzer failed for {filename}: {err}")
        LOGGER.error(traceback.format_exc())
        LOGGER.info(f"time taken to analyze {filename}: {time.time() - start_time}")
        return {
            "score": 0.0,
            "aesthetic": 0.0,
            "sharpness": 0.0,
            "exposure": 0.0,
            "composition": 0.0,
            "color_harmony": 0.0,
            "face": 0.0,
            "face_count": 0.0,
            "dom": 0.0,
            "avg_sat": 0.0,
            "top_hue": "",
            "season_score": 0.0
        }

