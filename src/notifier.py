# notifier.py
import concurrent.futures
import os
import io
import time

from config import PHOTOS_FOLDER, MAX_CANDIDATES, CHAT_ID, MAX_PROCESSES, PROCESS_TIMEOUT
from analyzer import compute_score, gen_caption_suggestion
from db import init_db, mark_suggested, unprocessed_candidates, is_skipped
from utils import read_image_bytes
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot
from PIL import Image
from logger import Logger


# initialize DB (idempotent)
init_db()

LOGGER = Logger(log_file_name="notifier.log")


def _evaluate(filename):
    full = os.path.join(PHOTOS_FOLDER, filename)
    LOGGER.info(f"Evaluating {filename}")
    try:
        b = read_image_bytes(full)
        mtime = os.path.getmtime(full)
        analysis = compute_score(b, filename)
        was_skipped = is_skipped(filename=filename)
        if was_skipped:
            analysis["score"] = analysis["score"] - 0.05
        caption = gen_caption_suggestion(filename, analysis)
        return analysis["score"], filename, b, caption, analysis
    except Exception as e:
        # skip problematic files
        LOGGER.warning(f"Skipping {filename} due to error: {e}")
        return float("-inf"), filename, None, "", {}


async def choose_and_send(bot: Bot):
    """
    Scans local folder, picks the best candidate (by analyzer score),
    logs it as suggested and sends to CHAT_ID via provided bot.
    """
    # gather candidates
    candidates = unprocessed_candidates(PHOTOS_FOLDER, max_candidates=MAX_CANDIDATES)
    if not candidates:
        # nothing to suggest
        return None, ""

    evaluated = {}
    start = time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_PROCESSES) as executor:
        future_to_path = {
            executor.submit(_evaluate, fname): fname
            for fname in candidates
        }

        for future in concurrent.futures.as_completed(future_to_path):
            path = future_to_path[future]
            try:
                # We apply the timeout to each individual task's result
                analysis = future.result(timeout=PROCESS_TIMEOUT)
                evaluated[path] = analysis
            except concurrent.futures.TimeoutError:
                print(f"⌛ Skipping {path}: Analysis took too long.")
                evaluated[path] = (float("-inf"), path, None, "", {})
            except Exception as e:
                print(f"❌ Error analyzing {path}: {e}")
                evaluated[path] = (float("-inf"), path, None, "", {})

    LOGGER.info(f"Time taken to evaluate: {time.time() - start}")

    if not evaluated:
        return None, ""

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

    # send via bot
    await bot.send_photo(
        chat_id=CHAT_ID,
        photo=bio,
        caption=caption,
        reply_markup=keyboard
    )

    LOGGER.info(f"Sent suggestion: {top_fname}, {top_score}")
    return top_fname
