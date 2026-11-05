"""Only synthetic forecast data, temporary photos and mocked transports."""
import asyncio
import contextlib
import csv
import hashlib
import importlib
import io
import itertools
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from test_weather_logic import FIXTURES, load_fixture
from weather_v2_integration import (PreparationBlocked, diagnostic_snapshot,
                                    live_v2_ready, prepare_v2, save_snapshot)
from weather_v2_photo import PhotoDecision, select_v2_photo


def provider_payload(number=1):
    data, hours = load_fixture(sorted(FIXTURES.glob(f'{number:02}_*.json'))[0])
    grouped = {}
    for hour in hours:
        grouped.setdefault(hour['time'][:10], []).append(hour)
    return {'forecast': {'forecastday': [dict(date=day, hour=rows,
                day={'avghumidity': 70}, astro={'sunrise': '07:00 AM', 'sunset': '05:00 PM'})
            for day, rows in grouped.items()]}}, data['publish_date']


class PreparationTests(unittest.TestCase):
    def test_eighteen_full_offline_chains(self):
        targets = json.loads((FIXTURES/'rendering'/'expected.json').read_text())
        for target in targets:
            with self.subTest(scenario=target['scenario']):
                payload, day = provider_payload(target['scenario'])
                result = prepare_v2(payload, day)
                self.assertEqual(result.blockers, ())
                self.assertEqual(list(result.rendered.period_lines), target['lines'])
                self.assertEqual(result.photo.scenario, target['photo'])
                self.assertIn('🌅 Восход — 07:00', result.rendered.text)
                self.assertIn('🌇 Закат — 17:00', result.rendered.text)

    def test_missing_second_day_does_not_reuse_first_night(self):
        payload, day = provider_payload()
        payload['forecast']['forecastday'] = payload['forecast']['forecastday'][:1]
        result = prepare_v2(payload, day)
        self.assertIn('SECOND_DAY_MISSING', result.diagnostics)
        self.assertEqual(result.forecast.periods[3].time_count, 0)
        self.assertIn('данных недостаточно', result.rendered.period_lines[3])

    def test_day_validation_and_nested_timestamp_mismatch(self):
        payload, day = provider_payload()
        payload['forecast']['forecastday'][0]['hour'].append({'time':'2026-11-05 03:00','temp_c':999})
        result = prepare_v2(payload, day)
        self.assertIn('HOUR_DAY_MISMATCH', result.diagnostics)
        self.assertNotEqual(result.forecast.periods[3].temperature.maximum, 999)
        with self.assertRaisesRegex(PreparationBlocked, 'TARGET_DAY_MISSING'):
            prepare_v2(payload, '2026-11-06')
        with self.assertRaisesRegex(PreparationBlocked, 'INVALID_PUBLISH_DATE'):
            prepare_v2(payload, 'SECRET')
        payload['forecast']['forecastday'].append(payload['forecast']['forecastday'][0])
        with self.assertRaisesRegex(PreparationBlocked, 'TARGET_DAY_MISSING_OR_DUPLICATED'):
            prepare_v2(payload, day)

    def test_missing_or_unusable_day_hours_blocks(self):
        for rows in (None, [], [{'time':'2026-11-04 03:00'}], [{'time':'2026-11-04 06:12'}]):
            payload, day = provider_payload()
            payload['forecast']['forecastday'][0]['hour'] = rows
            with self.subTest(rows=rows), self.assertRaises(PreparationBlocked):
                prepare_v2(payload, day)

    def test_approved_code_only_hazard_is_rendered_as_possible(self):
        payload, day = provider_payload()
        payload['forecast']['forecastday'][0]['hour'][0]['condition']['code'] = 1087
        result = prepare_v2(payload, day)
        self.assertIn('возможна гроза', result.rendered.text)
        self.assertFalse(result.blockers)
        self.assertIsNone(result.photo.scenario)

    def test_snapshot_whitelist_canaries_and_unique_private_files(self):
        payload, day = provider_payload()
        payload.update(token='SECRET_CANARY', Authorization='SECRET_CANARY',url='https://SECRET_CANARY')
        payload['forecast']['forecastday'][0]['day']['avghumidity'] = 'SECRET_CANARY'
        for row in payload['forecast']['forecastday'][0]['hour']:
            row['condition']['text'] = 'SECRET_CANARY'
            row['temperature_secret'] = 'SECRET_CANARY'
            row['cloud'] = 'SECRET_CANARY'
        prepared = prepare_v2(payload, day)
        text = json.dumps(diagnostic_snapshot(prepared))
        self.assertNotIn('SECRET_CANARY', text)
        self.assertNotIn('Authorization', text)
        self.assertIn('invalid', text)
        with tempfile.TemporaryDirectory() as root:
            first = save_snapshot(prepared, root)
            second = save_snapshot(prepared, root)
            self.assertNotEqual(first, second)
            self.assertEqual(first.stat().st_mode & 0o777, 0o600)
            stored = json.loads(first.read_text())
            self.assertIn('created_at',stored)
            self.assertIn('expires_at',stored)
            del stored['created_at'],stored['expires_at']
            self.assertEqual(stored, diagnostic_snapshot(prepared))


class PhotoTests(unittest.TestCase):
    def test_approved_hash_season_required_and_no_season_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'photos'
            (root/'snowy').mkdir(parents=True)
            photo = root/'snowy'/'snow.jpg'
            photo.write_bytes(b'original')
            manifest = root/'photo_seasons.csv'
            fields=['path','weather_category','filename','season','review_status','sha256']
            def write(status='approved', sha=None, season='bare'):
                with manifest.open('w',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
                    writer.writerow(dict(path='photos/snowy/snow.jpg',weather_category='snowy',filename='snow.jpg',
                                         season=season,review_status=status,sha256=sha or hashlib.sha256(b'original').hexdigest()))
            args=dict(photo_dir=root,manifest=manifest,season='bare')
            decision=PhotoDecision('snowy','EXPECTED_SNOW')
            with contextlib.redirect_stdout(io.StringIO()):
                write()
                self.assertEqual(select_v2_photo(decision,{'snowy':'snowy'},**args),str(photo))
                self.assertIsNone(select_v2_photo(decision,{'snowy':'snowy'},**dict(args,season='winter_snow')))
                write(status='pending')
                self.assertIsNone(select_v2_photo(decision,{'snowy':'snowy'},**args))
                write(sha='0'*64)
                self.assertIsNone(select_v2_photo(decision,{'snowy':'snowy'},**args))
                write();photo.write_bytes(b'changed')
                self.assertIsNone(select_v2_photo(decision,{'snowy':'snowy'},**args))

    def test_invalid_season_is_redacted_and_none_scenario_does_not_read_catalogue(self):
        output=io.StringIO()
        with patch('weather_v2_photo.select_weather_photo') as selector, contextlib.redirect_stdout(output):
            self.assertIsNone(select_v2_photo(PhotoDecision(None,'UNKNOWN'),{},season='bare'))
            self.assertIsNone(select_v2_photo(PhotoDecision('snowy','OK'),{'snowy':'snowy'},season='SECRET'))
            selector.assert_not_called()
        self.assertNotIn('SECRET',output.getvalue())


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.app = importlib.import_module('app_zngrd_weather')

    def test_import_has_no_credentials_or_network_side_effects(self):
        with patch.dict(os.environ,{},clear=True), patch('urllib.request.urlopen',side_effect=AssertionError('NO NETWORK')):
            namespace = {}
            source=Path(self.app.__file__).read_text()
            exec(compile(source,self.app.__file__,'exec'),dict(__name__='offline_import',**namespace))

    def test_all_live_gates_are_required(self):
        for enabled, verified, closed in itertools.product((False, True), repeat=3):
            with self.subTest(enabled=enabled, verified=verified, closed=closed), \
                 patch('weather_v2_integration.V2_LIVE_ENABLED', enabled), \
                 patch('weather_v2_integration.V2_CHAIN_VERIFIED', verified), \
                 patch('weather_logic.OPEN_RULES', {} if closed else {'PENDING': 'question'}):
                self.assertEqual(live_v2_ready(), enabled and verified and closed)

    def test_live_gate_blocks_before_credentials_forecast_or_transport(self):
        self.assertFalse(live_v2_ready())
        with patch.object(self.app,'load_credentials') as creds, patch.object(self.app,'get_weather') as weather, \
             patch.object(self.app,'send_post') as send,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.app.main(['--logic-version','v2']),2)
            creds.assert_not_called();weather.assert_not_called();send.assert_not_called()

    def test_cli_local_preview_and_snapshot_without_credentials_or_network(self):
        payload,day=provider_payload(7)
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'input.json';source.write_text(json.dumps(payload))
            output=io.StringIO()
            with patch.dict(os.environ,{},clear=True),patch.object(self.app,'load_credentials') as creds, \
                 patch.object(self.app,'send_post') as send,patch.object(self.app,'get_weather') as weather, \
                 contextlib.redirect_stdout(output):
                status=self.app.main(['--logic-version','v2','--v2-input',str(source),
                    '--publish-date',day,'--diagnostics-dir',str(Path(root)/'snapshots')])
            self.assertEqual(status,0)
            self.assertIn('ледяной дождь',output.getvalue())
            self.assertEqual(len(list((Path(root)/'snapshots').glob('*.json'))),1)
            creds.assert_not_called();send.assert_not_called();weather.assert_not_called()

    def test_v1_default_and_explicit_rollback(self):
        with patch.dict(os.environ,{},clear=True),patch.object(self.app,'run_v1',return_value=0) as v1:
            self.assertEqual(self.app.main([]),0)
            v1.assert_called_once()
        with patch.dict(os.environ,{'WEATHER_LOGIC_VERSION':'v2'}),patch.object(self.app,'run_v1',return_value=0) as v1:
            self.assertEqual(self.app.main(['--logic-version','v1']),0)
            v1.assert_called_once()

    def test_weather_request_defaults_one_and_prepared_two_days(self):
        requests=[]
        def fake_open(url):
            requests.append(parse_qs(urlsplit(url).query));return io.BytesIO(b'{}')
        with patch.object(self.app,'WEATHER_API_KEY','SECRET',create=True), patch('urllib.request.urlopen',side_effect=fake_open):
            self.app.get_weather();self.app.get_weather(days=2)
        self.assertEqual([row['days'] for row in requests],[['1'],['2']])

    def test_future_branch_two_days_and_no_v1_after_partial_failure(self):
        payload, day = provider_payload(7)
        for successful in (False, True):
            with self.subTest(successful=successful), \
                 patch('weather_v2_integration.live_v2_ready', return_value=True), \
                 patch.object(self.app, 'load_credentials') as credentials, \
                 patch.object(self.app, 'get_weather', return_value=payload) as weather, \
                 patch.object(self.app, 'send_post', new_callable=AsyncMock, return_value=successful) as send, \
                 patch.object(self.app, 'run_v1', side_effect=AssertionError('No resend/fallback')), \
                 patch('weather_v2_photo.select_v2_photo', return_value=None), \
                 contextlib.redirect_stdout(io.StringIO()):
                result = self.app.main(['--logic-version', 'v2', '--publish-date', day])
                self.assertEqual(result, 0 if successful else 1)
                credentials.assert_called_once()
                weather.assert_called_once_with(days=2)
                send.assert_awaited_once()
                self.assertIn('ледяной дождь', send.call_args.args[0])

    def test_cli_failure_never_logs_raw_exception(self):
        output = io.StringIO()
        with patch('pathlib.Path.open', side_effect=OSError('SECRET Authorization https://secret')), \
             contextlib.redirect_stdout(output):
            status = self.app.main(['--logic-version','v2','--v2-input','/tmp/not-used.json',
                                    '--publish-date','2026-11-04'])
        self.assertEqual(status, 2)
        self.assertIn('IO_ERROR', output.getvalue())
        self.assertNotIn('SECRET', output.getvalue())
        self.assertNotIn('Authorization', output.getvalue())
        self.assertNotIn('https://', output.getvalue())

    def test_shared_sender_all_failure_combinations_photo_and_text(self):
        payload,day=provider_payload(7)
        text=prepare_v2(payload,day).rendered.text
        for photo in (False,True):
            for failures in itertools.product((False,True),repeat=4):
                with self.subTest(photo=photo,failures=failures):
                    attempts=[];messages=[]
                    def attempt(index,message):
                        attempts.append(index);messages.append(message)
                        if failures[index]:raise RuntimeError('SECRET_CANARY https://secret.invalid Authorization')
                    class Bot:
                        def __init__(self,**kwargs):pass
                        async def __aenter__(self):return self
                        async def __aexit__(self,*args):pass
                        async def send_message(self,*,chat_id,text):attempt(0 if chat_id==-1004382412226 else 1,text)
                        async def send_photo(self,*,chat_id,photo,caption):
                            self_test.assertEqual(photo.read(),b'photo');await self.send_message(chat_id=chat_id,text=caption)
                    def max_send(message,photo_path,*,chat_id):attempt(2 if chat_id=='primary' else 3,message)
                    self_test=self
                    with tempfile.TemporaryDirectory() as root:
                        file=Path(root)/'photo.jpg';file.write_bytes(b'photo')
                        output=io.StringIO()
                        with patch.object(self.app,'Bot',Bot),patch.object(self.app,'send_max_message',side_effect=max_send), \
                             patch.object(self.app,'TELEGRAM_BOT_TOKEN','SECRET',create=True), \
                             patch.object(self.app,'MAX_CHAT_ID','primary',create=True),patch.object(self.app,'MAX_NEWS_CHAT_ID','news',create=True), \
                             patch.object(self.app,'get_weather_photo',side_effect=AssertionError('Must use preselected photo')), \
                             contextlib.redirect_stdout(output):
                            success=asyncio.run(self.app.send_post(text,selected_photo=str(file) if photo else None))
                    self.assertEqual(success,not any(failures))
                    self.assertEqual(attempts,[0,1,2,3])
                    self.assertEqual(messages,[text]*4)
                    self.assertNotIn('SECRET',output.getvalue())
                    self.assertNotIn('Authorization',output.getvalue())
                    self.assertNotIn('https://',output.getvalue())
                    logs=[json.loads(row) for row in output.getvalue().splitlines()]
                    self.assertEqual([x['result'] for x in logs[:-1]],['failure' if x else 'success' for x in failures])
                    self.assertEqual(logs[-1]['failed'],sum(failures))
