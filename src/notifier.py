# notifier.py
import os
import io
import time

from config import PHOTOS_FOLDER, MAX_CANDIDATES
from analyzer import compute_score, gen_caption_suggestion
from db import (mark_suggested, unprocessed_candidates, get_image_score_from_cache, get_all_skipped,
                store_score_cache)
from utils import read_image_bytes
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from PIL import Image
from logger import Logger

LOGGER = Logger(log_file_name="notifier.log")


def _evaluate(filename, cache_score, skipped):
    full = os.path.join(PHOTOS_FOLDER, filename)
    LOGGER.info(f"Evaluating {filename}")
    start_time = time.time()
    try:
        b = read_image_bytes(full)
        analysis = compute_score(b, cache_score=cache_score, filename=filename)
        if skipped:
            analysis["score"] = analysis["score"] - 0.05
        caption = gen_caption_suggestion(filename, analysis)
        if cache_score is None or not cache_score:
            store_score_cache(
                filename=filename,
                aesthetic=analysis.get("aesthetic", 0.0),
                sharpness=analysis.get("sharpness", 0.0),
                exposure=analysis.get("exposure", 0.0),
                composition=analysis.get("composition", 0.0),
                color_harmony=analysis.get("color_harmony", 0.0),
                face=analysis.get("face_count", 0.0),
                dom=analysis.get("dom", 0.0),
                avg_sat=analysis.get("avg_sat", 0.0),
                top_hue=analysis.get("top_hue", "")
            )
        LOGGER.info(f"Time taken for {filename}: {time.time() - start_time}")
        return analysis["score"], filename, b, caption, analysis
    except Exception as e:
        # skip problematic files
        LOGGER.warning(f"Skipping {filename} due to error: {e}")
        LOGGER.info(f"Time taken for {filename}: {time.time() - start_time}")
        return float("-inf"), filename, None, "", {}


def choose():
    """
    Scans local folder, picks the best candidate (by analyzer score),
    logs it as suggested and sends to CHAT_ID via provided bot.
    """
    # gather candidates
    candidates = unprocessed_candidates(PHOTOS_FOLDER, max_candidates=MAX_CANDIDATES)
    if not candidates:
        # nothing to suggest
        return None

    evaluated = {}
    cache_scores = get_image_score_from_cache(filenames=candidates)
    skipped_filenames = get_all_skipped()
    start = time.time()
    for fname in candidates:
        analysis = _evaluate(
            filename=fname,
            cache_score=cache_scores.get(fname),
            skipped=True if fname in skipped_filenames else False,
        )
        evaluated[fname] = analysis
    # with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_PROCESSES) as executor:
    #     future_to_path = {
    #         executor.submit(_evaluate, **{
    #             "filename": fname,
    #             "cache_score": cache_scores.get(fname),
    #             "skipped": True if fname in skipped_filenames else False
    #         }): fname
    #         for fname in candidates
    #     }
    #
    #     for future in concurrent.futures.as_completed(future_to_path):
    #         path = future_to_path[future]
    #         try:
    #             # We apply the timeout to each individual task's result
    #             analysis = future.result(timeout=PROCESS_TIMEOUT)
    #             evaluated[path] = analysis
    #         except concurrent.futures.TimeoutError:
    #             print(f"⌛ Skipping {path}: Analysis took too long.")
    #             evaluated[path] = (float("-inf"), path, None, "", {})
    #         except Exception as e:
    #             print(f"❌ Error analyzing {path}: {e}")
    #             evaluated[path] = (float("-inf"), path, None, "", {})

    LOGGER.info(f"Time taken to evaluate: {time.time() - start}")

    if not evaluated:
        return None

    evaluated = sorted(list(evaluated.values()), key=lambda x: x[0], reverse=True)
    top_score, top_fname, top_bytes, top_caption, top_analysis = evaluated[0]

    # mark suggested in DB
    mark_suggested(top_fname, float(top_score), top_caption)
    caption = f"Suggested: {top_fname}\nScore: {top_score:.3f}\n\n{top_caption}"

    # prepare keyboard
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{top_fname}"),
            InlineKeyboardButton("⏭ Skip", callback_data=f"skip:{top_fname}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject:{top_fname}")
        ]
    ])

    # create a thumbnail to reduce payload (optional)
    try:
        img = Image.open(io.BytesIO(top_bytes))
        img.thumbnail((1200, 1200))
        bio = io.BytesIO()
        img.save(bio, format="JPEG", quality=85)
        bio.seek(0)
    except Exception:
        bio = io.BytesIO(top_bytes)
        bio.seek(0)

    return top_fname, top_score, caption, bio, keyboard
