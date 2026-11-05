import unittest
from dataclasses import FrozenInstanceError

from weather_conditions import CONDITIONS, UNKNOWN, condition_for


class ConditionTests(unittest.TestCase):
    def test_registry_has_unique_expected_codes(self):
        expected = {
            1000,1003,1006,1009,1012,1015,1018,1021,1024,1027,1030,1033,1036,
            1039,1042,1045,1048,1063,1066,1069,1072,1087,1114,1117,1135,1147,
            1150,1153,1168,1171,1180,1183,1186,1189,1192,1195,1198,1201,1204,
            1207,1210,1213,1216,1219,1222,1225,1237,1240,1243,1246,1249,1252,
            1255,1258,1261,1264,1273,1276,1279,1282,
        }
        self.assertEqual(set(CONDITIONS), expected)
        for code, item in CONDITIONS.items():
            self.assertEqual(item.code, code)
            self.assertTrue(item.text_ru)
            self.assertTrue(item.emoji_day)
            self.assertTrue(item.emoji_night)

    def test_exact_audit_conditions(self):
        for code, phase, intensity in (
            (1213, 'snow', 'light'), (1225, 'snow', 'heavy'),
            (1198, 'freezing_rain', 'light'),
        ):
            with self.subTest(code=code):
                item = condition_for(code)
                self.assertEqual(item.precipitation, phase)
                self.assertEqual(item.intensity, intensity)
                self.assertNotEqual(item.emoji_day, '🌤️')

    def test_unknown_and_malformed_codes_are_neutral(self):
        for code in (None, -1, 9999, True, 1000.0, '1000', {}, []):
            with self.subTest(code=code):
                self.assertIs(condition_for(code), UNKNOWN)
                self.assertEqual(condition_for(code).emoji(None), '❔')

    def test_solar_icons_require_actual_binary_is_day(self):
        for code in (1000,1003):
            item = condition_for(code)
            self.assertEqual(item.emoji(0), '🌙')
            self.assertNotEqual(item.emoji(1), '🌙')
            for absent in (None,True,False,2,'1'):
                self.assertIsNone(item.emoji(absent))
        self.assertEqual(condition_for(1213).emoji(None), '❄️')

    def test_frozen_registry_and_entries(self):
        with self.assertRaises(TypeError):
            CONDITIONS[1000] = UNKNOWN
        with self.assertRaises(FrozenInstanceError):
            condition_for(1000).category = 'rain'

    def test_dangerous_types_are_distinct_and_blown_snow_is_not_snowfall(self):
        self.assertEqual(condition_for(1198).potential_hazards, ('freezing_rain',))
        self.assertEqual(condition_for(1168).potential_hazards, ('freezing_drizzle',))
        self.assertEqual(condition_for(1117).potential_hazards, ('blizzard',))
        self.assertIsNone(condition_for(1114).precipitation)
        self.assertEqual(condition_for(1204).precipitation, 'sleet')
        self.assertNotEqual(condition_for(1258).intensity, 'heavy')
