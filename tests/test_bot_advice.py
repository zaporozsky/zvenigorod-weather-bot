import ast
import contextlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def weather_response(kind, wind=10):
    rain = 80 if kind == "rain" else 0
    snow = 80 if kind == "snow" else 0
    temp = -5 if snow else 12
    condition = "Снег" if snow else "Дождь" if rain else "Ясно"
    hours = [
        {
            "time": f"2026-10-10 {hour:02d}:00",
            "temp_c": temp,
            "precip_mm": 1 if rain or snow else 0,
            "chance_of_rain": rain,
            "chance_of_snow": snow,
            "will_it_rain": int(bool(rain)),
            "will_it_snow": int(bool(snow)),
            "condition": {"text": condition, "code": 1219 if snow else 1189 if rain else 1000},
        }
        for hour in range(24)
    ]
    return {
        "current": {"pressure_mb": 1013},
        "forecast": {
            "forecastday": [
                {
                    "date": "2026-10-10",
                    "hour": hours,
                    "day": {
                        "mintemp_c": temp - 3,
                        "maxtemp_c": temp + 3,
                        "condition": {"text": condition},
                        "daily_chance_of_rain": rain,
                        "daily_chance_of_snow": snow,
                        "maxwind_kph": wind,
                        "avghumidity": 70,
                        "totalprecip_mm": 24 if rain or snow else 0,
                    },
                    "astro": {"sunrise": "07:00 AM", "sunset": "06:00 PM"},
                }
            ]
        },
    }


class BotAdviceIntegrationTests(unittest.TestCase):
    def assert_short_weather_comment(self, comment):
        self.assertTrue(comment.strip())
        self.assertLessEqual(len(comment.encode("utf-16-le")) // 2, 180)
        self.assertNotRegex(comment, r"\d")
        self.assertLessEqual(len(re.findall(r"[.!?…]+(?:\s|$)", comment)), 1)
        self.assertNotRegex(comment.lower(), r"прогул|маршрут|план|\bдом\w*|занят|уют|\bдел[ао]\b")

    def execute_bot(self, kind, advice, wind=10):
        telegram_posts = []
        max_posts = []
        forecast_requests = []

        class FakeBot:
            def __init__(self, token):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def send_photo(self, *, chat_id, photo, caption):
                telegram_posts.append(caption)

            async def send_message(self, *, chat_id, text):
                telegram_posts.append(text)

        def urlopen(request, **kwargs):
            url = request if isinstance(request, str) else request.full_url
            if url.startswith("https://api.weatherapi.com/v1/forecast.json?"):
                forecast_requests.append(url)
                body = weather_response(kind, wind)
            elif url == "https://platform-api2.max.ru/uploads?type=image":
                body = {"url": "https://upload.invalid/image"}
            elif url == "https://upload.invalid/image":
                body = {"photos": {"uploaded": {"token": "test-image"}}}
            elif url.startswith("https://platform-api2.max.ru/messages?chat_id="):
                max_posts.append(json.loads(request.data)["text"])
                body = {"success": True}
            else:
                raise AssertionError(f"Unexpected request: {url}")
            return io.BytesIO(json.dumps(body).encode())

        previous_dir = Path.cwd()
        try:
            os.chdir(ROOT)
            with (
                patch.dict(os.environ, {
                    "TELEGRAM_BOT_TOKEN": "test-placeholder",
                    "WEATHER_API_KEY": "test-placeholder",
                    "MAX_BOT_TOKEN": "test-placeholder",
                    "MAX_CHAT_ID": "test-chat",
                    "MAX_NEWS_CHAT_ID": "test-news-chat",
                }),
                patch("urllib.request.urlopen", side_effect=urlopen),
                patch("telegram.Bot", FakeBot),
                patch("httpx.Client", side_effect=AssertionError("Real HTTP is forbidden")),
                patch("weather_advice.generate_weather_advice", return_value=advice) as generate,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                namespace = runpy.run_path(str(ROOT / "app_zngrd_weather.py"))
        finally:
            os.chdir(previous_dir)

        self.assertEqual(len(forecast_requests), 1)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(generate.call_args.kwargs, {"city": "Звенигород"})
        forecast = generate.call_args.args[0]
        self.assertEqual(len(forecast["hourly"]), 24)
        post = namespace["post"]
        self.assertEqual(telegram_posts, [post, post])
        self.assertEqual(max_posts, [post, post])
        self.assertLessEqual(len(post.encode("utf-16-le")) // 2, 1024)
        self.assertIn("Доброе утро, Звенигород!", post)
        self.assertIn("Восход — 07:00", post)
        comment = post.split("мм рт. ст.\n\n", 1)[1].split("\n\n", 1)[0]
        self.assert_short_weather_comment(comment)
        if advice is None and wind >= 30:
            self.assertIn("сильный ветер", comment.lower())
            if kind in ("rain", "snow"):
                self.assertIn("дождь" if kind == "rain" else "снег", comment)
                self.assertIn("капюшон", comment)
            else:
                self.assertEqual(comment, "Сегодня сильный ветер, пригодится непродуваемая куртка.")
        elif advice is None:
            expected_list = {
                "dry": "ORDINARY_CALM_TEXTS",
                "rain": "RAINY_TEXTS",
                "snow": "SNOWY_TEXTS",
            }[kind]
            self.assertTrue(any(
                text.format(temp_max=forecast["temp_max"]) in post
                for text in namespace[expected_list]
            ), "The post must contain a nonempty fallback for its forecast")
        return post

    def test_generated_advice_used_once_and_shared_by_all_channels(self):
        advice = "После обеда возможен дождь, зонт пригодится."
        post = self.execute_bot("rain", advice)
        self.assertEqual(post.count(advice), 1)

    def test_maximum_advice_fits_telegram_photo_caption(self):
        advice = "А" * 180
        self.assertIn(advice, self.execute_bot("dry", advice))

    def test_fallback_forecasts_still_publish(self):
        for kind in ("dry", "rain", "snow"):
            with self.subTest(kind=kind):
                self.execute_bot(kind, None)

    def test_fallback_preserves_strong_wind_with_rain_and_snow(self):
        for kind in ("dry", "rain", "snow"):
            with self.subTest(kind=kind):
                self.execute_bot(kind, None, wind=35)

    def test_every_fallback_variant_is_one_short_weather_phrase(self):
        tree = ast.parse((ROOT / "app_zngrd_weather.py").read_text())
        lists = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.endswith("_TEXTS")
        }
        self.assertEqual(len(lists), 13)
        for name, variants in lists.items():
            with self.subTest(scenario=name):
                self.assertGreaterEqual(len(variants), 2)
                for comment in variants:
                    self.assert_short_weather_comment(comment)


if __name__ == "__main__":
    unittest.main()
