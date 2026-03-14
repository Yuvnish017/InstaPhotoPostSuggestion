# main.py
import os
import shutil
import traceback
from datetime import datetime
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from config import BOT_TOKEN, PHOTOS_FOLDER, POSTED_FOLDER
from notifier import choose_and_send
from db import mark_approved, mark_skipped, init_db, get_analysis_stats, get_latest_health_report, mark_rejected
from utils import next_scheduled_time_epoch
from logger import Logger
from resource_monitor import ResourceMonitor

# ensure folders and DB exist
os.makedirs(PHOTOS_FOLDER, exist_ok=True)
os.makedirs(POSTED_FOLDER, exist_ok=True)
init_db()

monitor = ResourceMonitor()
monitor.start()

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


async def status_command(update, context):
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


async def last_run_utilization_command(update, context):
    row = get_analysis_stats()

    if not row:
        await update.message.reply_text("❌ No telemetry data found yet.")
        return

    cpu, temp, mem = row

    status_emoji = "🔥" if temp > 75 else "🟢"

    message = (
        f"🖥️ **Pi 4 Health Report During Last Image Analysis**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{status_emoji} Temp: `{temp:.1f}°C`\n"
        f"🧠 App RAM: `{mem:.1f} MB`\n"
        f"⚡ CPU Load: `{cpu:.1f}%`"
    )

    await update.message.reply_text(message, parse_mode='Markdown')


async def _process_suggestion(bot, chat_id):
    try:
        monitor.set_high_priority(True)  # Start high-res logging
        sent = await choose_and_send(bot)

        if sent:
            await bot.send_message(chat_id=chat_id, text=f"📸 Suggestion sent: {sent}")
        else:
            await bot.send_message(chat_id=chat_id, text="No candidates available right now.")
    except Exception as err:
        LOGGER.error(f"Error in background suggestion: {err}")
        await bot.send_message(chat_id=chat_id, text="❌ An error occurred while processing suggestion.")
    finally:
        monitor.set_high_priority(False)  # Go back to sleep


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
    elif action == "reject":
        mark_rejected(fname)
        await  query.edit_message_caption(f"❌ Rejected: {fname}")
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
            monitor.set_high_priority(True)  # Go back to sleep
            sent = await choose_and_send(bot)
            if sent:
                LOGGER.info(f"Daily suggestion sent: {sent}")
            else:
                LOGGER.warning("No candidate to send at this time.")
        except Exception as e:
            LOGGER.error(f"Error in daily scheduled send: {e}")
            LOGGER.error(traceback.format_exc())
        finally:
            monitor.set_high_priority(False)  # Go back to sleep
        await asyncio.sleep(5)  # prevent double send
        NEXT_SCHEDULE = next_scheduled_time_epoch()


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
        asyncio.create_task(daily_scheduler_task(app))

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
