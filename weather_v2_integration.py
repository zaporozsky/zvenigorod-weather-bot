"""Explicit offline preparation boundary; no import-time I/O or transport."""
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import os
import re
import stat

from weather_logic import Forecast, analyze_hours
from weather_rendering import Ancillary, RenderedForecast, RenderingBlocked, render_forecast
from weather_v2_photo import PhotoDecision, photo_scenario

# Both are code gates, not environment overrides.
V2_LIVE_ENABLED = True
V2_CHAIN_VERIFIED = True


class PreparationBlocked(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PreparedForecast:
    forecast: Forecast
    rendered: RenderedForecast | None
    photo: PhotoDecision
    blockers: tuple[str, ...]
    diagnostics: tuple[str, ...]


def live_v2_ready():
    from weather_logic import OPEN_RULES
    return V2_LIVE_ENABLED and V2_CHAIN_VERIFIED and not OPEN_RULES


def _clock(value):
    if type(value) is not str:
        return None
    for fmt in ('%I:%M %p', '%H:%M'):
        try:
            return datetime.strptime(value, fmt).strftime('%H:%M')
        except ValueError:
            pass
    return None


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def prepare_v2(payload, publish_date):
    try:
        target = date.fromisoformat(publish_date) if type(publish_date) is str else publish_date
        if type(target) is not date:
            raise ValueError
    except (ValueError, TypeError):
        raise PreparationBlocked('INVALID_PUBLISH_DATE') from None
    days = _mapping(_mapping(payload).get('forecast')).get('forecastday')
    if type(days) is not list:
        raise PreparationBlocked('MISSING_FORECAST_DAYS')
    dates = (target.isoformat(), (target + timedelta(days=1)).isoformat())
    selected = {key: [day for day in days if isinstance(day, Mapping) and day.get('date') == key]
                for key in dates}
    if len(selected[dates[0]]) != 1:
        raise PreparationBlocked('TARGET_DAY_MISSING_OR_DUPLICATED')
    if len(selected[dates[1]]) > 1:
        raise PreparationBlocked('NEXT_DAY_DUPLICATED')
    records, diagnostics = [], []
    for key in dates:
        if not selected[key]:
            diagnostics.append('SECOND_DAY_MISSING')
            continue
        hours = selected[key][0].get('hour')
        if type(hours) is not list:
            diagnostics.append('DAY_HOURS_MISSING')
            continue
        # A timestamp must belong to its enclosing provider date. Never use
        # mismatched nested days as a substitute for the following night.
        for hour in hours:
            if not isinstance(hour, Mapping):
                diagnostics.append('INVALID_HOUR_RECORD')
                continue
            time = hour.get('time')
            if type(time) is str and time.startswith(key + ' '):
                records.append(hour)
            else:
                diagnostics.append('HOUR_DAY_MISMATCH')
    if not any(type(hour.get('time')) is str and hour['time'].startswith(dates[0] + ' ')
               for hour in records):
        raise PreparationBlocked('TARGET_DAY_HOURS_MISSING')
    forecast = analyze_hours(records, target.isoformat())
    if not any(item.condition.code is not None or item.hour.temp_c is not None
               for period in forecast.periods[:3] for item in period.hours):
        raise PreparationBlocked('TARGET_DAY_HOURS_UNUSABLE')
    day = selected[dates[0]][0]
    ancillary = Ancillary(
        humidity=_mapping(day.get('day')).get('avghumidity'),
        # Current pressure is not silently presented as a forecast-day value.
        sunrise=_clock(_mapping(day.get('astro')).get('sunrise')),
        sunset=_clock(_mapping(day.get('astro')).get('sunset')),
    )
    try:
        rendered = render_forecast(forecast, ancillary)
        blockers = ()
    except RenderingBlocked as exc:
        rendered = None
        blockers = tuple(sorted({exc.code, *exc.blockers}))
    return PreparedForecast(forecast, rendered, photo_scenario(forecast), blockers,
                            tuple(sorted(set(diagnostics))))


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def diagnostic_snapshot(prepared):
    """Only validated Core fields/decisions, never the provider response."""
    return {
        'schema_version': 1, 'contract_version': '1.1', 'live_gate_open': live_v2_ready(),
        'forecast': _json_value(prepared.forecast),
        'adapter_diagnostics': list(prepared.diagnostics),
        'blockers': list(prepared.blockers),
        'photo': _json_value(prepared.photo),
        'rendered': _json_value(prepared.rendered),
    }


RETENTION = timedelta(days=7)
_SNAPSHOT_NAME = re.compile(r'weather-v2-[a-z0-9_]+\.json')


def _utc(now):
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError('AWARE_UTC_TIMESTAMP_REQUIRED')
    return now.astimezone(timezone.utc)


def purge_snapshots(directory, *, now=None):
    """Delete only this store's expired regular files, never follow symlinks.

    Called on every access. Persistent storage additionally needs a deletion
    service while this process is idle; live operation uses ephemeral storage.
    """
    now = _utc(now if now is not None else datetime.now(timezone.utc))
    root = Path(directory)
    removed = 0
    if not root.exists():
        return 0
    for file in root.iterdir():
        if not _SNAPSHOT_NAME.fullmatch(file.name) or file.is_symlink():
            continue
        info = file.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            continue
        try:
            # Refuse symbolic-link replacement between inspection and reading.
            fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'r', encoding='utf-8') as stream:
                metadata = json.load(stream)
            created = _utc(datetime.fromisoformat(metadata['created_at']))
            expires = _utc(datetime.fromisoformat(metadata['expires_at']))
            expired = now >= min(expires, created + RETENTION) or created > now
        except (ValueError, KeyError, TypeError, UnicodeError, OSError):
            expired = True  # Unreadable/malformed owned snapshots fail closed.
        if expired:
            file.unlink(missing_ok=True)
            removed += 1
    return removed


def save_snapshot(prepared, directory, *, now=None):
    """Safe projection, 0600 files, <=7-day expiry, explicit local I/O only."""
    now = _utc(now if now is not None else datetime.now(timezone.utc))
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_mode & 0o077:
        raise ValueError('PRIVATE_DIAGNOSTICS_DIRECTORY_REQUIRED')
    purge_snapshots(root, now=now)
    content = json.dumps(dict(diagnostic_snapshot(prepared),
                             created_at=now.isoformat(),
                             expires_at=(now + RETENTION).isoformat()),
                         ensure_ascii=False, allow_nan=False, indent=2) + '\n'
    result = pending = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=root,
                                         prefix='weather-v2-', suffix='.pending',
                                         delete=False) as stream:
            pending = Path(stream.name)
            result = pending.with_suffix('.json')
            stream.write(content)
        os.replace(pending, result)
    except BaseException:
        if pending is not None:
            pending.unlink(missing_ok=True)
        if result is not None:
            result.unlink(missing_ok=True)
        raise
    return result
