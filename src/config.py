"""Centralized runtime configuration loaded from environment variables.

This module resolves data/log/model paths differently for local and Docker
deployments so the rest of the codebase can use a single config interface.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base project directory (parent of `src`).
BASE_DIR = Path(__file__).resolve().parent.parent

IS_DOCKER = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"

if not IS_DOCKER:
    # Local development: load values from `.env` file.
    env_path = BASE_DIR / ".env"
    load_dotenv(dotenv_path=env_path)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID")) if os.getenv("CHAT_ID") else None

SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "8"))
SCHEDULE_MINUTE = int(os.getenv("SCHEDULE_MINUTE", "0"))

MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "50"))
MAX_PROCESSES = int(os.getenv("MAX_PROCESSES", "10"))
PROCESS_TIMEOUT = int(os.getenv("PROCESS_TIMEOUT", "300"))
SKIP_RETRY = int(os.getenv("SKIP_RETRY", "3"))

if IS_DOCKER:
    # Container paths are mounted by docker-compose/runtime.
    PHOTOS_FOLDER = os.getenv("PHOTOS_FOLDER", "/app/data/photos_to_post")
    POSTED_FOLDER = os.getenv("POSTED_FOLDER", "/app/data/posted_images")
    DB_PATH = os.getenv("DB_PATH", "/app/data/insta_queue.db")
    LOGS_PATH = os.getenv("LOGS_PATH", "/app/src/logs")
    MODELS_PATH = os.getenv("MODELS_PATH")
else:
    # Local paths are resolved relative to project root.
    PHOTOS_FOLDER = os.path.join(str(BASE_DIR), "data", os.getenv("PHOTOS_FOLDER", "photos_to_post"))
    POSTED_FOLDER = os.path.join(str(BASE_DIR), "data", os.getenv("POSTED_FOLDER", "posted_images"))
    DB_PATH = os.path.join(str(BASE_DIR), "data", os.getenv("DB_PATH", "insta_queue.db"))
    LOGS_PATH = os.path.join(str(BASE_DIR), "src", os.getenv("LOGS_PATH", "logs"))
    MODELS_PATH = os.path.join(str(BASE_DIR), "src", os.getenv("MODELS_PATH", "models"))
