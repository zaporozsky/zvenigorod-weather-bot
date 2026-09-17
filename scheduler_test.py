from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import os

scheduler = os.getenv("SCHEDULER", "unknown")

print("Scheduler:", scheduler)
print("UTC:", datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
print("Moscow:", datetime.now(ZoneInfo("Europe/Moscow")).isoformat(timespec="milliseconds"))