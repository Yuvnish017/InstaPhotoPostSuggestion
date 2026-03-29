import datetime
from datetime import datetime, timedelta
from datetime import time as dtime


def next_scheduled_time_epoch(target_weekday: int, hour: int, minute: int):
    """
    target_weekday: 0=Monday ... 6=Sunday
    hour, minute: scheduled time
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


def read_image_bytes(path):
    with open(path, "rb") as f:
        return f.read()
