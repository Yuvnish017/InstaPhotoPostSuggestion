# notifier.py
import os
import io
from config import PHOTOS_FOLDER, MAX_CANDIDATES, CHAT_ID
from analyzer import compute_score, gen_caption_suggestion
from db import init_db, mark_suggested, unprocessed_candidates
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot
from PIL import Image
from logger import Logger

# initialize DB (idempotent)
init_db()

LOGGER = Logger(log_file_name="notifier.log")


def _read_image_bytes(path):
    with open(path, "rb") as f:
        return f.read()


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

    evaluated = []
    for fname in candidates:
        full = os.path.join(PHOTOS_FOLDER, fname)
        LOGGER.info(f"Evaluating {fname}")
        try:
            b = _read_image_bytes(full)
            mtime = os.path.getmtime(full)
            analysis = compute_score(b, mtime)
            caption = gen_caption_suggestion(fname, analysis)
            evaluated.append((analysis["score"], fname, b, caption, analysis))
        except Exception as e:
            # skip problematic files
            LOGGER.warning(f"Skipping {fname} due to error: {e}")
            continue

    if not evaluated:
        return None, ""

    evaluated.sort(key=lambda x: x[0], reverse=True)
    top_score, top_fname, top_bytes, top_caption, top_analysis = evaluated[0]

    # mark suggested in DB
    mark_suggested(top_fname, float(top_score), top_caption)
    caption = f"Suggested: {top_fname}\nScore: {top_score:.3f}\n\n{top_caption}"

    # prepare keyboard
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{top_fname}"),
            InlineKeyboardButton("⏭ Skip", callback_data=f"skip:{top_fname}")
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
