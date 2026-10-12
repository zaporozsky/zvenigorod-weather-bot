import contextlib
import copy
import io
import json
import os
import unittest
from unittest.mock import patch

import httpx

import weather_advice


def forecast_fixture():
    return {
        "date": "2026-10-10",
        "temp_min": 4.5,
        "temp_max": 12.0,
        "max_wind": 28.0,
        "chance_of_rain": 70,
        "chance_of_snow": 5,
        "condition": "Местами дождь",
        "humidity": 80,
        "hourly": [
            {
                "time": f"2026-10-10 {hour:02d}:00",
                "temp_c": 5 + hour / 4,
                "precip_mm": 0.8 if hour == 12 else 0.0,
                "chance_of_rain": 80 if hour == 12 else 10,
                "chance_of_snow": 5,
                "will_it_rain": int(hour == 12),
                "will_it_snow": 0,
                "condition_code": 1183 if hour == 12 else 1000,
                "condition": "Небольшой дождь" if hour == 12 else "Ясно",
                "unknown_secret": "hourly-secret",
            }
            for hour in range(24)
        ],
        "api_key": "forecast-secret",
    }


def completion(content=None, finish_reason="stop"):
    if content is None:
        content = json.dumps({
            "weather_advice": "После обеда возможен дождь, зонт пригодится.",
        }, ensure_ascii=False)
    return {"choices": [{"finish_reason": finish_reason, "message": {"content": content}}]}


class WeatherAdviceTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"LLM_API_KEY": "test-key"}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.forecast = forecast_fixture()
        self.real_client = httpx.Client

    def generate(self, handler, forecast=None):
        def client_factory(**kwargs):
            return self.real_client(transport=httpx.MockTransport(handler), **kwargs)

        with patch("weather_advice.httpx.Client", side_effect=client_factory) as mocked:
            result = weather_advice.generate_weather_advice(
                self.forecast if forecast is None else forecast
            )
        return result, mocked

    def test_request_contains_all_weather_facts_and_key_only_in_header(self):
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(str(request.url), weather_advice.OPENAI_URL)
            self.assertEqual(request.headers["Authorization"], "Bearer test-key")
            self.assertEqual(request.method, "POST")
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "gpt-4.1-mini")
            self.assertEqual(payload["response_format"], {"type": "json_object"})
            facts = json.loads(payload["messages"][1]["content"])
            self.assertEqual(facts["city"], "Звенигород")
            for key in ("date", "temp_min", "temp_max", "max_wind", "chance_of_rain", "chance_of_snow",
                        "condition", "humidity"):
                self.assertEqual(facts[key], self.forecast[key])
            self.assertEqual(len(facts["hourly"]), 24)
            self.assertEqual(facts["hourly"][12]["precip_mm"], 0.8)
            self.assertEqual(facts["hourly"][12]["condition"], "Небольшой дождь")
            self.assertEqual(facts["hourly"][0]["condition"], "Ясно")
            self.assertEqual(facts["hourly"][-1]["time"], "2026-10-10 23:00")
            self.assertNotIn("secret", request.content.decode())
            self.assertNotIn("test-key", request.content.decode())
            return httpx.Response(200, json=completion())

        original = copy.deepcopy(self.forecast)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result, client = self.generate(handler)
        self.assertEqual(len(requests), 1)
        client.assert_called_once_with(timeout=15.0, follow_redirects=False)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(self.forecast, original)
        self.assertEqual(result, "После обеда возможен дождь, зонт пригодится.")
        self.assertNotIn("\n", result)
        self.assertLessEqual(len(result), 180)

    def test_no_key_returns_none_without_network(self):
        with patch.dict(os.environ, {}, clear=True), patch("weather_advice.httpx.Client") as client:
            self.assertIsNone(weather_advice.generate_weather_advice(self.forecast))
            client.assert_not_called()

    def test_openai_key_fallback_and_custom_model(self):
        def handler(request):
            self.assertEqual(request.headers["Authorization"], "Bearer existing-key")
            self.assertEqual(json.loads(request.content)["model"], "gpt-4.1")
            return httpx.Response(200, json=completion())

        with patch.dict(os.environ, {
            "LLM_API_KEY": " ", "OPENAI_API_KEY": "existing-key", "LLM_MODEL": "gpt-4.1"
        }, clear=True):
            result, _ = self.generate(handler)
        self.assertIsNotNone(result)

    def test_http_error_is_silent_and_not_retried(self):
        for status in (401, 429, 500):
            with self.subTest(status=status):
                requests = []

                def handler(request):
                    requests.append(request)
                    return httpx.Response(status, text="private-key-in-error-body")

                output = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    result, _ = self.generate(handler)
                self.assertIsNone(result)
                self.assertEqual(len(requests), 1)
                self.assertEqual(output.getvalue(), "")

    def test_timeout_returns_none_without_retry_or_logs(self):
        requests = []

        def handler(request):
            requests.append(request)
            raise httpx.ReadTimeout("private-key-in-error", request=request)

        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result, _ = self.generate(handler)
        self.assertIsNone(result)
        self.assertEqual(len(requests), 1)
        self.assertEqual(output.getvalue(), "")

    def test_malformed_api_json_returns_none(self):
        result, _ = self.generate(lambda request: httpx.Response(200, text="not JSON"))
        self.assertIsNone(result)

    def test_invalid_response_shapes_and_advice_are_rejected(self):
        invalid = [
            [], {}, {"choices": []}, {"choices": [None]},
            {"choices": [{"message": {"content": 123}, "finish_reason": "stop"}]},
            completion("not JSON"), completion("[]"), completion("null"),
            completion(json.dumps({"weather_advice": " "})),
            completion(json.dumps({"weather_advice": 123})),
            completion(json.dumps({"weather_advice": "Одежда", "day_advice": "План"})),
            completion(json.dumps({"weather_advice": "Одежда", "extra": "Нет"})),
            completion(json.dumps({"weather_advice": "а" * 181})),
            completion(json.dumps({"weather_advice": "☀️" * 150})),
            completion(json.dumps({"weather_advice": "😀" * 100})),
            completion(json.dumps({"weather_advice": "**Куртка**"})),
            completion(json.dumps({"weather_advice": "<b>Куртка</b>"})),
            completion(json.dumps({"weather_advice": "- Куртка"})),
            completion(json.dumps({"weather_advice": "Куртка\nЗонт"})),
            completion(json.dumps({"weather_advice": "Куртка\u200b"})),
            completion(finish_reason="length"),
        ]
        for response in invalid:
            with self.subTest(response=response):
                result, _ = self.generate(lambda request: httpx.Response(200, json=response))
                self.assertIsNone(result)

    def test_exact_length_limit_is_accepted_but_one_more_character_is_rejected(self):
        for weather_length, accepted in ((180, True), (181, False)):
            with self.subTest(weather_length=weather_length):
                response = completion(json.dumps({
                    "weather_advice": "а" * weather_length,
                }))
                result, _ = self.generate(lambda request: httpx.Response(200, json=response))
                self.assertEqual(result is not None, accepted)
                if accepted:
                    self.assertEqual(len(result.encode("utf-16-le")) // 2, 180)

    def test_repeated_forecast_numbers_and_three_sentences_are_rejected(self):
        for weather in (
            "Температура до +13°C.",
            "Сильный ветер до 35 км/ч.",
            "Дождь с вероятностью 70%.",
            "Утром прохладно. Днём потеплеет. Вечером дождь.",
        ):
            with self.subTest(weather=weather):
                response = completion(json.dumps({
                    "weather_advice": weather,
                }))
                result, _ = self.generate(lambda request: httpx.Response(200, json=response))
                self.assertIsNone(result)

    def test_strong_wind_cannot_be_omitted_from_weather_advice(self):
        cases = (
            (29.9, "Дождь маловероятен.", True),
            (30, "Дождь маловероятен.", False),
            (30, "Сегодня сильный ветер, пригодится непродуваемая куртка.", True),
            (35, "Возможен дождь. Сегодня сильный ветер, пригодится куртка с капюшоном.", True),
        )
        for wind, weather, accepted in cases:
            with self.subTest(wind=wind, weather=weather):
                response = completion(json.dumps({"weather_advice": weather}))
                result, _ = self.generate(
                    lambda request: httpx.Response(200, json=response),
                    dict(self.forecast, max_wind=wind),
                )
                self.assertEqual(result is not None, accepted)

    def test_old_awkward_wording_and_activity_suggestions_are_rejected(self):
        comments = (
            "День будет пасмурным с местами дождём, зонт может пригодиться.",
            "День будет пасмурным с местами небольшим дождём, зонт может пригодиться.",
            "Дождь возможен вечером. Утро подойдёт для прогулки.",
            "Возможен дождь. Лучше выбрать короткий маршрут или уютный дом.",
            "Зонт может пригодиться. После можно заняться домашними делами.",
            "Дождливо. Вечер подойдёт для любимых занятий дома.",
        )
        for comment in comments:
            with self.subTest(comment=comment):
                response = completion(json.dumps({"weather_advice": comment}))
                result, _ = self.generate(lambda request: httpx.Response(200, json=response))
                self.assertIsNone(result)

    def test_concise_natural_weather_comments_are_accepted(self):
        for comment in (
            "День будет пасмурным, местами возможен дождь, зонт может пригодиться.",
            "Днём пасмурно, возможен небольшой дождь, может пригодиться зонт.",
            "К вечеру заметно похолодает. Пригодится тёплая куртка.",
        ):
            with self.subTest(comment=comment):
                response = completion(json.dumps({"weather_advice": comment}))
                result, _ = self.generate(lambda request: httpx.Response(200, json=response))
                self.assertEqual(result, comment)

    def test_invalid_forecast_skips_network(self):
        invalid = [None, {}, dict(self.forecast, hourly=[]), dict(self.forecast, temp_min=float("nan")),
                   dict(self.forecast, date="2026-99-99"), dict(self.forecast, hourly=[{}])]
        with patch("weather_advice.httpx.Client") as client:
            for forecast in invalid:
                with self.subTest(forecast=forecast):
                    self.assertIsNone(weather_advice.generate_weather_advice(forecast))
            client.assert_not_called()

    def test_invalid_optional_descriptions_are_omitted_without_losing_forecast(self):
        for condition in ("Ясно\nСкрытая строка", "Ясно\u200b", "а" * 161, 123, " "):
            with self.subTest(condition=condition):
                forecast = copy.deepcopy(self.forecast)
                forecast["condition"] = condition
                forecast["humidity"] = "not a number"
                for hour in forecast["hourly"]:
                    hour["condition"] = condition

                def handler(request):
                    facts = json.loads(json.loads(request.content)["messages"][1]["content"])
                    self.assertNotIn("condition", facts)
                    self.assertNotIn("humidity", facts)
                    self.assertEqual(len(facts["hourly"]), 24)
                    self.assertTrue(all("condition" not in hour for hour in facts["hourly"]))
                    return httpx.Response(200, json=completion())

                result, _ = self.generate(handler, forecast)
                self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
