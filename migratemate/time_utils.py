"""MigrateMate posted-time helpers."""
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings

TZ = ZoneInfo("America/New_York")
SECONDS_24H = 86400


def max_age_seconds():
    return 86400


def slugify_keyword(keyword):
    return re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")


def is_within_24h_timestamp(ts):
    if not ts:
        return False
    try:
        posted = int(ts)
    except (TypeError, ValueError):
        return False
    return int(time.time()) - posted <= max_age_seconds()


def format_posted_time(ts):
    if not ts:
        return "Recently"
    diff = max(0, int(time.time()) - int(ts))
    if diff > max_age_seconds():
        return None

    post_dt = datetime.fromtimestamp(int(ts), tz=TZ)
    now_dt = datetime.fromtimestamp(int(time.time()), tz=TZ)
    time_str = post_dt.strftime("%I:%M %p").lstrip("0")

    if diff < 60:
        return f"Just now · Today {time_str}"
    if diff < 3600:
        m = diff // 60
        rel = f"{m} min ago"
        if post_dt.date() == now_dt.date():
            return f"{rel} · Today {time_str}"
        if post_dt.date() == (now_dt.date() - timedelta(days=1)):
            return f"{rel} · Yesterday {time_str}"
        return rel

    h = diff // 3600
    rel = f"{h} hour{'s' if h != 1 else ''} ago"
    if post_dt.date() == now_dt.date():
        return f"{rel} · Today {time_str}"
    if post_dt.date() == (now_dt.date() - timedelta(days=1)):
        return f"Yesterday · {time_str}"
    return f"{rel} · {post_dt.strftime('%b %d')} {time_str}"
