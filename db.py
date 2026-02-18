# db.py
import sqlite3
from config import DB_PATH
import os
import datetime
from datetime import datetime
from logger import Logger

LOGGER = Logger(log_file_name="db.logs")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS photos (
        filename TEXT PRIMARY KEY,
        suggested_at TEXT,
        approved INTEGER DEFAULT 0,
        skipped INTEGER DEFAULT 0,
        caption TEXT,
        score REAL
    )
    """)
    LOGGER.info("DB Table initialized")
    conn.commit()
    conn.close()


def mark_suggested(filename, score, caption):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO photos (filename, suggested_at, approved, skipped, caption, score)
    VALUES (?, ?, COALESCE((SELECT approved FROM photos WHERE filename=?), 0),
            COALESCE((SELECT skipped FROM photos WHERE filename=?), 0),
            ?, ?)
    """, (filename, datetime.utcnow().isoformat(), filename, filename, caption, score))
    LOGGER.info(f"{filename}, {score} marked as suggested")
    conn.commit()
    conn.close()


def mark_approved(filename):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE photos SET approved=1 WHERE filename=?", (filename,))
    LOGGER.info(f"{filename} marked as approved and posted")
    conn.commit()
    conn.close()


def mark_skipped(filename):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE photos SET skipped=1 WHERE filename=?", (filename,))
    LOGGER.info(f"{filename} marked as skipped")
    conn.commit()
    conn.close()


def is_approved(filename):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    LOGGER.info(f"{filename}: Checking if previously approved and posted")
    cur.execute("SELECT approved FROM photos WHERE filename=?", (filename,))
    row = cur.fetchone()
    conn.close()
    return bool(row and row[0] == 1)


def is_skipped(filename):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    LOGGER.info(f"{filename}: Checking if previously skipped")
    cur.execute("SELECT skipped FROM photos WHERE filename=?", (filename,))
    row = cur.fetchone()
    conn.close()
    return bool(row and row[0] == 1)


def unprocessed_candidates(folder, max_candidates=50):
    # return list of filenames not approved and not skipped
    files = []
    seen = set()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT filename FROM photos WHERE approved=1")
    rows = cur.fetchall()
    approved = {r[0] for r in rows}
    cur.execute("SELECT filename FROM photos WHERE skipped=1")
    rows2 = cur.fetchall()
    skipped = {r[0] for r in rows2}
    conn.close()

    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        if f in approved or f in skipped:
            continue
        if f in seen:
            continue
        seen.add(f)
        files.append(f)
        if len(files) >= max_candidates:
            break
    LOGGER.info(f"Number of candidates found: {len(files)}")
    return files
