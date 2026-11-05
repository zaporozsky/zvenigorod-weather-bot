"""Contract 1.1, accepted PO additions and release safety, all offline."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import contextlib
import importlib
import io
import itertools
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from test_weather_logic import FIXTURES, load_fixture, raw_hour, raw_period
from test_weather_v2_integration import provider_payload
import weather_logic as logic
from weather_rendering import clothing_advice, render_forecast, utf16_length
from weather_v2_integration import prepare_v2, purge_snapshots, save_snapshot
from weather_v2_photo import photo_scenario
from weather_v2_preflight import diagnose_weatherapi


class ApprovedRulesTests(unittest.TestCase):
    def assess(self, code, **fields):
        return logic.assess_hour(logic.normalize_hours([raw_hour(code=code, **fields)]).hours[0])

    def test_known_rain_and_snow_probability_amount_matrix(self):
        for code, field in ((1183,'chance_of_rain'), (1213,'chance_of_snow')):
            for probability, amount in itertools.product((None,0,29.9,30,69.9,70,100), (None,0,.2)):
                with self.subTest(code=code, probability=probability, amount=amount):
                    item=self.assess(code, **{field:probability,'precip_mm':amount})
                    expected='expected' if amount and (probability is None or probability>=70) else 'possible'
                    self.assertEqual(item.likelihood,expected)
                    self.assertFalse(item.unresolved_rules)
                    if probability is not None and probability<30 and amount:
                        self.assertIn('PRECIPITATION_PROBABILITY_AMOUNT_CONFLICT',[d.code for d in item.diagnostics])
        snow=self.assess(1213,chance_of_snow=None,precip_mm=None,snow_cm=.2)
        self.assertEqual(snow.likelihood,'expected')
        self.assertIsNone(snow.hour.chance_of_snow)

    def test_generic_precipitation_does_not_invent_a_phase(self):
        for code in (1006,9999):
            for fields in ({'precip_mm':.2},{'snow_cm':.2},{'chance_of_rain':80,'chance_of_snow':80}):
                with self.subTest(code=code,fields=fields):
                    item=self.assess(code,**fields)
                    self.assertEqual((item.precipitation,item.likelihood),('unknown','possible'))
        for field,phase in (('chance_of_rain','rain'),('chance_of_snow','snow')):
            self.assertEqual(self.assess(1006,**{field:80}).precipitation,phase)
        forecast=logic.analyze_hours(raw_period(code=1183,chance_of_rain=80,precip_mm=.2,snow_cm=.2),'2026-11-04')
        result=render_forecast(forecast)
        self.assertIn('возможны осадки',result.period_lines[0])
        self.assertIsNone(photo_scenario(forecast).scenario)
        self.assertFalse(forecast.unresolved_rules)

    def test_freezing_type_conflict_keeps_possible_icing_warning(self):
        for code,kind in ((1198,'freezing_rain'),(1168,'freezing_drizzle')):
            item=self.assess(code,chance_of_rain=80,precip_mm=.2,snow_cm=.2)
            self.assertEqual(item.precipitation,'unknown')
            self.assertEqual([(h.kind,h.likelihood) for h in item.hazards],[(kind,'possible')])
            self.assertFalse(item.unresolved_rules)
            result=render_forecast(logic.analyze_hours(raw_period(code=code,chance_of_rain=80,precip_mm=.2,snow_cm=.2),'2026-11-04'))
            self.assertIn('⚠️',result.period_lines[0])
            self.assertIn('возмож',result.comment)
            self.assertNotIn('ожидается',result.comment)

    def test_sleet_and_ice_never_borrow_phase_probability(self):
        for code,phase in ((1069,'sleet'),(1204,'sleet'),(1207,'sleet'),(1237,'ice_pellets'),(1264,'ice_pellets')):
            for amount,probability in itertools.product((0,.2,None),(0,80,None)):
                with self.subTest(code=code,amount=amount,p=probability):
                    hours=raw_period(code=code,precip_mm=amount,chance_of_rain=probability,chance_of_snow=probability)
                    forecast=logic.analyze_hours(hours,'2026-11-04')
                    event=forecast.periods[0].precipitation[0]
                    self.assertEqual(event.kind,phase)
                    self.assertIsNone(event.probability)
                    self.assertEqual(event.expected_hours,6 if amount else 0)
                    self.assertFalse(forecast.unresolved_rules)
                    self.assertLessEqual(utf16_length(render_forecast(forecast).text),1024)

    def test_ambiguous_snow_can_only_warn_about_possible_heavy_snow(self):
        for probability, snow, amount in itertools.product((None,0,29.9,30,70), (0,.2), (0,.2)):
            with self.subTest(p=probability,snow=snow,amount=amount):
                item=self.assess(1258,chance_of_snow=probability,snow_cm=snow,precip_mm=amount)
                confirmed=probability is not None and probability>=30 and snow>0 and amount>0
                self.assertFalse(item.strong_snow_supported)
                self.assertEqual(bool(item.hazards),confirmed)
                if confirmed:
                    self.assertEqual(item.intensity,'moderate_or_heavy')
                    self.assertEqual(item.hazards[0].likelihood,'possible')
                else:
                    self.assertEqual(item.likelihood,'possible')
                    self.assertIsNone(item.intensity)
        result=render_forecast(logic.analyze_hours(raw_period(code=1258,chance_of_snow=80,snow_cm=.2,precip_mm=.2),'2026-11-04'))
        self.assertIn('умеренный или сильный снег',result.text)
        self.assertIn('возможен сильный снег',result.text)
        self.assertNotIn('ожидается сильный снег',result.text)

    def test_other_hazards_are_possible_and_heavy_rain_is_evidence_gated(self):
        for code,kind in ((1087,'thunder'),(1117,'blizzard'),(1114,'blowing_snow'),(1147,'freezing_fog'),(1021,'dust_storm')):
            item=self.assess(code)
            self.assertEqual([(h.kind,h.likelihood) for h in item.hazards],[(kind,'possible')])
            self.assertFalse(item.unresolved_rules)
        for code,probability,amount,expected in ((1195,70,.2,'expected'),(1195,69.9,.2,'possible'),
                                               (1195,80,0,'possible'),(1243,80,.2,'possible')):
            item=self.assess(code,chance_of_rain=probability,precip_mm=amount)
            self.assertEqual(next(h.likelihood for h in item.hazards if h.kind=='heavy_rain'),expected)

    def test_intensity_tie_preserves_timed_heavy_episode(self):
        hours=raw_period(code=1213,temp=-2,chance_of_snow=80,precip_mm=.2,snow_cm=.2)
        for hour in hours[3:]:hour['condition']['code']=1225
        forecast=logic.analyze_hours(hours,'2026-11-04')
        snow=forecast.periods[0].precipitation[0]
        self.assertIsNone(snow.predominant_intensity)
        self.assertEqual(snow.intensity_counts,(('heavy',3),('light',3)))
        self.assertFalse(snow.unresolved_rules)
        line=render_forecast(forecast).period_lines[0]
        self.assertIn('продолжительный снег',line)
        self.assertIn('сильный снег в 09:00–11:00',line)
        self.assertNotIn('продолжительный сильный снег',line)

    def test_unprovable_duplicates_leave_publishable_partial_period(self):
        hours=raw_period()
        hours[0]['precip_mm']='SECRET_A'
        duplicate=deepcopy(hours[0]);duplicate['precip_mm']='SECRET_B'
        forecast=logic.analyze_hours([*hours,duplicate],'2026-11-04')
        self.assertFalse(forecast.unresolved_rules)
        self.assertEqual(forecast.periods[0].time_count,5)
        self.assertIn('[5/6 ч]',render_forecast(forecast).period_lines[0])
        self.assertNotIn('SECRET_',repr(forecast))


class EditorialReleaseTests(unittest.TestCase):
    def test_eighteen_expected_outputs_match_approved_document_verbatim(self):
        contract=(Path(__file__).parents[1]/'docs/weather-logic-v2-editorial-contract-1.1.md').read_text()
        blocks=re.split(r'\*\*Сценарий \d+ — ',contract)[1:]
        expected=json.loads((FIXTURES/'rendering'/'expected.json').read_text())
        self.assertEqual(len(blocks),18)
        for block,target in zip(blocks,expected,strict=True):
            self.assertEqual(target['lines'],re.search(r'```text\n(.*?)\n```',block,re.S).group(1).splitlines())
            self.assertEqual(target['comment'],re.search(r'Комментарий: «(.*?)»',block).group(1))
            photo=re.search(r'Фото: (?:`([^`]+)`|(без фотографии))',block)
            self.assertEqual(target['photo'],photo.group(1))

    def advice(self,**fields):
        return clothing_advice(logic.analyze_hours(raw_period(**fields),'2026-11-04').periods[0])

    def test_clothing_thresholds_and_missing_feelslike(self):
        for temp,felt,expected in ((0,10,'тёплая одежда'),(10,0,'тёплая одежда'),
                                   (8,5,'дополнительный слой'),(8.01,5,None),(8,5.01,None),
                                   (-1,None,'тёплая одежда'),(8,None,None)):
            with self.subTest(temp=temp,felt=felt):
                advice=self.advice(temp=temp,feelslike_c=felt)
                self.assertEqual(advice is None,expected is None)
                if expected:self.assertIn(expected,advice)
        self.assertIsNone(self.advice(temp=15,feelslike_c=15,wind_kph=20))
        self.assertIn('непродуваемая',self.advice(temp=0,wind_kph=20))
        self.assertIn('непродуваемая',self.advice(temp=0,wind_kph=0,gust_kph=40))
        self.assertIn('непромокаемая',self.advice(temp=6,feelslike_c=2,wind_kph=30,code=1183,chance_of_rain=80,precip_mm=.2))

    def test_clothing_needs_coincident_adjacent_hours_or_explicit_short_timing(self):
        hours=raw_period(temp=15,feelslike_c=15)
        hours[0].update(temp_c=0,feelslike_c=0,wind_kph=20)
        period=logic.analyze_hours(hours,'2026-11-04').periods[0]
        self.assertEqual(clothing_advice(period),'в 06:00 пригодится тёплая непродуваемая одежда')
        hours[1].update(temp_c=0,feelslike_c=0,wind_kph=20)
        self.assertEqual(clothing_advice(logic.analyze_hours(hours,'2026-11-04').periods[0]),'пригодится тёплая непродуваемая одежда')
        # Morning wind is not combined with later rain.
        hours=raw_period(temp=15,wind_kph=30)
        for hour in hours[3:]:hour.update(wind_kph=0,condition={'code':1183},chance_of_rain=80,precip_mm=.2)
        self.assertIsNone(clothing_advice(logic.analyze_hours(hours,'2026-11-04').periods[0]))

    def test_photo_precipitation_duration_and_wind_priorities(self):
        for phase,code in (('rain',1183),('snow',1213)):
            for count in (1,2,3):
                hours=raw_period(wind_kph=35,gust_kph=45)
                for row in hours[:count]:
                    row.update(condition={'code':code},chance_of_rain=80 if phase=='rain' else 0,
                               chance_of_snow=80 if phase=='snow' else 0,precip_mm=.2,snow_cm=.2 if phase=='snow' else 0)
                forecast=logic.analyze_hours(hours,'2026-11-04')
                # Add ordinary evening/day so coverage, rather than a missing period, is not the reason.
                payload,day=provider_payload();payload['forecast']['forecastday'][0]['hour'][:6]=hours
                decision=prepare_v2(payload,day).photo
                expected=('rainy' if count>=3 else 'small_rain_possible') if phase=='rain' else ('snowy' if count>=3 else 'strong_wind')
                self.assertEqual(decision.scenario,expected)


class RetentionTests(unittest.TestCase):
    def setUp(self):
        payload,day=provider_payload()
        self.prepared=prepare_v2(payload,day)
        self.now=datetime(2026,11,5,tzinfo=timezone.utc)

    def test_seven_day_expiry_and_selective_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            file=save_snapshot(self.prepared,root,now=self.now)
            metadata=json.loads(file.read_text())
            self.assertEqual(datetime.fromisoformat(metadata['expires_at'])-self.now,timedelta(days=7))
            unrelated=Path(root)/'unrelated.json';unrelated.write_text('keep')
            symlink=Path(root)/'weather-v2-symlink.json';symlink.symlink_to(unrelated)
            self.assertEqual(purge_snapshots(root,now=self.now+timedelta(days=7,microseconds=-1)),0)
            self.assertEqual(purge_snapshots(root,now=self.now+timedelta(days=7)),1)
            self.assertFalse(file.exists())
            self.assertEqual(unrelated.read_text(),'keep')
            self.assertTrue(symlink.is_symlink())

    def test_tampered_expiry_cannot_extend_seven_days(self):
        with tempfile.TemporaryDirectory() as root:
            file=save_snapshot(self.prepared,root,now=self.now)
            value=json.loads(file.read_text());value['expires_at']=(self.now+timedelta(days=70)).isoformat()
            file.write_text(json.dumps(value))
            self.assertEqual(purge_snapshots(root,now=self.now+timedelta(days=7)),1)

    def test_save_prunes_old_snapshots_and_requires_private_directory(self):
        with tempfile.TemporaryDirectory() as root:
            first=save_snapshot(self.prepared,root,now=self.now)
            second=save_snapshot(self.prepared,root,now=self.now+timedelta(days=7))
            self.assertFalse(first.exists());self.assertTrue(second.exists())
            os.chmod(root,0o755)
            with self.assertRaisesRegex(ValueError,'PRIVATE_DIAGNOSTICS_DIRECTORY_REQUIRED'):
                save_snapshot(self.prepared,root,now=self.now)

    def test_future_live_snapshots_are_deleted_after_success_and_failure(self):
        app=importlib.import_module('app_zngrd_weather')
        payload,day=provider_payload()
        real_save=save_snapshot
        for delivered in (False,True):
            paths=[]
            def capture(prepared,directory):
                result=real_save(prepared,directory);paths.append(result);return result
            with self.subTest(delivered=delivered), \
                 patch('weather_v2_integration.live_v2_ready',return_value=True), \
                 patch('weather_v2_integration.save_snapshot',side_effect=capture), \
                 patch.object(app,'load_credentials'),patch.object(app,'get_weather',return_value=payload), \
                 patch('weather_v2_photo.select_v2_photo',return_value=None), \
                 patch.object(app,'send_post',new_callable=AsyncMock,return_value=delivered), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(app.main(['--logic-version','v2','--publish-date',day]),0 if delivered else 1)
            self.assertEqual(len(paths),1)
            self.assertFalse(paths[0].exists())
            self.assertFalse(paths[0].parent.exists())

    def test_persistent_live_diagnostics_block_before_credentials_or_request(self):
        app=importlib.import_module('app_zngrd_weather')
        with patch('weather_v2_integration.live_v2_ready',return_value=True), \
             patch.object(app,'load_credentials') as credentials,patch.object(app,'get_weather') as weather, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(['--logic-version','v2','--diagnostics-dir','/tmp/not-used']),2)
            credentials.assert_not_called();weather.assert_not_called()


class PreflightTests(unittest.TestCase):
    def test_missing_key_performs_zero_requests(self):
        factory=unittest.mock.Mock()
        result=diagnose_weatherapi(None,connection_factory=factory)
        self.assertEqual(result['request_attempts'],0)
        self.assertEqual(result['category'],'WEATHER_API_KEY_UNAVAILABLE')
        factory.assert_not_called()

    def connection(self,status=200,body=None,error=None):
        payload,_=provider_payload()
        response=unittest.mock.Mock(status=status)
        response.read.return_value=json.dumps(payload if body is None else body).encode()
        connection=unittest.mock.Mock()
        connection.getresponse.return_value=response
        if error:connection.request.side_effect=error
        factory=unittest.mock.Mock(return_value=connection)
        return factory,connection,response

    def test_exactly_one_days_two_request_and_only_safe_report(self):
        payload,_=provider_payload()
        payload.update(secret='SECRET_CANARY',Authorization='SECRET_CANARY')
        payload['forecast']['forecastday'][0]['hour'][0]['condition']['text']='SECRET_CANARY'
        factory,connection,response=self.connection(body=payload)
        report=diagnose_weatherapi('SECRET_CANARY',connection_factory=factory)
        connection.request.assert_called_once()
        method,path=connection.request.call_args.args
        from urllib.parse import parse_qs,urlsplit
        params=parse_qs(urlsplit(path).query)
        self.assertEqual(method,'GET')
        self.assertEqual(params['days'],['2'])
        self.assertEqual(params['q'],['55.7352,36.8553'])
        self.assertEqual(report['request_attempts'],1)
        self.assertEqual(report['returned_days'],2)
        self.assertNotIn('SECRET',json.dumps(report))
        self.assertNotIn('Authorization',json.dumps(report))
        self.assertNotIn('https://',json.dumps(report))
        connection.close.assert_called_once()
        response.read.assert_called_once()

    def test_no_retry_or_redirect_and_no_exception_details(self):
        for status,error in ((302,None),(403,None),(200,OSError('SECRET_CANARY https://secret'))):
            factory,connection,response=self.connection(status=status,error=error)
            result=diagnose_weatherapi('SECRET',connection_factory=factory)
            self.assertEqual(result['request_attempts'],1)
            connection.request.assert_called_once()
            factory.assert_called_once()
            self.assertNotIn('SECRET',json.dumps(result))
            self.assertNotIn('https://',json.dumps(result))
            self.assertNotEqual(result['category'],'OK')

    def test_invalid_response_only_emits_categorical_error(self):
        factory,connection,response=self.connection()
        response.read.return_value=b'NOT JSON SECRET_CANARY'
        result=diagnose_weatherapi('SECRET',connection_factory=factory)
        self.assertEqual(result['category'],'INVALID_JSON_RESPONSE')
        self.assertNotIn('SECRET',json.dumps(result))


class CompleteChainEdgeTests(unittest.TestCase):
    def test_extreme_hazards_fit_budget_without_losing_warnings_or_dates(self):
        fixture=json.loads((FIXTURES/'rendering'/'extreme_hazards.json').read_text())
        forecast=logic.analyze_hours(fixture['hours'],fixture['publish_date'])
        result=render_forecast(forecast)
        self.assertTrue(result.compact)
        self.assertEqual(len(result.period_lines),4)
        self.assertLessEqual(utf16_length(result.text),1024)
        self.assertIn('4 ноября',result.text)
        self.assertIn('Ночь 05.11',result.text)
        self.assertIn('Сильный ветер',result.text)
        self.assertIn('Сильные порывы',result.text)
        from weather_rendering import WARNING_NAMES
        for line in result.period_lines:
            for kind in fixture['warning_kinds']:
                self.assertIn(WARNING_NAMES[kind],line)
            self.assertIn('возможны:',line)
            self.assertIn('[4/6 ч]',line)

    def test_every_registered_code_has_a_safe_closed_rule_rendering(self):
        from weather_conditions import CONDITIONS
        for code in CONDITIONS:
            with self.subTest(code=code):
                forecast=logic.analyze_hours(raw_period(code=code),'2026-11-04')
                self.assertFalse(forecast.unresolved_rules)
                text=render_forecast(forecast).text
                self.assertLessEqual(utf16_length(text),1024)
                self.assertNotIn('интенсивность неясна',text)

    def test_fully_unusable_day_blocks_before_delivery(self):
        payload,day=provider_payload()
        for row in payload['forecast']['forecastday'][0]['hour']:
            row['condition']['code']=9999
            row['temp_c']=None
        from weather_v2_integration import PreparationBlocked
        with self.assertRaisesRegex(PreparationBlocked,'TARGET_DAY_HOURS_UNUSABLE'):
            prepare_v2(payload,day)

    def test_failed_atomic_snapshot_write_leaves_no_partial_files(self):
        payload,day=provider_payload()
        with tempfile.TemporaryDirectory() as root:
            with patch('weather_v2_integration.os.replace',side_effect=OSError('SECRET')):
                with self.assertRaises(OSError):
                    save_snapshot(prepare_v2(payload,day),root)
            self.assertEqual(list(Path(root).iterdir()),[])

    def test_heavy_rain_type_conflict_does_not_reintroduce_rain_warning(self):
        hours=raw_period(code=1195,chance_of_rain=80,precip_mm=.2,snow_cm=.2)
        forecast=logic.analyze_hours(hours,'2026-11-04')
        self.assertFalse(any(h.kind=='heavy_rain' for h in forecast.hazards))
        self.assertIn('возможны осадки',render_forecast(forecast).period_lines[0])

    def test_agreed_heavy_rain_photo_precedes_wind_and_unrepresented_hazards_fall_back(self):
        payload,day=provider_payload()
        for row in payload['forecast']['forecastday'][0]['hour'][:6]:
            row.update(condition={'code':1195},chance_of_rain=80,precip_mm=.2,wind_kph=35)
        self.assertEqual(prepare_v2(payload,day).photo.scenario,'rainy')
        for row in payload['forecast']['forecastday'][0]['hour'][:6]:
            row.update(condition={'code':1117},chance_of_rain=0,precip_mm=0)
        self.assertIsNone(prepare_v2(payload,day).photo.scenario)

    def test_potential_thunder_precedes_confirmed_strong_snow_in_comment(self):
        payload,day=provider_payload(5)
        payload['forecast']['forecastday'][0]['hour'][0]['condition']['code']=1087
        result=prepare_v2(payload,day)
        self.assertIn('гроза',result.rendered.comment)
        self.assertIn('сильный снег',result.rendered.period_lines[1])

    def test_precipitation_icons_use_registry_and_unknown_codes_stay_neutral(self):
        for code,icon in ((1183,'🌦️'),(1189,'🌧️'),(1153,'🌦️'),(9999,'❔')):
            forecast=logic.analyze_hours(raw_period(code=code,chance_of_rain=80,precip_mm=.2 if code!=9999 else 0),'2026-11-04')
            line=render_forecast(forecast).period_lines[0]
            self.assertIn(icon,line)
            if code!=9999:self.assertNotIn('условия не уточнены',line)


class FullV2ChainTests(unittest.TestCase):
    def test_actual_v2_preparation_photo_and_four_transports_are_mocked_end_to_end(self):
        from urllib.error import HTTPError
        from telegram.error import BadRequest
        import hashlib
        import csv
        from weather_photo_selector import select_weather_photo as real_selector
        app=importlib.import_module('app_zngrd_weather')
        for second_telegram_fails in (False,True):
            with self.subTest(second_telegram_fails=second_telegram_fails),tempfile.TemporaryDirectory() as root:
                photos=Path(root)/'photos';category=photos/'cloudy_comfortable';category.mkdir(parents=True)
                image=category/'approved.jpg';image.write_bytes(b'photo')
                manifest=photos/'photo_seasons.csv'
                with manifest.open('w',newline='') as stream:
                    fields=['path','weather_category','filename','season','review_status','sha256']
                    writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
                    writer.writerow(dict(path='photos/cloudy_comfortable/approved.jpg',weather_category='cloudy_comfortable',
                                         filename='approved.jpg',season='bare',review_status='approved',
                                         sha256=hashlib.sha256(b'photo').hexdigest()))
                payload,day=provider_payload()
                attempts=[];messages=[];uploads=[];snapshots=[]
                def photo_select(scenario,mapping,**kwargs):
                    return real_selector(scenario,mapping,**dict(kwargs,manifest=manifest))
                test=self
                class FakeBot:
                    def __init__(self,**kwargs):pass
                    async def __aenter__(self):return self
                    async def __aexit__(self,*args):pass
                    async def send_photo(self,*,chat_id,photo,caption):
                        test.assertEqual(photo.read(),b'photo')
                        attempts.append('telegram_primary' if chat_id==-1004382412226 else 'telegram_news')
                        messages.append(caption)
                        if chat_id=='@svoi_zvenigorod' and second_telegram_fails:
                            raise BadRequest('Chat not found SECRET_CANARY https://secret')
                    async def send_message(self,**kwargs):
                        raise AssertionError('Approved matching photo must pass through the full chain')
                def urlopen(request,**kwargs):
                    url=request.full_url
                    if url=='https://platform-api2.max.ru/uploads?type=image':
                        uploads.append(url);body={'url':'https://upload.invalid/photo'}
                    elif url=='https://upload.invalid/photo':
                        test.assertEqual(request.data,b'photo');body={'photos':{'image':{'token':'SECRET_CANARY'}}}
                    elif url.startswith('https://platform-api2.max.ru/messages?chat_id='):
                        attempts.append('max_primary' if url.endswith('primary') else 'max_news')
                        data=json.loads(request.data);messages.append(data['text'])
                        test.assertEqual(data['attachments'][0]['payload']['token'],'SECRET_CANARY')
                        body={'success':True}
                    else:
                        raise AssertionError('Unexpected request; external network forbidden')
                    return io.BytesIO(json.dumps(body).encode())
                def capture(prepared,directory):
                    file=save_snapshot(prepared,directory);snapshots.append(file);return file
                output=io.StringIO()
                with patch.dict(os.environ,dict(TELEGRAM_BOT_TOKEN='SECRET_CANARY',WEATHER_API_KEY='SECRET_CANARY',
                          MAX_BOT_TOKEN='SECRET_CANARY',MAX_CHAT_ID='primary',MAX_NEWS_CHAT_ID='news',PHOTO_SEASON='bare')), \
                     patch('weather_v2_integration.live_v2_ready',return_value=True), \
                     patch('weather_v2_integration.save_snapshot',side_effect=capture), \
                     patch.object(app,'PHOTO_DIR',str(photos)),patch.object(app,'Bot',FakeBot), \
                     patch.object(app,'get_weather',return_value=payload) as weather, \
                     patch('weather_v2_photo.select_weather_photo',side_effect=photo_select), \
                     patch('urllib.request.urlopen',side_effect=urlopen), \
                     patch.object(app,'run_v1',side_effect=AssertionError('No V1 resend')), \
                     contextlib.redirect_stdout(output):
                    status=app.main(['--logic-version','v2','--publish-date',day])
                self.assertEqual(status,1 if second_telegram_fails else 0)
                weather.assert_called_once_with(days=2)
                self.assertEqual(attempts,['telegram_primary','telegram_news','max_primary','max_news'])
                self.assertEqual(len(uploads),2)
                self.assertEqual(len(set(messages)),1)
                self.assertLessEqual(utf16_length(messages[0]),1024)
                self.assertEqual(len(snapshots),1)
                self.assertFalse(snapshots[0].exists())
                self.assertNotIn('SECRET_CANARY',output.getvalue())
                self.assertNotIn('https://',output.getvalue())
