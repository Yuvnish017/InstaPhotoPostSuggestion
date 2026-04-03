# main.py
"""Telegram bot entrypoint for image suggestion workflow."""

import os
import shutil
import time
import traceback
import asyncio
from datetime import datetime
import nest_asyncio
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from config import BOT_TOKEN, PHOTOS_FOLDER, POSTED_FOLDER, SKIP_RETRY, CHAT_ID, SCHEDULE_MINUTE, SCHEDULE_HOUR
from notifier import choose
from db import (mark_approved, mark_skipped, init_db, get_analysis_stats, get_latest_health_report, mark_rejected,
                store_score_cache, get_filenames_in_scores_db)
from utils import next_scheduled_time_epoch, read_image_bytes
from logger import Logger
from resource_monitor import ResourceMonitor
from analyzer import compute_score

# ensure folders and DB exist
os.makedirs(PHOTOS_FOLDER, exist_ok=True)
os.makedirs(POSTED_FOLDER, exist_ok=True)
init_db()

monitor = ResourceMonitor()
monitor.start()

NEXT_SCHEDULE = next_scheduled_time_epoch(target_weekday=6, hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE)
NEXT_CACHE_UPDATE = next_scheduled_time_epoch(target_weekday=5, hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE)
LOGGER = Logger(log_file_name="main.log")


def _cache_update():
    """Backfill score cache for images that are not yet cached."""
    LOGGER.info("Cache update running...")
    filenames_in_cache = get_filenames_in_scores_db()
    if not filenames_in_cache:
        filenames_in_cache = []
    for image in os.listdir(PHOTOS_FOLDER):
        if not image.lower().endswith((".jpg", ".jpeg", ".png")) or image in filenames_in_cache:
            continue
        score_info = compute_score(image_bytes=read_image_bytes(os.path.join(PHOTOS_FOLDER, image)), filename=image)
        store_score_cache(
            filename=image,
            aesthetic=score_info.get("aesthetic", 0.0),
            sharpness=score_info.get("sharpness", 0.0),
            exposure=score_info.get("exposure", 0.0),
            composition=score_info.get("composition", 0.0),
            color_harmony=score_info.get("color_harmony", 0.0),
            face=score_info.get("face_count", 0.0),
            avg_sat=score_info.get("avg_sat", 0.0),
            dom=score_info.get("dom", 0.0),
            top_hue=score_info.get("top_hue", "")
        )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle `/start` command."""
    await update.message.reply_text(
        "Insta-helper bot is running. You will receive 1 suggestion per week at configured time."
    )


async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle `/whoami` command and return current chat id."""
    cid = update.effective_chat.id
    await update.message.reply_text(f"Your chat id is: {cid}")


async def next_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle `/next_schedule` command."""
    await update.message.reply_text(
        f"Next run is scheduled at {datetime.fromtimestamp(NEXT_SCHEDULE).strftime('%Y/%m/%d:%H:%M')}"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle `/status` command with latest telemetry snapshot."""
    row = get_latest_health_report()

    if not row:
        await update.message.reply_text("❌ No telemetry data found yet.")
        return

    # row structure based on our schema: (id, timestamp, cpu, mem, temp, is_busy)
    _, timestamp, cpu, mem, temp, is_busy = row

    status_emoji = "🔥" if temp > 75 else "🟢"
    busy_status = "🏃 Analyzing Photos" if is_busy else "😴 Idling"

    message = (
        f"🖥️ **Pi 4 Health Report**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🕒 Time: `{timestamp}`\n"
        f"📊 Status: {busy_status}\n"
        f"{status_emoji} Temp: `{temp:.1f}°C`\n"
        f"🧠 App RAM: `{mem:.1f} MB`\n"
        f"⚡ CPU Load: `{cpu:.1f}%`"
    )

    await update.message.reply_text(message, parse_mode='Markdown')


async def last_run_utilization_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle `/last_run` command with aggregated busy-window stats."""
    row = get_analysis_stats()

    if not row:
        await update.message.reply_text("❌ No telemetry data found yet.")
        return

    cpu, temp, mem = row
    if cpu is None or temp is None or mem is None:
        await update.message.reply_text("❌ No completed analysis utilization window found yet.")
        return

    status_emoji = "🔥" if temp > 75 else "🟢"

    message = (
        f"🖥️ **Pi 4 Health Report During Last Image Analysis**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{status_emoji} Temp: `{temp:.1f}°C`\n"
        f"🧠 App RAM: `{mem:.1f} MB`\n"
        f"⚡ CPU Load: `{cpu:.1f}%`"
    )

    await update.message.reply_text(message, parse_mode='Markdown')


async def _process_suggestion(bot, chat_id: int):
    """Run suggestion flow in background and send response to chat."""
    start_time = time.time()
    try:
        monitor.set_high_priority(True)  # Start high-res logging
        result = await asyncio.to_thread(choose)

        if not result:
            await bot.send_message(chat_id=chat_id, text="No candidates available.")
            return

        top_fname, top_score, caption, bio, keyboard = result

        # send via bot
        await bot.send_photo(
            chat_id=chat_id,
            photo=bio,
            reply_markup=keyboard
        )

        LOGGER.info(f"Sent suggestion: {top_fname}, {top_score}")

        if top_fname:
            await bot.send_message(chat_id=chat_id, text=f"📸 {caption}")
        else:
            await bot.send_message(chat_id=chat_id, text="No candidates available right now.")
    except Exception as err:
        LOGGER.error(f"Error in background suggestion: {err}, traceback: {traceback.format_exc()}")
        await bot.send_message(chat_id=chat_id, text="❌ An error occurred while processing suggestion.")
    finally:
        monitor.set_high_priority(False)  # Go back to sleep
        LOGGER.info(f"Time taken to process suggestion: {time.time() - start_time}")


async def suggest_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle `/suggest_now` and trigger non-blocking suggestion job."""
    await update.message.reply_text("🔎 Processing suggestion...")

    # "Fire and forget" - this releases the chat lock immediately
    asyncio.create_task(_process_suggestion(context.bot, update.effective_chat.id))


async def simple_echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback text handler confirming bot responsiveness."""
    await update.message.reply_text("I hear you. Try /suggest_now or /whoami.")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    CallbackQuery data format: 'approve:filename' or 'skip:filename'
    """
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    try:
        action, fname = data.split(":", 1)
    except ValueError:
        await query.edit_message_text("Invalid action.")
        return

    filepath = os.path.join(PHOTOS_FOLDER, fname)
    if action == "approve":
        mark_approved(fname)
        # move to posted folder
        try:
            dest = os.path.join(POSTED_FOLDER, fname)
            if os.path.exists(dest):
                base, ext = os.path.splitext(fname)
                i = 1
                while True:
                    newname = f"{base}_{i}{ext}"
                    dest = os.path.join(POSTED_FOLDER, newname)
                    if not os.path.exists(dest):
                        break
                    i += 1
            shutil.move(filepath, dest)

            await query.edit_message_caption(f"✅ Approved & moved to posted: {os.path.basename(dest)}")
        except FileNotFoundError:
            await query.edit_message_caption(f"✅ Approved (file not found locally). Marked as posted.")
        except Exception as e:
            await query.edit_message_caption(f"✅ Approved, but failed to move file: {e}")

    elif action == "skip":
        mark_skipped(fname)
        await query.edit_message_caption(f"⏭ Skipped: {fname}")
        num_skips = context.user_data.get("skip_count", 0)
        num_skips += 1
        context.user_data["skip_count"] = num_skips
        LOGGER.info(f"Skip count: {num_skips}/{SKIP_RETRY}")
        if num_skips >= SKIP_RETRY:
            LOGGER.info(f"Already skipped {num_skips} times, will not process more suggestions for current request..")
            # Use query.message or effective_chat to send the new message
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"Already skipped {num_skips} times. Stopping suggestions for now."
            )
            context.user_data["skip_count"] = 0
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"🔎 Suggestion {num_skips}/{SKIP_RETRY} skipped. Getting next..."
            )

            # "Fire and forget" - this releases the chat lock immediately
            asyncio.create_task(_process_suggestion(context.bot, update.effective_chat.id))
    elif action == "reject":
        mark_rejected(fname)
        await query.edit_message_caption(f"❌ Rejected: {fname}")
    else:
        await query.edit_message_text("Unknown action.")


async def suggestion_scheduler_task(app):
    """
    Background loop that sends weekly scheduled suggestions.
    """
    global NEXT_SCHEDULE
    bot = app.bot
    while True:
        curr_epoch = int(datetime.now().timestamp())
        wait_seconds = NEXT_SCHEDULE - curr_epoch
        LOGGER.info(f"Scheduler sleeping for {int(wait_seconds)} seconds until next run at {datetime.fromtimestamp(NEXT_SCHEDULE).strftime('%Y/%m/%d:%H:%M')}")
        await asyncio.sleep(wait_seconds)

        # "Fire and forget" - this releases the chat lock immediately
        asyncio.create_task(_process_suggestion(bot, CHAT_ID))

        await asyncio.sleep(5)  # prevent double send
        NEXT_SCHEDULE = next_scheduled_time_epoch(target_weekday=6, hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE)


async def cache_update_scheduler():
    """Background loop that periodically refreshes score cache."""
    global NEXT_CACHE_UPDATE
    while True:
        curr_epoch = int(datetime.now().timestamp())
        wait_seconds = NEXT_CACHE_UPDATE - curr_epoch
        LOGGER.info(
            f"cache scheduler sleeping for {wait_seconds}..")
        await asyncio.sleep(wait_seconds)

        # NOTE: Existing behavior intentionally preserved (recursive call).
        await cache_update_scheduler()

        await asyncio.sleep(5)  # prevent double send
        NEXT_CACHE_UPDATE = next_scheduled_time_epoch(target_weekday=5, hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE)


async def main():
    """Initialize bot, register handlers, and start polling loop."""
    try:
        if not BOT_TOKEN:
            raise RuntimeError("BOT_TOKEN not found in environment or config.py")

        # build app
        app = ApplicationBuilder().token(BOT_TOKEN).build()

        try:
            await app.bot.set_my_commands([
                BotCommand("start", "Start the bot"),
                BotCommand("suggest_now", "Get an immediate suggestion"),
                BotCommand("whoami", "Show your chat id"),
                BotCommand("next_schedule", "Show when is the next weekly run scheduled"),
                BotCommand("status", "Gives latest health report based on CPU and Mem utilization"),
                BotCommand("last_run", "Gives CPU and Mem utilization analysis for "
                                       "last heavy image analysis run")
            ])

        except Exception:
            LOGGER.warning("Failed to set bot commands; continuing anyway.")
            LOGGER.error(f"TRACEBACK: {traceback.format_exc()}")

        # add handlers
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(CommandHandler("whoami", whoami_command))
        app.add_handler(CommandHandler("next_schedule", next_schedule))
        app.add_handler(CommandHandler("suggest_now", suggest_now))
        app.add_handler(CommandHandler("status", status_command))
        app.add_handler(CommandHandler("last_run", last_run_utilization_command))
        app.add_handler(CallbackQueryHandler(callback_handler))
        # fallback message handler to confirm bot connectivity
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                       lambda u, c: u.message.reply_text("Try /suggest_now")))

        # run scheduler in background
        asyncio.create_task(suggestion_scheduler_task(app))

        asyncio.create_task(cache_update_scheduler())

        # run bot polling (blocking)
        LOGGER.info("Starting Telegram bot...")
        await app.run_polling()
    except Exception as err:
        LOGGER.error(f"ERR: {str(err)}")
        LOGGER.error(f"TRACEBACK: {str(traceback.format_exc())}")


if __name__ == "__main__":
    # Warm cache once at startup to reduce first-request latency.
    LOGGER.info("initializing cache")
    _cache_update()
    nest_asyncio.apply()  # patch to allow nested event loops (Jupyter/interactive)
    asyncio.run(main())
