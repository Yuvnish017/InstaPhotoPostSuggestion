import datetime
from datetime import datetime, timedelta
from datetime import time as dtime
from config import SCHEDULE_MINUTE, SCHEDULE_HOUR


def next_scheduled_time_epoch():
    now = datetime.now()
    curr_weekday = now.date().weekday()
    days_to_target = (6 - curr_weekday) % 7
    target_time = dtime(SCHEDULE_HOUR, SCHEDULE_MINUTE)
    if days_to_target == 0 and now.time() >= target_time:
        days_to_target = 7
    next_schedule = now.date() + timedelta(days=days_to_target)
    next_schedule = int(datetime.combine(next_schedule, target_time).timestamp())
    return next_schedule
