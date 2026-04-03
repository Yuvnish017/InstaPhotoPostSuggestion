# analyzer.py
"""Image quality analysis utilities and scoring composition."""

import ast
import json
import os
import time
import traceback
from PIL import Image
import numpy as np
import cv2
from io import BytesIO
import math
import datetime
from datetime import datetime
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from ai_edge_litert.interpreter import Interpreter
from config import MODELS_PATH
from logger import Logger

interpreter = Interpreter(model_path=os.path.join(MODELS_PATH, "nima_mobilenet.tflite"))
interpreter.allocate_tensors()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

LOGGER = Logger(log_file_name="analyzer.log")


def pil_from_bytes(b):
    """Decode raw image bytes into an RGB PIL image."""
    return Image.open(BytesIO(b)).convert("RGB")


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
    final_score = np.sum(output[0] * scores)
    return final_score / 10.0  # normalize to 0–1


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

    # Normalize position
    x_norm = x / w
    y_norm = y / h

    # Thirds positions
    thirds = [1/3, 2/3]

    def distance_to_thirds(v):
        return min([abs(v - t) for t in thirds])

    dx = distance_to_thirds(x_norm)
    dy = distance_to_thirds(y_norm)

    dist = np.sqrt(dx**2 + dy**2)

    # Convert to score (closer = better)
    score = np.exp(-dist * 5)

    return score


def composition_score(image):
    """Blend edge-density and thirds-based composition signals."""
    LOGGER.info("getting composition score..")
    edge_score = edge_density_score(image)

    saliency_map = get_saliency_map(image)
    thirds_score = rule_of_thirds_score(saliency_map)

    # Weighted combination
    comp_score = 0.6 * thirds_score + 0.4 * edge_score

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


def gen_caption_suggestion(filename, analysis):
    """Build a short human-readable caption and hashtag suggestion."""
    parts = []
    if analysis["face_count"] > 0:
        parts.append("portrait")
    else:
        parts.append("shot")

    # dom = analysis["dominant_color"]
    # r, g, b = dom
    # if r > 180 and g > 120:
    #     parts.append("warm tones")
    # elif b > 140:
    #     parts.append("cool tones")

    hashtags = []
    if analysis["face_count"] > 0:
        hashtags += ["#portrait", "#people"]
    else:
        hashtags += ["#photooftheday"]
    hashtags += [f"#{datetime.utcnow().year}"]

    caption = f"{filename} | " + " · ".join(parts) + "\n\n" + " ".join(hashtags)
    return caption
