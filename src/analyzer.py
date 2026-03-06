# analyzer.py
from PIL import Image
import numpy as np
import cv2
from io import BytesIO
from sklearn.cluster import KMeans
import math
import datetime


def pil_from_bytes(b):
    return Image.open(BytesIO(b)).convert("RGB")


def variance_of_laplacian(img_pil):
    arr = np.array(img_pil.convert("L"))
    lap = cv2.Laplacian(arr, cv2.CV_64F)
    return float(lap.var())


def brightness_score(img_pil):
    arr = np.array(img_pil.convert("L"))
    return float(arr.mean()) / 255.0


def dominant_color(img_pil, n_colors=3):
    arr = np.array(img_pil).reshape(-1, 3).astype(float)
    if arr.shape[0] > 5000:
        sample_idx = np.random.choice(arr.shape[0], 5000, replace=False)
        sample = arr[sample_idx]
    else:
        sample = arr
    kmeans = KMeans(n_clusters=min(n_colors, len(sample)), random_state=0, n_init=4)
    kmeans.fit(sample)
    counts = np.bincount(kmeans.labels_)
    dominant = kmeans.cluster_centers_[np.argmax(counts)]
    return tuple(int(x) for x in dominant)


def color_warmth(rgb):
    r, g, b = rgb
    return (r - b) / 255.0  # negative -> cool, positive -> warm


def face_count(img_pil):
    gray = np.array(img_pil.convert("L"))
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    return int(len(faces))


def season_match_score(file_mtime, dominant_rgb):
    # file_mtime: float timestamp (os.path.getmtime)
    try:
        dt = datetime.datetime.fromtimestamp(file_mtime)
        month = dt.month
    except Exception:
        month = None
    warmth = color_warmth(dominant_rgb)
    # heuristics: winter = months 12/1/2 prefer cool (neg warmth)
    if month in (12, 1, 2):
        return 0.5 + ( -warmth ) * 0.5
    if month in (3, 4, 5):
        return 0.5 + (abs(warmth) * 0.2)
    if month in (6, 7, 8):
        return 0.5 + (warmth) * 0.5
    if month in (9, 10, 11):
        return 0.5 + (warmth) * 0.4
    return 0.5


def compute_score(image_bytes, file_mtime):
    img = pil_from_bytes(image_bytes)
    sharp = variance_of_laplacian(img)  # larger -> sharper
    bright = brightness_score(img)
    dom = dominant_color(img)
    faces = face_count(img)
    season = season_match_score(file_mtime, dom)

    # normalize sharp roughly using tanh
    sharp_norm = math.tanh(sharp / 100.0)  # ~0..1 scale
    face_norm = min(1.0, faces / 3.0)

    score = (0.55 * sharp_norm) + (0.2 * bright) + (0.15 * season) + (0.1 * face_norm)

    return {
        "score": float(score),
        "sharpness": float(sharp_norm),
        "brightness": float(bright),
        "dominant_color": dom,
        "face_count": int(faces),
        "season_score": float(season)
    }


def gen_caption_suggestion(filename, analysis):
    parts = []
    if analysis["face_count"] > 0:
        parts.append("portrait")
    else:
        parts.append("shot")

    dom = analysis["dominant_color"]
    r, g, b = dom
    if r > 180 and g > 120:
        parts.append("warm tones")
    elif b > 140:
        parts.append("cool tones")

    hashtags = []
    if analysis["face_count"] > 0:
        hashtags += ["#portrait", "#people"]
    else:
        hashtags += ["#photooftheday"]
    hashtags += [f"#{datetime.datetime.utcnow().year}"]

    caption = f"{filename} | " + " · ".join(parts) + "\n\n" + " ".join(hashtags)
    return caption
