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
        rejected INTEGER DEFAULT 0,
        caption TEXT,
        score REAL
    )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT (DATETIME('now', 'localtime')),
            cpu_percent REAL,
            memory_mb REAL,
            temp_c REAL,
            is_busy BOOLEAN
        )
    """)
    LOGGER.info("DB Table initialized")
    conn.commit()
    conn.close()


def mark_suggested(filename, score, caption):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO photos (filename, suggested_at, approved, skipped, rejected, caption, score)
    VALUES (?, ?, COALESCE((SELECT approved FROM photos WHERE filename=?), 0),
            COALESCE((SELECT skipped FROM photos WHERE filename=?), 0),
            COALESCE((SELECT rejected FROM photos WHERE filename=?), 0),
            ?, ?)
    """, (filename, datetime.utcnow().isoformat(), filename, filename, filename, caption, score))
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


def mark_rejected(filename):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE photos SET rejected=1 WHERE filename=?", (filename,))
    LOGGER.info(f"{filename} marked as rejected")
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


def is_rejected(filename):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    LOGGER.info(f"{filename}: Checking if previously skipped")
    cur.execute("SELECT rejected FROM photos WHERE filename=?", (filename,))
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
    cur.execute("SELECT filename FROM photos WHERE rejected=1")
    rows2 = cur.fetchall()
    rejected = {r[0] for r in rows2}
    conn.close()

    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        if f in approved or f in rejected:
            continue
        if f in seen:
            continue
        seen.add(f)
        files.append(f)
        if len(files) >= max_candidates:
            break
    LOGGER.info(f"Number of candidates found: {len(files)}")
    return files


def save_telemetry(stats):
    """
    Saves a snapshot of system resources.
    stats: dict containing 'cpu', 'mem', 'temp', and 'is_busy'
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)  # 10s timeout for Pi SD card latency
        cursor = conn.cursor()

        LOGGER.info("Executing: INSERT INTO telemetry (cpu_percent, memory_mb, temp_c, is_busy)")
        cursor.execute("""
            INSERT INTO telemetry (cpu_percent, memory_mb, temp_c, is_busy)
            VALUES (?, ?, ?, ?)
        """, (
            stats.get('cpu'),
            stats.get('mem'),
            stats.get('temp'),
            stats.get('is_busy', False)
        ))

        conn.commit()
    except sqlite3.Error as e:
        LOGGER.error(f"⚠️ Telemetry DB Error: {e}")
    finally:
        if conn:
            conn.close()


def get_latest_health_report():
    """
    Optional helper to let the user check Pi health via a Telegram command.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    LOGGER.info("Executing: SELECT * FROM telemetry ORDER BY timestamp DESC LIMIT 1")
    cursor.execute("SELECT * FROM telemetry ORDER BY timestamp DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row  # Returns the most recent resource snapshot


def get_analysis_stats():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Get stats only from the last time is_busy was True
    LOGGER.info("Executing: SELECT AVG(cpu_percent), MAX(temp_c), MAX(memory_mb) FROM telemetry "
                "WHERE timestamp > (SELECT MAX(timestamp) FROM telemetry WHERE is_busy = 0 "
                "AND id < (SELECT MAX(id) FROM telemetry WHERE is_busy = 1)) AND is_busy = 1")
    cursor.execute("""
        SELECT AVG(cpu_percent), MAX(temp_c), MAX(memory_mb) 
        FROM telemetry 
        WHERE timestamp > (SELECT MAX(timestamp) FROM telemetry WHERE is_busy = 0 AND id < (SELECT MAX(id) FROM telemetry WHERE is_busy = 1))
        AND is_busy = 1
    """)
    stats = cursor.fetchone()
    conn.close()
    return stats
