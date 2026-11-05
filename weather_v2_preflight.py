"""One explicit WeatherAPI diagnostic request; never imports delivery code.

No retries, redirect following, raw-body persistence or secret-bearing logs.
The caller must explicitly authorize the one request and supply the key via env.
"""
from collections import Counter
from datetime import date, datetime, timedelta
import http.client
import json
import os
import ssl
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from weather_logic import NUMERIC_FIELDS, TIMEZONE, normalize_hours
from weather_rendering import utf16_length
from weather_v2_integration import PreparationBlocked, prepare_v2


HOST = 'api.weatherapi.com'
LOCATION = '55.7352,36.8553'
MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # transport bound, not an editorial threshold


REQUIRED_FIELDS = (
    'condition_code', 'temp_c', 'feelslike_c', 'chance_of_rain', 'chance_of_snow',
    'precip_mm', 'snow_cm', 'wind_kph', 'gust_kph', 'is_day',
)


def _date(value):
    if type(value) is not str:
        return None
    try:
        parsed = date.fromisoformat(value)
        return parsed if parsed.isoformat() == value else None
    except ValueError:
        return None


def _day_report(day, calendar_date):
    raw = day.get('hour')
    hours = raw if type(raw) is list else []
    normalized = normalize_hours(hours)
    fields = {
        name: dict(Counter(next((field.state for field in source.fields if field.name == name), 'missing')
                           for source in normalized.sources))
        for name in (*NUMERIC_FIELDS, 'is_day', 'condition_code')
    }
    in_day = [source.time for source in normalized.sources if source.time is not None
              and source.time.date() == calendar_date and source.time.minute == 0]
    counts = Counter(in_day)
    duplicates = sorted(time.strftime('%H:%M') for time, count in counts.items() if count > 1)
    usable = {hour.time.strftime('%H:%M') for hour in normalized.hours if hour.time.date() == calendar_date}
    expected = {f'{hour:02}:00' for hour in range(24)}
    timestamp_diagnostics = [item for item in normalized.diagnostics
                            if item.code in ('INVALID_HOUR', 'OFF_HOUR_TIMESTAMP', 'TIME_CONFLICT', 'INVALID_EPOCH')
                            or (item.field in ('time', 'time_epoch') and item.code in ('INVALID_FIELD', 'NULL_FIELD'))]
    invalid = len(hours) - len(in_day)
    epoch_ok = not timestamp_diagnostics
    complete = (len(hours) == 24 and len(in_day) == 24 and usable == expected
                and not duplicates and epoch_ok)
    gaps = sorted(name for name in REQUIRED_FIELDS if fields[name].get('valid', 0) != len(hours) or not hours)
    return {
        'date': calendar_date.isoformat(), 'hours_array_present': type(raw) is list,
        'hour_records': len(hours), 'valid_hour_timestamps': len(in_day),
        'usable_hours': len(usable), 'complete_24_hours': complete,
        'invalid_or_wrong_day_timestamps': invalid, 'epoch_timestamps_consistent': epoch_ok,
        'duplicate_hours': duplicates, 'missing_hours': sorted(expected - usable),
        'field_states': fields, 'required_field_gaps': gaps,
        'diagnostic_codes': sorted({item.code for item in normalized.diagnostics}),
    }


def _compatibility(payload, target):
    try:
        prepared = prepare_v2(payload, target.isoformat())
        if prepared.blockers or prepared.rendered is None:
            return {'status': 'blocked', 'categories': list(prepared.blockers)}
        return {
            'status': 'compatible', 'categories': list(prepared.diagnostics),
            'weather_diagnostic_codes': sorted({item.code for item in prepared.forecast.diagnostics}),
            'periods': [{'name': period.name, 'hours': period.time_count,
                         'known_conditions': period.condition_count,
                         'temperatures': period.temperature.count}
                        for period in prepared.forecast.periods],
            'rendered_utf16_units': utf16_length(prepared.rendered.text),
            'photo_scenario': prepared.photo.scenario, 'photo_reason': prepared.photo.reason,
        }
    except PreparationBlocked as exc:
        return {'status': 'blocked', 'categories': [exc.code]}
    except Exception:
        return {'status': 'error', 'categories': ['V2_COMPATIBILITY_ERROR']}


def inspect_payload(payload, *, reference_date=None):
    """Only allowlisted structural/decision metadata; no raw weather or text.

    With reference_date, D is fixed before the HTTP request in Moscow. Standalone
    offline inspection may explicitly use the first returned date as D.
    """
    if not isinstance(payload, dict):
        return {'category': 'INVALID_RESPONSE_SHAPE'}
    forecast = payload.get('forecast')
    days = forecast.get('forecastday') if isinstance(forecast, dict) else None
    if not isinstance(days, list):
        error = payload.get('error')
        code = error.get('code') if isinstance(error, dict) else None
        return {'category': 'API_ERROR_OR_MISSING_FORECAST',
                'provider_error_code': code if type(code) is int else None}
    valid = [(day, _date(day.get('date'))) for day in days if isinstance(day, dict)]
    valid = [(day, value) for day, value in valid if value is not None]
    result = [_day_report(day, value) for day, value in valid]
    dates = sorted(value for _, value in valid)
    consecutive = len(dates) == 2 and dates[1] - dates[0] == timedelta(days=1)
    target = _date(reference_date) if reference_date is not None else dates[0] if dates else None
    reference_ok = target is not None and bool(dates) and target == dates[0]
    night = None
    if target is not None:
        # Filter dates, not array positions, and never use D 00–05 for D+1.
        tomorrow = (target + timedelta(days=1)).isoformat()
        matches = [item for item in result if item['date'] == tomorrow]
        wanted = {f'{hour:02}:00' for hour in range(6)}
        missing = sorted(wanted & set(matches[0]['missing_hours'])) if len(matches) == 1 else sorted(wanted)
        duplicates = sorted(wanted & set(matches[0]['duplicate_hours'])) if len(matches) == 1 else []
        night = {'date': tomorrow, 'expected_hours': 6, 'missing_hours': missing,
                 'duplicate_hours': duplicates,
                 'available': len(matches) == 1 and not missing and not duplicates}
    structural = (len(days) == len(valid) == 2 and consecutive and reference_ok
                  and all(item['complete_24_hours'] for item in result)
                  and night is not None and night['available'])
    fields_complete = len(result) == 2 and all(not item['required_field_gaps'] for item in result)
    compatibility = _compatibility(payload, target) if target is not None else {
        'status': 'blocked', 'categories': ['REFERENCE_DATE_UNAVAILABLE']}
    category = ('FORECAST_STRUCTURE_INVALID' if not structural else
                'V2_INCOMPATIBLE' if compatibility['status'] != 'compatible' else
                'REQUIRED_FIELD_GAPS' if not fields_complete else 'OK')
    return {
        'category': category, 'forecastday_records': len(days),
        'returned_days': len(result), 'invalid_day_records': len(days) - len(valid),
        'two_consecutive_days': consecutive, 'reference_date_matches': reference_ok,
        'reference_date': target.isoformat() if target is not None else None,
        'complete_hourly_days': sum(item['complete_24_hours'] for item in result),
        'required_fields_complete': fields_complete, 'structure_valid': structural,
        'next_night': night, 'days': result, 'v2': compatibility,
    }


def diagnose_weatherapi(api_key, *, connection_factory=None):
    """One forecast.json request with fixed city and days=2, no redirects."""
    if type(api_key) is not str or not api_key.strip():
        return {'category': 'WEATHER_API_KEY_UNAVAILABLE', 'request_attempts': 0}
    api_key = api_key.strip()
    connection = None
    report = {'request_attempts': 1}
    request_date = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    try:
        factory = connection_factory or http.client.HTTPSConnection
        connection = factory(HOST, timeout=20, context=ssl.create_default_context())
        path = '/v1/forecast.json?' + urlencode({'key': api_key, 'q': LOCATION,
                                                'days': 2, 'lang': 'ru'})
        connection.request('GET', path)
        response = connection.getresponse()
        report['http_status'] = response.status
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            report['category'] = 'RESPONSE_TOO_LARGE'
        elif response.status != 200:
            report['category'] = 'HTTP_ERROR'  # never echo request URL/error body
            try:
                error = json.loads(body).get('error')
                code = error.get('code') if isinstance(error, dict) else None
                if type(code) is int:
                    report['provider_error_code'] = code
            except (ValueError, AttributeError, UnicodeError):
                pass
        else:
            report.update(inspect_payload(json.loads(body), reference_date=request_date))
    except (TimeoutError, OSError):
        report['category'] = 'NETWORK_OR_TIMEOUT_ERROR'
    except (ValueError, UnicodeError):
        report['category'] = 'INVALID_JSON_RESPONSE'
    except Exception:
        report['category'] = 'DIAGNOSTIC_ERROR'
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
    return report


def main():
    report = diagnose_weatherapi(os.getenv('WEATHER_API_KEY'))
    # Only this fixed allowlisted report reaches stdout, never exceptions.
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report['category'] == 'OK' else 2


if __name__ == '__main__':
    raise SystemExit(main())
