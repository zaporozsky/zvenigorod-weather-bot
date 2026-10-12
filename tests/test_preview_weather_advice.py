from datetime import date
import json
import os
import unittest
from unittest.mock import patch

import httpx

import preview_weather_advice as preview


class PreviewSafetyTests(unittest.TestCase):
    def test_synthetic_cases_include_rainy_monday_and_strong_wind_with_rain(self):
        cases = preview.synthetic_forecasts()
        self.assertEqual(len(cases), 6)
        for case in cases:
            with self.subTest(scenario=case["name"]):
                forecast = case["forecast"]
                self.assertIsNotNone(preview.weather_advice._forecast_facts(forecast, "Звенигород"))
                self.assertEqual(len(forecast["hourly"]), 24)
                self.assertTrue(all(hour["time"].startswith(forecast["date"]) for hour in forecast["hourly"]))

        monday = next(case["forecast"] for case in cases if case["forecast"]["date"] == "2026-10-12")
        self.assertEqual(date.fromisoformat(monday["date"]).weekday(), 0)
        self.assertIn("Пасмурно", monday["condition"])
        self.assertIn("небольшой дождь", monday["condition"])
        rainy_hours = [hour for hour in monday["hourly"] if hour["will_it_rain"]]
        self.assertTrue(rainy_hours)
        self.assertLess(len(rainy_hours), 24)
        self.assertTrue(all(0 < hour["precip_mm"] < 0.4 for hour in rainy_hours))

        wind_and_rain = next(case["forecast"] for case in cases if case["name"] == "Сильный ветер и дождь")
        self.assertGreaterEqual(wind_and_rain["max_wind"], 30)
        self.assertGreater(wind_and_rain["chance_of_rain"], 0)
        self.assertTrue(any(hour["will_it_rain"] and hour["precip_mm"] > 0 for hour in wind_and_rain["hourly"]))

    def test_publishing_and_other_endpoints_are_blocked_before_transport(self):
        requests = []
        with preview.OpenAIOnlyClient(transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200)
        )) as client:
            for url in (
                "https://api.telegram.org/bot-test/sendMessage",
                "https://platform-api2.max.ru/messages",
                "https://api.openai.com/v1/chat/completions?extra=1",
            ):
                with self.subTest(url=url), self.assertRaises(RuntimeError):
                    client.post(url)
            with self.assertRaises(RuntimeError):
                client.get(preview.weather_advice.OPENAI_URL)
        self.assertEqual(requests, [])

    def test_preview_checks_all_scenarios_and_reports_failure_without_fallback(self):
        real_client = preview.OpenAIOnlyClient
        original_httpx_client = httpx.Client
        requests = []

        def handler(request):
            requests.append(request)
            if len(requests) == 3:
                return httpx.Response(401, text="private-key-in-error-body")
            facts = json.loads(json.loads(request.content)["messages"][1]["content"])
            weather = "Сегодня сильный ветер." if facts["max_wind"] >= 30 else "Пригодится куртка."
            return httpx.Response(200, json={"choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({
                    "weather_advice": weather,
                })},
            }]})

        def factory(**kwargs):
            return real_client(transport=httpx.MockTransport(handler), **kwargs)

        with patch.dict(os.environ, {"LLM_API_KEY": "test-key"}, clear=True), patch.object(
            preview, "OpenAIOnlyClient", side_effect=factory
        ):
            results = preview.run_preview()
        self.assertEqual(len(requests), 6)
        self.assertEqual([result["http_status"] for result in results], [200, 200, 401, 200, 200, 200])
        self.assertEqual([result["status"] for result in results], ["generated", "generated", "failed", "generated", "generated", "generated"])
        self.assertEqual(results[2]["status"], "failed")
        self.assertIsNone(results[2]["comment"])
        self.assertNotIn("private-key", json.dumps(results))
        self.assertNotIn("test-key", json.dumps(results))
        self.assertIs(httpx.Client, original_httpx_client)


if __name__ == "__main__":
    unittest.main()
