"""Shared utility helpers used across bot runtime modules."""

from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path


def next_scheduled_time_epoch(target_weekday: int, hour: int, minute: int) -> int:
    """Return the next scheduled timestamp for a weekday/time pair.

    Args:
        target_weekday: Weekday index where Monday=0 ... Sunday=6.
        hour: Target hour in 24-hour format.
        minute: Target minute.
    """
    now = datetime.now()
    curr_weekday = now.weekday()

    # Days until target
    days_to_target = (target_weekday - curr_weekday) % 7

    target_time = dtime(hour, minute)

    # If today is target day but time has passed → move to next week
    if days_to_target == 0 and now.time() >= target_time:
        days_to_target = 7

    next_date = now.date() + timedelta(days=days_to_target)
    next_dt = datetime.combine(next_date, target_time)

    return int(next_dt.timestamp())


def read_image_bytes(path: str | Path) -> bytes:
    """Read an image file from disk as raw bytes."""
    with open(path, "rb") as file_obj:
        return file_obj.read()
