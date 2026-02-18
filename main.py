# main.py
import os
import shutil
import traceback
from datetime import datetime
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from config import BOT_TOKEN, PHOTOS_FOLDER, POSTED_FOLDER
from notifier import choose_and_send
from db import mark_approved, mark_skipped, init_db
from utils import next_scheduled_time_epoch
from logger import Logger

# ensure folders and DB exist
os.makedirs(PHOTOS_FOLDER, exist_ok=True)
os.makedirs(POSTED_FOLDER, exist_ok=True)
init_db()

NEXT_SCHEDULE = next_scheduled_time_epoch()
LOGGER = Logger(log_file_name="main.log")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Insta-helper bot is running. You will receive 1 suggestion per week at configured time."
    )


async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(f"Your chat id is: {cid}")


async def next_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Next run is scheduled at {datetime.fromtimestamp(NEXT_SCHEDULE).strftime('%Y/%m/%d:%H:%M')}"
    )


async def _process_suggestion(bot, chat_id):
    try:
        sent = await choose_and_send(bot)

        if sent:
            await bot.send_message(chat_id=chat_id, text=f"📸 Suggestion sent: {sent}")
        else:
            await bot.send_message(chat_id=chat_id, text="No candidates available right now.")
    except Exception as err:
        LOGGER.error(f"Error in background suggestion: {err}")
        await bot.send_message(chat_id=chat_id, text="❌ An error occurred while processing suggestion.")


async def suggest_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 Processing suggestion...")

    # "Fire and forget" - this releases the chat lock immediately
    await asyncio.create_task(_process_suggestion(context.bot, update.effective_chat.id))


async def simple_echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # fallback to confirm bot receives messages
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
    else:
        await query.edit_message_text("Unknown action.")


async def daily_scheduler_task(app):
    """
    Runs in background; sends one suggestion per day at configured time.
    """
    global NEXT_SCHEDULE
    bot = app.bot
    while True:
        curr_epoch = int(datetime.now().timestamp())
        wait_seconds = NEXT_SCHEDULE - curr_epoch
        LOGGER.info(f"Scheduler sleeping for {int(wait_seconds)} seconds until next run at {datetime.fromtimestamp(NEXT_SCHEDULE).strftime('%Y/%m/%d:%H:%M')}")
        await asyncio.sleep(wait_seconds)
        try:
            sent = await choose_and_send(bot)
            if sent:
                LOGGER.info(f"Daily suggestion sent: {sent}")
            else:
                LOGGER.warning("No candidate to send at this time.")
        except Exception as e:
            LOGGER.error(f"Error in daily scheduled send: {e}")
            LOGGER.error(traceback.format_exc())
        await asyncio.sleep(5)  # prevent double send
        NEXT_SCHEDULE = next_scheduled_time_epoch()


async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    """Runs once per day at configured hour/minute."""
    bot = context.bot
    sent = await choose_and_send(bot)
    if sent:
        LOGGER.info(f"Daily suggestion sent: {sent}")
    else:
        LOGGER.warning("Daily suggestion: no candidates available.")


async def init_jobqueue(app):
    if app.job_queue is None:
        from telegram.ext import JobQueue
        jq = JobQueue()
        jq.set_application(app)
        jq.start()
        app.job_queue = jq
        LOGGER.info("JobQueue initialized manually.")


async def main():
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
                BotCommand("next_schedule", "Show when is the next weekly run scheduled")
            ])

        except Exception:
            LOGGER.warning("Failed to set bot commands; continuing anyway.")
            LOGGER.error(f"TRACEBACK: {traceback.format_exc()}")

        # add handlers
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(CommandHandler("whoami", whoami_command))
        app.add_handler(CommandHandler("next_schedule", next_schedule))
        app.add_handler(CommandHandler("suggest_now", suggest_now))
        app.add_handler(CallbackQueryHandler(callback_handler))
        # fallback message handler to confirm bot connectivity
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                       lambda u, c: u.message.reply_text("Try /suggest_now")))

        # run scheduler in background
        asyncio.create_task(daily_scheduler_task(app))
        # app.job_queue.run_daily(
        #     daily_job,
        #     time=dtime(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE, tzinfo=timezone(timedelta(hours=9))),
        #     name="daily_suggestion",
        #     chat_id=CHAT_ID
        # )

        # run bot polling (blocking)
        LOGGER.info("Starting Telegram bot...")
        await app.run_polling()
    except Exception as err:
        LOGGER.error(f"ERR: {str(err)}")
        LOGGER.error(f"TRACEBACK: {str(traceback.format_exc())}")


if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()  # patch to allow nested event loops (Jupyter/interactive)

    import asyncio

    asyncio.run(main())
