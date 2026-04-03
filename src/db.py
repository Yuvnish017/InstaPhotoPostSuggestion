# db.py
from __future__ import annotations

"""SQLite data-access layer for photo status, scores and telemetry."""

from collections.abc import Iterable
import os
import sqlite3
from datetime import datetime

from config import DB_PATH
from logger import Logger

LOGGER = Logger(log_file_name="db.log")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def _connect(timeout: int = 5) -> sqlite3.Connection:
    """Create a SQLite connection with a configurable timeout."""
    return sqlite3.connect(DB_PATH, timeout=timeout)


def init_db():
    """Initialize required tables if they are not present."""
    conn = _connect()
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            filename TEXT PRIMARY KEY,
            aesthetic FLOAT,
            sharpness FLOAT,
            exposure FLOAT,
            composition FLOAT,
            color_harmony FLOAT,
            face FLOAT,
            dom FLOAT,
            avg_sat FLOAT,
            top_hue TEXT
        )
    """)
    LOGGER.info("DB Table initialized")
    conn.commit()
    conn.close()


def store_score_cache(filename, aesthetic, sharpness, exposure, composition, color_harmony, face,
                      dom, avg_sat, top_hue):
    """Insert or update a score cache record for an image."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO scores (filename, aesthetic, sharpness, exposure, composition, color_harmony, face, dom, avg_sat, top_hue)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (filename, aesthetic, sharpness, exposure, composition, color_harmony, face, dom, avg_sat, top_hue))
    LOGGER.info(f"Scores for {filename} stored in cache")
    conn.commit()
    conn.close()


def get_filenames_in_scores_db():
    """Return all filenames currently present in score cache table."""
    conn = _connect()
    cur = conn.cursor()
    query = "SELECT filename FROM scores"
    LOGGER.info(f"Executing: {query}")
    cur.execute(query)

    rows = cur.fetchall()
    if not rows:
        rows = []
    filenames = [row[0] for row in rows]
    conn.close()
    return filenames


def get_image_score_from_cache(filenames: Iterable[str]):
    """Fetch cached score rows for specific filenames keyed by filename."""
    filenames = list(filenames)
    if not filenames:
        return {}

    conn = _connect()
    cur = conn.cursor()

    # Create placeholders (?, ?, ?, ...)
    placeholders = ",".join(["?"] * len(filenames))

    query = f"""
            SELECT * FROM scores WHERE filename IN ({placeholders})
        """

    LOGGER.info(f"Executing: {query} with {len(filenames)} filenames")

    cur.execute(query, filenames)

    rows = cur.fetchall()
    columns = [desc[0] for desc in cur.description]

    result = {}
    for row in rows:
        row_dict = dict(zip(columns, row))
        filename = row_dict["filename"]
        result[filename] = row_dict

    conn.close()

    return result


def mark_suggested(filename, score, caption):
    """Mark a photo as suggested while preserving prior decision flags."""
    conn = _connect()
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
    """Mark a photo as approved."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("UPDATE photos SET approved=1 WHERE filename=?", (filename,))
    LOGGER.info(f"{filename} marked as approved and posted")
    conn.commit()
    conn.close()


def mark_skipped(filename):
    """Mark a photo as skipped."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("UPDATE photos SET skipped=1 WHERE filename=?", (filename,))
    LOGGER.info(f"{filename} marked as skipped")
    conn.commit()
    conn.close()


def mark_rejected(filename):
    """Mark a photo as rejected."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("UPDATE photos SET rejected=1 WHERE filename=?", (filename,))
    LOGGER.info(f"{filename} marked as rejected")
    conn.commit()
    conn.close()


def is_approved(filename):
    """Return True if the photo has been approved before."""
    conn = _connect()
    cur = conn.cursor()
    LOGGER.info(f"{filename}: Checking if previously approved and posted")
    cur.execute("SELECT approved FROM photos WHERE filename=?", (filename,))
    row = cur.fetchone()
    conn.close()
    return bool(row and row[0] == 1)


def is_skipped(filename):
    """Return True if the photo has been skipped before."""
    conn = _connect()
    cur = conn.cursor()
    LOGGER.info(f"{filename}: Checking if previously skipped")
    cur.execute("SELECT skipped FROM photos WHERE filename=?", (filename,))
    row = cur.fetchone()
    conn.close()
    return bool(row and row[0] == 1)


def get_all_skipped():
    """Return a set of all skipped filenames."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT filename FROM photos WHERE skipped=1")
    rows = cur.fetchall()
    skipped = {r[0] for r in rows}
    return skipped


def is_rejected(filename):
    """Return True if the photo has been rejected before."""
    conn = _connect()
    cur = conn.cursor()
    LOGGER.info(f"{filename}: Checking if previously skipped")
    cur.execute("SELECT rejected FROM photos WHERE filename=?", (filename,))
    row = cur.fetchone()
    conn.close()
    return bool(row and row[0] == 1)


def unprocessed_candidates(folder, max_candidates=50):
    """List image files not yet approved/rejected up to `max_candidates`."""
    files = []
    seen = set()
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT filename FROM photos WHERE approved=1")
    rows = cur.fetchall()
    approved = {r[0] for r in rows}
    cur.execute("SELECT filename FROM photos WHERE rejected=1")
    rows2 = cur.fetchall()
    rejected = {r[0] for r in rows2}
    conn.close()

    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith(IMAGE_EXTENSIONS):
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
    Persist one resource telemetry snapshot.

    Args:
        stats: Dict containing 'cpu', 'mem', 'temp', and optional 'is_busy'.
    """
    conn = None
    try:
        conn = _connect(timeout=10)  # 10s timeout for Pi SD card latency
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
    """Return the most recent telemetry row, or None if table is empty."""
    conn = _connect()
    cursor = conn.cursor()
    LOGGER.info("Executing: SELECT * FROM telemetry ORDER BY timestamp DESC LIMIT 1")
    cursor.execute("SELECT * FROM telemetry ORDER BY timestamp DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row


def get_analysis_stats():
    """Return aggregated telemetry stats for the latest busy analysis window.

    The window is computed as:
    - end at the latest row where `is_busy = 1`
    - start right after the most recent `is_busy = 0` before that end row
    """
    conn = _connect()
    cursor = conn.cursor()

    # Previous query depended on timestamp subqueries and often produced NULL window bounds.
    # Using monotonically increasing `id` is more stable for defining the latest busy run.
    query = """
        WITH last_busy AS (
            SELECT MAX(id) AS last_busy_id
            FROM telemetry
            WHERE is_busy = 1
        ),
        prev_idle AS (
            SELECT MAX(t.id) AS prev_idle_id
            FROM telemetry t
            CROSS JOIN last_busy lb
            WHERE t.is_busy = 0
              AND t.id < lb.last_busy_id
        )
        SELECT
            AVG(t.cpu_percent),
            MAX(t.temp_c),
            MAX(t.memory_mb)
        FROM telemetry t
        CROSS JOIN last_busy lb
        CROSS JOIN prev_idle pi
        WHERE t.is_busy = 1
          AND t.id <= lb.last_busy_id
          AND t.id > COALESCE(pi.prev_idle_id, 0)
    """
    LOGGER.info("Executing query to fetch latest busy-window utilization stats")
    cursor.execute(query)
    stats = cursor.fetchone()
    conn.close()

    # Normalize empty aggregate tuples like (None, None, None) to None.
    if not stats or all(value is None for value in stats):
        return None

    return stats
