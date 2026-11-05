"""Offline production preflight: complete days, fields, time grid and isolation."""
import ast
from copy import deepcopy
from datetime import date, datetime, timedelta
import io
import json
from pathlib import Path
import random
import re
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from test_weather_logic import raw_hour
import weather_v2_preflight as preflight

ROOT = Path(__file__).parents[1]
D = '2026-11-05'


def full_payload():
    start = date.fromisoformat(D)
    days = []
    for index in range(2):
        day = (start + timedelta(days=index)).isoformat()
        rows = [raw_hour(f'{day} {hour:02}:00', is_day=int(7 <= hour <= 17)) for hour in range(24)]
        days.append({'date': day, 'hour': rows})
    return {'forecast': {'forecastday': days}}


def inspect(payload):
    return preflight.inspect_payload(payload, reference_date=D)


class PreflightStructureTests(unittest.TestCase):
    def test_two_complete_days_and_v2_use_the_same_response(self):
        payload = full_payload()
        original = deepcopy(payload)
        result = inspect(payload)
        self.assertEqual(result['category'], 'OK')
        self.assertTrue(result['structure_valid'])
        self.assertTrue(result['required_fields_complete'])
        self.assertEqual(result['complete_hourly_days'], 2)
        self.assertEqual([day['hour_records'] for day in result['days']], [24, 24])
        self.assertTrue(result['next_night']['available'])
        self.assertEqual(result['next_night']['date'], '2026-11-06')
        self.assertEqual(result['v2']['status'], 'compatible')
        self.assertEqual([period['hours'] for period in result['v2']['periods']], [6]*4)
        self.assertLessEqual(result['v2']['rendered_utf16_units'], 1024)
        self.assertEqual(payload, original)

    def test_missing_fields_are_reported_without_replacement(self):
        for field in preflight.REQUIRED_FIELDS:
            payload = full_payload()
            row = payload['forecast']['forecastday'][0]['hour'][8]
            if field == 'condition_code':
                del row['condition']['code']
            else:
                del row[field]
            with self.subTest(field=field):
                result = inspect(payload)
                self.assertEqual(result['category'], 'REQUIRED_FIELD_GAPS')
                self.assertEqual(result['days'][0]['field_states'][field], {'valid': 23, 'missing': 1})
                self.assertIn(field, result['days'][0]['required_field_gaps'])
                self.assertEqual(result['v2']['status'], 'compatible')
                self.assertNotIn(field, row if field != 'condition_code' else row['condition'])

    def test_zero_is_valid_while_null_invalid_and_missing_remain_distinct(self):
        payload = full_payload()
        rows = payload['forecast']['forecastday'][0]['hour']
        rows[0]['snow_cm'] = None
        rows[1]['snow_cm'] = 'SECRET_CANARY'
        del rows[2]['snow_cm']
        result = inspect(payload)
        self.assertEqual(result['days'][0]['field_states']['snow_cm'],
                         {'null': 1, 'invalid': 1, 'missing': 1, 'valid': 21})
        self.assertNotIn('SECRET_CANARY', json.dumps(result))

    def test_duplicate_cannot_replace_a_missing_hour(self):
        payload = full_payload()
        rows = payload['forecast']['forecastday'][1]['hour']
        rows[0] = deepcopy(rows[1])
        result = inspect(payload)
        self.assertEqual(result['category'], 'FORECAST_STRUCTURE_INVALID')
        self.assertEqual(result['days'][1]['duplicate_hours'], ['01:00'])
        self.assertEqual(result['days'][1]['missing_hours'], ['00:00'])
        self.assertFalse(result['next_night']['available'])
        self.assertEqual(result['complete_hourly_days'], 1)

    def test_identical_and_conflicting_duplicates_both_fail(self):
        for conflict in (False, True):
            payload = full_payload()
            rows = payload['forecast']['forecastday'][0]['hour']
            duplicate = deepcopy(rows[6])
            if conflict:
                duplicate['temp_c'] = 99
            rows.append(duplicate)
            with self.subTest(conflict=conflict):
                result = inspect(payload)
                self.assertFalse(result['structure_valid'])
                self.assertEqual(result['days'][0]['duplicate_hours'], ['06:00'])

    def test_missing_next_day_never_reuses_the_first_night(self):
        payload = full_payload()
        payload['forecast']['forecastday'].pop()
        result = inspect(payload)
        self.assertFalse(result['two_consecutive_days'])
        self.assertFalse(result['next_night']['available'])
        self.assertEqual(result['next_night']['missing_hours'], [f'{h:02}:00' for h in range(6)])

    def test_missing_last_hour_of_next_night_is_visible(self):
        payload = full_payload()
        del payload['forecast']['forecastday'][1]['hour'][5]
        result = inspect(payload)
        self.assertEqual(result['next_night']['missing_hours'], ['05:00'])
        self.assertFalse(result['next_night']['available'])

    def test_malformed_off_hour_wrong_date_and_epoch_conflict_are_rejected(self):
        for change in ({'time': 'SECRET_CANARY'}, {'time': D+' 06:30'},
                       {'time': '2026-11-07 06:00'}, {'time_epoch': 'SECRET_CANARY'},
                       {'time_epoch': int(datetime(2026, 11, 5, 7, tzinfo=ZoneInfo('Europe/Moscow')).timestamp())}):
            payload = full_payload()
            payload['forecast']['forecastday'][0]['hour'][6].update(change)
            with self.subTest(change=change):
                result = inspect(payload)
                self.assertFalse(result['structure_valid'])
                self.assertEqual(result['category'], 'FORECAST_STRUCTURE_INVALID')
                self.assertNotIn('SECRET_CANARY', json.dumps(result))

    def test_reordered_days_and_hours_do_not_change_decisions(self):
        payload = full_payload()
        expected = inspect(payload)
        payload['forecast']['forecastday'].reverse()
        for day in payload['forecast']['forecastday']:
            random.Random(4).shuffle(day['hour'])
        result = inspect(payload)
        self.assertEqual(result['category'], 'OK')
        self.assertEqual(result['v2'], expected['v2'])
        self.assertTrue(result['next_night']['available'])

    def test_invalid_repeated_extra_or_nonconsecutive_days_fail(self):
        for variant in ('invalid', 'duplicate', 'extra', 'gap'):
            payload = full_payload()
            days = payload['forecast']['forecastday']
            if variant == 'invalid': days[1]['date'] = 'SECRET_CANARY'
            if variant == 'duplicate': days[1] = deepcopy(days[0])
            if variant == 'extra': days.append(deepcopy(days[1]))
            if variant == 'gap': days[1]['date'] = '2026-11-07'
            with self.subTest(variant=variant):
                result = inspect(payload)
                self.assertFalse(result['structure_valid'])
                self.assertNotIn('SECRET_CANARY', json.dumps(result))

    def test_reference_date_is_fixed_in_moscow_not_taken_from_another_forecast(self):
        result = preflight.inspect_payload(full_payload(), reference_date='2026-11-06')
        self.assertFalse(result['reference_date_matches'])
        self.assertFalse(result['structure_valid'])

    def test_v2_incompatibility_is_reported_before_any_delivery(self):
        payload = full_payload()
        for row in payload['forecast']['forecastday'][0]['hour']:
            row['condition']['code'] = None
            row['temp_c'] = None
        result = inspect(payload)
        self.assertEqual(result['category'], 'V2_INCOMPATIBLE')
        self.assertEqual(result['v2']['status'], 'blocked')
        self.assertIn('TARGET_DAY_HOURS_UNUSABLE', result['v2']['categories'])

    def test_no_provider_text_location_or_forecast_values_are_logged(self):
        payload = full_payload()
        payload['location'] = {'name': 'SECRET_CANARY', 'lat': 'SECRET_CANARY'}
        payload['forecast']['forecastday'][0]['hour'][8]['condition']['text'] = 'SECRET_CANARY'
        payload['forecast']['forecastday'][0]['hour'][8]['Authorization'] = 'SECRET_CANARY'
        result = inspect(payload)
        text = json.dumps(result)
        self.assertNotIn('SECRET_CANARY', text)
        self.assertNotIn('period_lines', text)
        self.assertNotIn('forecastday', result)  # structural counts only


class PreflightWorkflowTests(unittest.TestCase):
    def test_workflow_is_manual_secret_scoped_and_single_command(self):
        source = (ROOT/'.github/workflows/weatherapi-preflight.yml').read_text()
        on = re.search(r'^on:\n(.*?)(?=^\S)', source, re.M|re.S).group(1)
        self.assertEqual(on.strip(), 'workflow_dispatch:')
        self.assertEqual(re.findall(r'secrets\.([A-Z_]+)', source), ['WEATHER_API_KEY'])
        self.assertEqual(source.count('run: python weather_v2_preflight.py'), 1)
        self.assertIn('persist-credentials: false', source)
        self.assertIn('contents: read', source)
        self.assertIn('PREFLIGHT_RERUN_BLOCKED', source)
        for forbidden in ('TELEGRAM_', 'MAX_', 'app_zngrd_weather.py', 'workflow_run:',
                          'workflow_call:', 'schedule:', 'curl ', 'gh workflow', 'upload-artifact'):
            self.assertNotIn(forbidden, source)

    def test_preflight_import_closure_contains_no_publication_modules(self):
        queue = ['weather_v2_preflight']
        seen = set()
        forbidden = {'app_zngrd_weather', 'weather_advice', 'telegram', 'httpx', 'requests'}
        while queue:
            name = queue.pop()
            if name in seen:
                continue
            seen.add(name)
            source = ROOT/(name+'.py')
            tree = ast.parse(source.read_text())
            for node in ast.walk(tree):
                imports = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                           else [node.module] if isinstance(node, ast.ImportFrom) else [])
                for module in imports:
                    self.assertNotIn(module.split('.')[0], forbidden)
                    if (ROOT/(module+'.py')).is_file(): queue.append(module)
        self.assertIn('weather_logic', seen)
        self.assertIn('weather_v2_integration', seen)

    def test_main_returns_failure_for_gaps_and_never_retries(self):
        for category, status in (('OK', 0), ('REQUIRED_FIELD_GAPS', 2), ('FORECAST_STRUCTURE_INVALID', 2)):
            with patch.object(preflight, 'diagnose_weatherapi', return_value={'category': category}) as call, \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(preflight.main(), status)
                call.assert_called_once()

    def test_one_mocked_client_response_is_used_for_v2_and_validation(self):
        response = Mock(status=200)
        response.read.return_value = json.dumps(full_payload()).encode()
        connection = Mock()
        connection.getresponse.return_value = response
        factory = Mock(return_value=connection)
        with patch.object(preflight, 'datetime') as clock:
            clock.now.return_value = datetime(2026,11,5,9,tzinfo=ZoneInfo('Europe/Moscow'))
            result = preflight.diagnose_weatherapi('SECRET_CANARY', connection_factory=factory)
        self.assertEqual(result['category'], 'OK')
        self.assertEqual(result['v2']['status'], 'compatible')
        self.assertEqual(result['request_attempts'], 1)
        factory.assert_called_once()
        connection.request.assert_called_once()
        connection.getresponse.assert_called_once()
        response.read.assert_called_once()
        self.assertNotIn('SECRET_CANARY', json.dumps(result))
