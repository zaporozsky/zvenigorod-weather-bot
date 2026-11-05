"""Offline decision tests: no app import, renderer, model, photo or transport."""
from copy import deepcopy
from dataclasses import asdict, FrozenInstanceError
from datetime import datetime, timedelta
import importlib
import io
import json
from pathlib import Path
import random
import socket
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import weather_conditions
import weather_logic as logic

FIXTURES = Path(__file__).parent / 'fixtures' / 'weather_v2'


def raw_hour(time='2026-11-04 06:00', code=1006, temp=10, **fields):
    result = dict(time=time, condition={'code':code}, temp_c=temp, feelslike_c=temp,
                  precip_mm=0, snow_cm=0, chance_of_rain=0, chance_of_snow=0,
                  wind_kph=10, gust_kph=15, cloud=80, is_day=1)
    result.update(fields)
    return result


def raw_period(**fields):
    return [raw_hour(f'2026-11-04 {h:02}:00', **fields) for h in range(6,12)]


def load_fixture(path):
    data = json.loads(path.read_text())
    records = []
    for row in data['hours']:
        record = dict(zip(data['columns'], row, strict=True))
        record['condition'] = {'code':record.pop('condition_code')}
        records.append(record)
    return data, records


def metric_projection(metric, quantity=False):
    return [metric.count, metric.total if quantity else metric.maximum, metric.complete]


def projection(forecast):
    periods = []
    for period in forecast.periods:
        wind = period.wind
        periods.append(dict(
            hours=period.time_count, known=period.condition_count,
            coverage=period.condition_coverage, dominant=period.predominant,
            is_day=period.is_day, temperature=asdict(period.temperature),
            precip_mm=metric_projection(period.precipitation_mm, True),
            snow_cm=metric_projection(period.snowfall_cm, True),
            rain_probability=metric_projection(period.rain_probability),
            snow_probability=metric_projection(period.snow_probability),
            wind=[wind.speed.maximum,wind.speed_level,len(wind.candidate_speed_times),len(wind.high_speed_times)],
            gust=[wind.gust.maximum,wind.gust_level,len(wind.candidate_gust_times),len(wind.high_gust_times)],
            feelslike=[period.feelslike.count,period.feelslike.minimum,
                       period.feelslike.maximum,period.feelslike.complete],
            felt_colder_lengths=[len(item.times) for item in period.felt_colder_episodes],
            strong_snow_hours=sum(item.strong_snow_supported for item in period.hours),
            hazards=[[item.kind,item.time.strftime('%H:%M'),item.likelihood] for item in period.hazards],
            precipitation=[dict(
                kind=item.kind,expected=item.expected_hours,possible=item.possible_hours,
                unresolved=item.unresolved_hours,duration=item.duration,
                episodes=[[episode.start.strftime('%H:%M'),len(episode.times),episode.likelihood]
                          for episode in item.episodes],
                intensity_counts=[list(pair) for pair in item.intensity_counts],
                predominant_intensity=item.predominant_intensity,
                peak_intensity=item.peak_intensity,
            ) for item in period.precipitation],
        ))
    return dict(periods=periods,
                temp_jumps=[[item.time.strftime('%Y-%m-%d %H:%M'),item.delta_c]
                            for item in forecast.diagnostics if item.code=='TEMP_JUMP'],
                unresolved_rules=list(forecast.unresolved_rules))


class ContractScenarioTests(unittest.TestCase):
    def test_all_eighteen_contract_scenarios(self):
        paths = sorted(FIXTURES.glob('*.json'))
        self.assertEqual(len(paths),18)
        self.assertEqual([json.loads(path.read_text())['scenario'] for path in paths],list(range(1,19)))
        for path in paths:
            with self.subTest(scenario=path.name):
                data, records = load_fixture(path)
                original = deepcopy(records)
                forecast = logic.analyze_hours(records,data['publish_date'])
                self.assertEqual(projection(forecast),data['expected'])
                self.assertEqual(records,original)

    def test_fixture_order_does_not_change_decisions(self):
        for path in sorted(FIXTURES.glob('*.json')):
            with self.subTest(scenario=path.name):
                data, records = load_fixture(path)
                random.Random(42).shuffle(records)
                forecast = logic.analyze_hours(records,data['publish_date'])
                self.assertEqual(projection(forecast),data['expected'])


class InputSafetyTests(unittest.TestCase):
    def test_unknown_fields_and_invalid_values_cannot_leak(self):
        record = raw_hour()
        record.update(token='SECRET_CANARY',url='https://secret.invalid/SECRET_CANARY',
                      Authorization='SECRET_CANARY',temp_c='SECRET_CANARY')
        record['condition']['text']='SECRET_CANARY'
        record['condition']['code']='SECRET_CANARY'
        result = logic.analyze_hours([record], '2026-11-04')
        self.assertNotIn('SECRET_CANARY',repr(result))
        self.assertNotIn('secret.invalid',repr(result))
        self.assertIsNone(result.normalized.hours[0].temp_c)
        self.assertIsNone(result.normalized.hours[0].condition_code)
        fields = {field.name:field for field in result.normalized.sources[0].fields}
        self.assertEqual(fields['temp_c'].state,'invalid')

    def test_missing_null_zero_and_invalid_remain_distinct(self):
        records=[]
        for i,value in enumerate(('missing',None,0,'invalid')):
            record=raw_hour(f'2026-11-04 {6+i:02}:00')
            if value=='missing':
                del record['snow_cm']
            else:
                record['snow_cm']=value
            records.append(record)
        result=logic.normalize_hours(records)
        fields=[next(field for field in src.fields if field.name=='snow_cm') for src in result.sources]
        self.assertEqual([field.state for field in fields],['missing','null','valid','invalid'])
        self.assertEqual([hour.snow_cm for hour in result.hours],[None,None,0,None])

    def test_invalid_numeric_fields_are_not_clamped_or_replaced_with_zero(self):
        for field,values in {
            'temp_c':[True,float('nan'),float('inf'),'10'],
            'feelslike_c':[False,float('-inf')],
            'chance_of_rain':[-1,101,True], 'chance_of_snow':[-.01,100.01],
            'cloud':[-1,101], 'precip_mm':[-1,False], 'snow_cm':[-1],
            'wind_kph':[-1], 'gust_kph':[-1], 'is_day':[2,True,'1'],
        }.items():
            for value in values:
                with self.subTest(field=field,value=value):
                    result=logic.normalize_hours([raw_hour(**{field:value})])
                    self.assertIsNone(getattr(result.hours[0],field))
                    self.assertTrue(any(item.code=='INVALID_FIELD' and item.field==field
                                        for item in result.diagnostics))

    def test_no_bad_input_repr_or_exception_is_retained(self):
        records=[None,[],raw_hour(time='SECRET_CANARY'),raw_hour(time='2026-11-04 6:00')]
        result=logic.normalize_hours(records)
        self.assertEqual(result.hours,())
        self.assertNotIn('SECRET_CANARY',repr(result))
        self.assertEqual(len(result.sources),4)

    def test_identical_duplicates_do_not_double_amounts(self):
        records=raw_period(code=1213,chance_of_snow=80,snow_cm=.1,precip_mm=.1)
        result=logic.analyze_hours(records+[deepcopy(records[0])], '2026-11-04')
        self.assertEqual(result.periods[0].time_count,6)
        self.assertAlmostEqual(result.periods[0].snowfall_cm.total,.6)
        self.assertEqual(len(result.normalized.sources),7)
        self.assertEqual(len([d for d in result.diagnostics if d.code=='IDENTICAL_DUPLICATES']),1)

    def test_conflicting_duplicate_group_is_quarantined_entirely(self):
        records=raw_period(code=1213,chance_of_snow=80,snow_cm=.1,precip_mm=.1)
        conflict=deepcopy(records[2])
        conflict['temp_c']=100
        result=logic.analyze_hours(records+[conflict], '2026-11-04')
        period=result.periods[0]
        self.assertEqual(period.time_count,5)
        self.assertEqual(period.condition_coverage,'limited')
        self.assertAlmostEqual(period.snowfall_cm.total,.5)
        self.assertFalse(period.snowfall_cm.complete)
        self.assertIsNone(period.precipitation[0].duration)
        self.assertEqual([len(item.times) for item in period.precipitation[0].episodes],[2,3])
        self.assertEqual(len(result.normalized.conflict_times),1)
        self.assertEqual(len(result.normalized.sources),7)
        self.assertFalse(any(item.temp_c==100 for item in result.normalized.hours))

    def test_source_projection_ignores_provider_text_for_deduplication(self):
        a=raw_hour()
        b=deepcopy(a)
        a['condition']['text']='Сильный снегопад'
        b['condition']['text']='SECRET_CANARY'
        result=logic.normalize_hours([a,b])
        self.assertEqual(len(result.hours),1)
        self.assertNotIn('SECRET_CANARY',repr(result))

    def test_epoch_agreement_and_conflict(self):
        record=raw_hour()
        record['time_epoch']=int(datetime(2026,11,4,6,tzinfo=ZoneInfo('Europe/Moscow')).timestamp())
        self.assertEqual(len(logic.normalize_hours([record]).hours),1)
        record['time_epoch']+=3600
        result=logic.normalize_hours([record])
        self.assertEqual(result.hours,())
        self.assertTrue(any(item.code=='TIME_CONFLICT' for item in result.diagnostics))

    def test_import_has_no_output_or_transport(self):
        with patch.object(socket,'socket',side_effect=AssertionError('Network forbidden')):
            with patch('sys.stdout',new_callable=io.StringIO) as out, patch('sys.stderr',new_callable=io.StringIO) as err:
                # Fresh execution of each module; no network, output or environment credentials.
                importlib.reload(weather_conditions)
                importlib.reload(logic)
                self.assertEqual(out.getvalue(),'')
                self.assertEqual(err.getvalue(),'')

    def test_data_are_immutable(self):
        result=logic.analyze_hours([raw_hour()], '2026-11-04')
        with self.assertRaises(FrozenInstanceError):
            result.normalized.hours[0].temp_c=50


class TimeAndTemperatureTests(unittest.TestCase):
    def test_period_boundaries_and_next_day_across_month_and_year(self):
        for date in ('2026-11-04','2026-11-30','2026-12-31'):
            with self.subTest(date=date):
                start=datetime.fromisoformat(date+' 00:00')
                records=[raw_hour((start+timedelta(hours=i)).strftime('%Y-%m-%d %H:%M'),
                                  temp=100 if i<6 else i) for i in range(48)]
                result=logic.analyze_hours(records,date)
                self.assertEqual([[hour.hour.temp_c for hour in period.hours] for period in result.periods],
                                 [list(range(6,12)),list(range(12,18)),list(range(18,24)),list(range(24,30))])
                self.assertEqual(result.periods[3].start.date(),(start+timedelta(days=1)).date())
                self.assertEqual(result.periods[-1].end.hour,6)

    def test_bad_publish_date_is_fixed_safe_error(self):
        for date in ('SECRET_CANARY','20261104','2026-02-30',None,123):
            with self.subTest(date=date):
                with self.assertRaisesRegex(ValueError,'publish_date must be YYYY-MM-DD') as raised:
                    logic.analyze_hours([],date)
                self.assertNotIn('SECRET_CANARY',str(raised.exception))

    def test_compact_temperature_threshold_is_before_rounding(self):
        for high,mode in ((2.99,'representative'),(3,'range'),(3.01,'range')):
            with self.subTest(high=high):
                records=[raw_hour(f'2026-11-04 {6+i:02}:00',temp=value)
                         for i,value in enumerate([0,1,1,1,2,high])]
                temperature=logic.analyze_hours(records,'2026-11-04').periods[0].temperature
                self.assertEqual(temperature.mode,mode)
                if mode=='representative':
                    self.assertEqual(temperature.representative,1)

    def test_half_rounding_medians_and_zero(self):
        for temps,expected in (([1,1,2,2],2),([-1,-1,-2,-2],-2),
                               ([-.1,-.1,-.1,-.1],0),([8,10,9,9,9],9)):
            with self.subTest(temps=temps):
                hours=logic.normalize_hours([raw_hour(f'2026-11-04 {6+i:02}:00',temp=t)
                                              for i,t in enumerate(temps)]).hours
                self.assertEqual(logic.aggregate_temperature(hours).representative,expected)

    def test_temperature_needs_four_values_independent_of_condition_coverage(self):
        records=raw_period()
        for record in records[3:]:
            del record['temp_c']
        period=logic.analyze_hours(records,'2026-11-04').periods[0]
        self.assertEqual(period.condition_coverage,'complete')
        self.assertEqual(period.temperature.mode,'unavailable')
        self.assertEqual(period.temperature.count,3)
        records[3]['temp_c']=10
        self.assertEqual(logic.analyze_hours(records,'2026-11-04').periods[0].temperature.mode,'representative')

    def test_jump_threshold_gap_and_no_correction(self):
        for delta,expected in ((5.99,False),(6,True),(-6,True)):
            with self.subTest(delta=delta):
                result=logic.normalize_hours([raw_hour(temp=0),raw_hour('2026-11-04 07:00',temp=delta)])
                self.assertEqual(any(d.code=='TEMP_JUMP' for d in result.diagnostics),expected)
                self.assertEqual([hour.temp_c for hour in result.hours],[0,delta])
        result=logic.normalize_hours([raw_hour(temp=0),raw_hour('2026-11-04 08:00',temp=100)])
        self.assertFalse(any(d.code=='TEMP_JUMP' for d in result.diagnostics))

    def test_daylight_uses_flags_not_season_or_clock(self):
        records=[raw_hour(f'2026-11-04 {h:02}:00',code=1000,is_day=1) for h in range(18,24)]
        period=logic.analyze_hours(records,'2026-11-04').periods[2]
        self.assertEqual(period.is_day,1)
        for record in records[:3]:
            record['is_day']=0
        self.assertEqual(logic.analyze_hours(records,'2026-11-04').periods[2].is_day,1)
        for record in records[:3]:
            del record['is_day']
        self.assertIsNone(logic.analyze_hours(records,'2026-11-04').periods[2].is_day)


class EvidenceTests(unittest.TestCase):
    def test_probability_and_wind_boundaries(self):
        for value,expected in ((0,'low'),(29.9,'low'),(30,'possible'),(69.9,'possible'),(70,'likely'),(100,'likely'),(None,'unknown')):
            self.assertEqual(logic.probability_band(value),expected)
        for gust,values in ((False,((19.9,'none'),(20,'candidate'),(29.9,'candidate'),(30,'high'))),
                            (True,((29.9,'none'),(30,'candidate'),(39.9,'candidate'),(40,'high')))):
            for value,expected in values:
                self.assertEqual(logic.wind_level(value,gust=gust),expected)
        for value in (-1,101,True,float('nan')):
            with self.assertRaises(ValueError):
                logic.probability_band(value)

    def test_heavy_snow_requires_all_confirmation_fields(self):
        for probability in (29.9,30,69.9,70):
            assessment=logic.assess_hour(logic.normalize_hours([raw_hour(code=1225,temp=-2,
                chance_of_snow=probability,snow_cm=.2,precip_mm=.2)]).hours[0])
            self.assertEqual(assessment.strong_snow_supported,probability>=30)
            if probability>=30:
                self.assertEqual(assessment.hazards[0].likelihood,'expected' if probability>=70 else 'possible')
        for field in ('snow_cm','precip_mm','chance_of_snow'):
            for absent in (None,0):
                record=raw_hour(code=1225,chance_of_snow=80,snow_cm=.2,precip_mm=.2)
                record[field]=absent
                item=logic.assess_hour(logic.normalize_hours([record]).hours[0])
                self.assertFalse(item.strong_snow_supported)
                self.assertIsNone(item.intensity)
                self.assertFalse(any(h.kind=='heavy_snow' for h in item.hazards))

    def test_cold_rain_does_not_become_snow(self):
        record=raw_hour(code=1183,temp=-3,chance_of_rain=80,precip_mm=.3)
        item=logic.assess_hour(logic.normalize_hours([record]).hours[0])
        self.assertEqual(item.precipitation,'rain')
        self.assertEqual(item.likelihood,'expected')
        self.assertEqual(item.hazards,())

    def test_freezing_rain_is_retained_and_rain_probability_is_only_proxy(self):
        for probability,amount,expected in ((0,0,'possible'),(30,.2,'possible'),
                                             (69.9,.2,'possible'),(70,.2,'expected'),
                                             (None,.2,'possible'),(80,None,'possible')):
            with self.subTest(probability=probability,amount=amount):
                record=raw_hour(code=1198,chance_of_rain=probability,precip_mm=amount)
                item=logic.assess_hour(logic.normalize_hours([record]).hours[0])
                self.assertEqual(item.precipitation,'freezing_rain')
                self.assertEqual(item.hazards[0].likelihood,expected)
                self.assertEqual(item.likelihood,expected)
        records=raw_period(code=1183,temp=-3,chance_of_rain=80,precip_mm=.2)
        self.assertFalse(logic.analyze_hours(records,'2026-11-04').hazards)

    def test_accepted_rules_produce_explicit_decisions(self):
        for code,fields,phase,likelihood in (
            (1183,dict(chance_of_rain=80,precip_mm=0),'rain','possible'),
            (1183,dict(chance_of_rain=80,precip_mm=.2,snow_cm=.2),'unknown','possible'),
            (1204,dict(precip_mm=.2),'sleet','expected'),
            (1258,dict(chance_of_snow=80,precip_mm=.2,snow_cm=.2),'snow','expected'),
            (1195,dict(chance_of_rain=80,precip_mm=.2),'rain','expected'),
        ):
            with self.subTest(code=code):
                forecast=logic.analyze_hours([raw_hour(code=code,**fields)],'2026-11-04')
                item=forecast.periods[0].hours[0]
                self.assertEqual((item.precipitation,item.likelihood),(phase,likelihood))
                self.assertFalse(forecast.unresolved_rules)
        self.assertFalse(logic.OPEN_RULES)
        self.assertEqual(len(logic.CLOSED_RULES),7)

    def test_partial_probabilities_and_amounts_are_not_imputed_or_multiplied(self):
        records=raw_period(code=1213,chance_of_snow=80,snow_cm=.2,precip_mm=.2)
        del records[0]['snow_cm']
        del records[1]['chance_of_snow']
        period=logic.analyze_hours(records,'2026-11-04').periods[0]
        self.assertEqual(period.snowfall_cm.count,5)
        self.assertAlmostEqual(period.snowfall_cm.total,1)
        self.assertFalse(period.snowfall_cm.complete)
        self.assertEqual(period.snow_probability.count,5)
        self.assertEqual(period.snow_probability.maximum,80)
        self.assertIsNone(period.snow_probability.total)
        self.assertAlmostEqual(period.precipitation_mm.total,1.2)

    def test_prevalence_ties_and_changing_intensities(self):
        records=raw_period()
        for record in records[:3]:
            record['condition']['code']=1000
        period=logic.analyze_hours(records,'2026-11-04').periods[0]
        self.assertIsNone(period.predominant)
        self.assertEqual([(run.kind,len(run.times)) for run in period.category_runs],
                         [('clear',3),('cloudy',3)])
        records[3]['condition']['code']=1000
        self.assertEqual(logic.analyze_hours(records,'2026-11-04').periods[0].predominant,'clear')
        records=raw_period(code=1213,chance_of_snow=80,snow_cm=.2,precip_mm=.2)
        for record in records[3:]:
            record['condition']['code']=1219
        period=logic.analyze_hours(records,'2026-11-04').periods[0]
        self.assertEqual(period.predominant,'snow')
        snow=period.precipitation[0]
        self.assertEqual([len(episode.times) for episode in snow.episodes],[6])
        self.assertEqual(snow.peak_intensity,'moderate')
        self.assertIsNone(snow.predominant_intensity)
        self.assertFalse(period.unresolved_rules)
        self.assertIn('INTENSITY_PREVALENCE_TIE',[d.code for d in period.diagnostics])

    def test_episode_duration_and_partial_period_does_not_claim_prolonged(self):
        for wet,expected in (({0},'brief'),({0,1},'brief'),({0,1,2},'intermittent'),
                             ({0,1,2,3},'intermittent'),({0,1,2,3,4},'prolonged'),
                             ({0,1,2,3,4,5},'prolonged'),({0,2},'intermittent')):
            with self.subTest(wet=wet):
                records=raw_period()
                for i in wet:
                    records[i].update(condition={'code':1183},chance_of_rain=80,precip_mm=.2)
                period=logic.analyze_hours(records,'2026-11-04').periods[0]
                self.assertEqual(period.precipitation[0].duration,expected)
        records=raw_period(code=1198,chance_of_rain=80,precip_mm=.2)[:2]
        period=logic.analyze_hours(records,'2026-11-04').periods[0]
        self.assertEqual(period.condition_coverage,'insufficient')
        self.assertEqual(len(period.hazards),2)
        self.assertIsNone(period.precipitation[0].duration)

    def test_feelslike_difference_needs_two_adjacent_hours(self):
        for positions,expected in (([0],[]),([0,1],[2]),([0,2],[])):
            records=raw_period(temp=10)
            for i in positions:
                records[i]['feelslike_c']=5
            period=logic.analyze_hours(records,'2026-11-04').periods[0]
            self.assertEqual([len(item.times) for item in period.felt_colder_episodes],expected)

    def test_overflow_is_diagnosed_without_new_plausibility_threshold(self):
        records=raw_period(precip_mm=1e308)
        period=logic.analyze_hours(records,'2026-11-04').periods[0]
        self.assertIsNone(period.precipitation_mm.total)
        self.assertEqual(period.precipitation_mm.total_error,'QUANTITY_TOTAL_OVERFLOW')
        self.assertTrue(any(d.code=='QUANTITY_TOTAL_OVERFLOW' for d in period.diagnostics))


class AdditionalSafetyTests(unittest.TestCase):
    def test_off_hour_records_are_not_rounded_into_periods(self):
        result = logic.normalize_hours([raw_hour('2026-11-04 06:30')])
        self.assertEqual(result.hours, ())
        self.assertEqual(result.sources[0].time.minute, 30)
        self.assertTrue(any(d.code == 'OFF_HOUR_TIMESTAMP' for d in result.diagnostics))

    def test_epoch_conflict_also_quarantines_other_records_at_that_time(self):
        good = raw_hour()
        conflict = deepcopy(good)
        conflict['time_epoch'] = int(datetime(2026, 11, 4, 7, tzinfo=ZoneInfo('Europe/Moscow')).timestamp())
        for records in ([good, conflict], [conflict, good]):
            with self.subTest(records_order=[record.get('time_epoch') for record in records]):
                result = logic.normalize_hours(records)
                self.assertEqual(result.hours, ())
                self.assertEqual(len(result.conflict_times), 1)
                self.assertEqual(len(result.sources), 2)

    def test_invalid_duplicate_fields_are_not_assumed_identical(self):
        first = raw_hour(precip_mm='CANARY_A')
        second = raw_hour(precip_mm='CANARY_B')
        result = logic.normalize_hours([first, second])
        self.assertEqual(result.hours, ())
        self.assertNotIn('CANARY_A', repr(result))
        self.assertNotIn('CANARY_B', repr(result))
        forecast = logic.analyze_hours([first, second], '2026-11-04')
        self.assertFalse(forecast.unresolved_rules)
        self.assertIn('DUPLICATE_IDENTITY_QUARANTINED',[d.code for d in forecast.diagnostics])

    def test_type_conflict_does_not_win_by_raw_code_count(self):
        forecast = logic.analyze_hours(raw_period(code=1183, chance_of_rain=80,
                                                  precip_mm=.2, snow_cm=.2), '2026-11-04')
        period = forecast.periods[0]
        self.assertIsNone(period.predominant)
        self.assertEqual(period.condition_count, 0)
        self.assertTrue(all(hour.condition.category == 'rain' for hour in period.hours))
        self.assertTrue(all(hour.likelihood == 'possible' for hour in period.hours))
        self.assertTrue(all(hour.precipitation == 'unknown' for hour in period.hours))

    def test_unknown_night_is_not_substituted_from_start_of_same_date(self):
        records = [raw_hour(f'2026-11-04 {hour:02}:00', temp=-20) for hour in range(6)]
        forecast = logic.analyze_hours(records, '2026-11-04')
        self.assertEqual(forecast.periods[3].time_count, 0)
        self.assertEqual(forecast.periods[3].temperature.mode, 'unavailable')

    def test_subthreshold_values_do_not_trigger_felt_colder(self):
        records = raw_period(temp=10.2, feelslike_c=5.2)
        period = logic.analyze_hours(records, '2026-11-04').periods[0]
        self.assertEqual([len(item.times) for item in period.felt_colder_episodes], [6])
        for record in records:
            record['feelslike_c'] = 5.21
        period = logic.analyze_hours(records, '2026-11-04').periods[0]
        self.assertEqual(period.felt_colder_episodes, ())

    def test_probability_only_snow_does_not_override_cloud_category(self):
        period = logic.analyze_hours(raw_period(chance_of_snow=50), '2026-11-04').periods[0]
        self.assertEqual(period.predominant, 'cloudy')
        self.assertEqual(period.precipitation[0].possible_hours, 6)
        self.assertIsNone(period.precipitation[0].duration)
        self.assertFalse(period.hazards)

    def test_large_finite_source_values_are_retained_without_infinite_diagnostics(self):
        records = raw_period(temp=1e308)
        records[1]['temp_c'] = -1e308
        forecast = logic.analyze_hours(records, '2026-11-04')
        self.assertEqual(forecast.periods[0].temperature.mode, 'range')
        self.assertTrue(any(d.code == 'TEMP_DELTA_OVERFLOW' for d in forecast.diagnostics))
        self.assertTrue(all(d.delta_c is None or abs(d.delta_c) < float('inf') for d in forecast.diagnostics))
