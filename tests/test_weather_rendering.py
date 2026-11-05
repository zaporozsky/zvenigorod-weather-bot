"""Reviewed synthetic outputs, independent of provider text and network."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from test_weather_logic import FIXTURES, load_fixture, raw_hour, raw_period
from weather_logic import Hazard, analyze_hours
from weather_rendering import (Ancillary, RenderingBlocked, deterministic_comment,
                               render_forecast, render_period, utf16_length)


class RenderingTests(unittest.TestCase):
    def test_eighteen_exact_outputs(self):
        expected = json.loads((FIXTURES / 'rendering' / 'expected.json').read_text())
        self.assertEqual(len(expected), 18)
        for path, target in zip(sorted(FIXTURES.glob('*.json')), expected, strict=True):
            with self.subTest(path=path.name):
                data, hours = load_fixture(path)
                forecast = analyze_hours(hours, data['publish_date'])
                result = render_forecast(forecast)
                self.assertEqual(list(result.period_lines), target['lines'])
                self.assertEqual(result.comment, target['comment'])
                self.assertEqual(result.text, target['text'])
                self.assertLessEqual(utf16_length(result.text), 1024)
                self.assertEqual(result, render_forecast(forecast))

    def test_utf16_and_compaction_preserve_four_lines_and_warnings(self):
        self.assertEqual(utf16_length('🌤️'), 3)
        data, hours = load_fixture(sorted(FIXTURES.glob('07_*.json'))[0])
        forecast = analyze_hours(hours, data['publish_date'])
        # Controlled ancillary content pressure forces the optional-info branch.
        with patch('weather_rendering._weather_details', side_effect=lambda f, compact=False: [] if compact else ['x'*1000]):
            result = render_forecast(forecast, Ancillary(humidity=70, sunrise='07:00'))
        self.assertTrue(result.compact)
        self.assertEqual(len(result.period_lines), 4)
        self.assertIn('ледяной дождь', result.period_lines[2])
        self.assertIn('возможно обледенение', result.comment)
        self.assertLessEqual(utf16_length(result.text), 1024)

    def test_budget_fails_closed_instead_of_cutting_warnings(self):
        forecast = analyze_hours(raw_period(), '2026-11-04')
        with patch('weather_rendering.render_period', return_value='x'*300):
            with self.assertRaisesRegex(RenderingBlocked, 'MESSAGE_TOO_LONG'):
                render_forecast(forecast)

    def test_unresolved_decisions_cannot_be_rendered(self):
        forecast = analyze_hours(raw_period(code=1087), '2026-11-04')
        period = replace(forecast.periods[0], unresolved_rules=('FUTURE_UNAPPROVED_RULE',))
        forecast = replace(forecast, periods=(period, *forecast.periods[1:]),
                           unresolved_rules=('FUTURE_UNAPPROVED_RULE',))
        self.assertTrue(forecast.unresolved_rules)
        with self.assertRaisesRegex(RenderingBlocked, 'UNRESOLVED_RULES'):
            render_forecast(forecast)
        with self.assertRaises(RenderingBlocked):
            render_period(forecast.periods[0])

    def test_missing_temperature_and_daylight_are_not_invented(self):
        hours = raw_period(code=1000, temp=None, is_day=None)
        result = render_forecast(analyze_hours(hours, '2026-11-04'))
        self.assertIn('температура не уточнена', result.period_lines[0])
        self.assertNotIn('☀', result.period_lines[0])
        self.assertNotIn('🌙', result.period_lines[0])

    def test_partial_warning_not_suppressed_or_promoted(self):
        hours = [raw_hour(code=1198, chance_of_rain=0)]
        forecast = analyze_hours(hours, '2026-11-04')
        result = render_forecast(forecast)
        self.assertIn('данных недостаточно', result.period_lines[0])
        self.assertIn('возможен ледяной дождь в доступные часы', result.period_lines[0])
        self.assertIn('возможен', result.comment)
        self.assertNotIn('ожидается', result.comment)

    def test_hazards_precede_wind_and_wind_is_still_visible(self):
        data, hours = load_fixture(sorted(FIXTURES.glob('07_*.json'))[0])
        for hour in hours:
            hour.update(wind_kph=35, gust_kph=50)
        result = render_forecast(analyze_hours(hours, data['publish_date']))
        self.assertIn('ледяной дождь', result.comment)
        self.assertIn('Сильный ветер', result.text)
        self.assertIn('Сильные порывы', result.text)

    def test_precipitation_intensity_peak_does_not_describe_the_whole_period(self):
        hours = raw_period(code=1213, temp=-2, chance_of_snow=90, snow_cm=1, precip_mm=.8)
        hours[2]['condition']['code'] = 1225
        result = render_forecast(analyze_hours(hours, '2026-11-04'))
        self.assertIn('продолжительный небольшой снег', result.period_lines[0])
        self.assertIn('сильный снег в 08:00', result.period_lines[0])
        self.assertNotIn('продолжительный сильный снег', result.period_lines[0])

    def test_ancillary_cannot_inject_provider_strings(self):
        forecast = analyze_hours(raw_period(), '2026-11-04')
        result = render_forecast(forecast, Ancillary('SECRET', 'SECRET', 'SECRET', 'SECRET'))
        self.assertNotIn('SECRET', result.text)

    def test_temperature_jump_does_not_change_text_values(self):
        data, hours = load_fixture(sorted(FIXTURES.glob('18_*.json'))[0])
        forecast = analyze_hours(hours, data['publish_date'])
        self.assertIn('TEMP_JUMP', [d.code for d in forecast.diagnostics])
        self.assertIn('+10…+17°', render_forecast(forecast).period_lines[1])

    def test_wind_twenty_does_not_trigger_clothing_advice(self):
        data, hours = load_fixture(sorted(FIXTURES.glob('09_*.json'))[0])
        comment = deterministic_comment(analyze_hours(hours, data['publish_date']))
        self.assertEqual(comment, 'Утром заметный ветер')
        self.assertNotIn('куртк', comment)

    def test_unknown_hazard_blocks_and_warning_loss_blocks(self):
        forecast = analyze_hours(raw_period(), '2026-11-04')
        period = replace(forecast.periods[0], hazards=(Hazard('UNSUPPORTED', forecast.periods[0].start, 'possible'),))
        with self.assertRaisesRegex(RenderingBlocked, 'UNKNOWN_HAZARD'):
            render_forecast(replace(forecast, periods=(period, *forecast.periods[1:])))
        data, hours = load_fixture(sorted(FIXTURES.glob('07_*.json'))[0])
        with patch('weather_rendering.render_period', return_value='missing warning'):
            with self.assertRaisesRegex(RenderingBlocked, 'WARNING_LOST'):
                render_forecast(analyze_hours(hours, data['publish_date']))
