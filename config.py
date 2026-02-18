# config.py - loads secrets from .env
import os
from dotenv import load_dotenv

load_dotenv()  # loads .env file if present in cwd

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID")) if os.getenv("CHAT_ID") else None

PHOTOS_FOLDER = os.getenv("PHOTOS_FOLDER", "photos_to_post")
POSTED_FOLDER = os.getenv("POSTED_FOLDER", "posted_images")

SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "21"))
SCHEDULE_MINUTE = int(os.getenv("SCHEDULE_MINUTE", "0"))

MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "50"))
DB_PATH = os.getenv("DB_PATH", "insta_queue.db")
