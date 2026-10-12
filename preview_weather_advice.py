"""Test OpenAI comments on synthetic forecasts without importing the publishing bot."""

from functools import partial
import json
import os
import unicodedata

import httpx

import weather_advice


MAX_CANDIDATE_LENGTH = 500


def candidate_comment(response):
    """Extract only a bounded comment, never response bodies or error details."""
    try:
        content = response.json()["choices"][0]["message"]["content"]
        decoded = json.loads(content)
    except (ValueError, TypeError, KeyError, IndexError, httpx.ResponseNotRead):
        return None
    if not isinstance(decoded, dict):
        return None
    comment = decoded.get("weather_advice")
    if not isinstance(comment, str) or not 0 < len(comment) <= MAX_CANDIDATE_LENGTH:
        return None
    if any(
        unicodedata.category(char).startswith("C") or char in "\u2028\u2029"
        for char in comment
    ):
        return None
    return comment if comment.strip() else None


class OpenAIOnlyClient(httpx.Client):
    def __init__(self, *args, observation=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.observation = observation if observation is not None else {}

    def send(self, request, **kwargs):
        if (
            request.method != "POST"
            or str(request.url) != weather_advice.OPENAI_URL
        ):
            raise RuntimeError("Preview permits only OpenAI comment generation")
        response = super().send(request, **kwargs)
        self.observation["http_status"] = response.status_code
        self.observation.pop("candidate_comment", None)
        if response.status_code == 200:
            candidate = candidate_comment(response)
            if candidate is not None:
                self.observation["candidate_comment"] = candidate
        return response


def synthetic_forecasts():
    """These are artificial scenarios, not archived WeatherAPI responses."""
    profiles = (
        ("Дождь после обеда", "2026-09-09", "Облачно",
         [6, 6, 6, 6, 6, 6, 6, 7, 8, 9, 10, 11, 12, 13, 13, 12, 11, 10, 9, 8, 7, 7, 6, 6],
         set(range(14, 19)), set(), 15),
        ("Сильный ветер, дождь маловероятен", "2026-09-09", "Облачно",
         [10, 10, 10, 10, 10, 10, 11, 12, 13, 14, 15, 16, 17, 18, 18, 17, 16, 15, 14, 13, 12, 11, 10, 10],
         set(), set(), 35),
        ("Похолодание к вечеру", "2026-09-09", "Облачно",
         [12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 10, 8, 5, 2, -1, -4, -5, -6, -6, -6, -6, -6, -6, -6],
         set(), set(), 10),
        ("Снег и мороз", "2026-09-09", "Облачно",
         [-8, -8, -8, -8, -8, -8, -7, -6, -5, -4, -3, -2, -2, -2, -3, -4, -5, -6, -6, -7, -7, -7, -8, -8],
         set(), set(range(8, 17)), 15),
        ("Пасмурный понедельник, местами небольшой дождь", "2026-10-12", "Пасмурно",
         [5, 5, 5, 5, 5, 5, 6, 6, 7, 8, 9, 10, 11, 11, 10, 10, 9, 8, 7, 7, 6, 6, 5, 5],
         {9, 13, 18}, set(), 15),
        ("Сильный ветер и дождь", "2026-09-09", "Облачно",
         [6, 6, 6, 6, 6, 6, 6, 7, 8, 9, 10, 11, 12, 13, 13, 12, 11, 10, 9, 8, 7, 7, 6, 6],
         set(range(14, 19)), set(), 35),
    )
    cases = []
    for name, date, cloud_condition, temperatures, rain_hours, snow_hours, wind in profiles:
        overcast = cloud_condition == "Пасмурно"
        rain_condition = "Местами небольшой дождь" if overcast else "Небольшой дождь"
        rain_code = 1180 if overcast else 1183
        cloud_code = 1009 if overcast else 1006
        precipitation = 0.2 if overcast else 0.4
        hourly = []
        for hour, temperature in enumerate(temperatures):
            rainy, snowy = hour in rain_hours, hour in snow_hours
            hourly.append({
                "time": f"{date} {hour:02d}:00",
                "temp_c": temperature,
                "precip_mm": precipitation if rainy or snowy else 0,
                "chance_of_rain": 70 if rainy else 10 if wind == 35 else 0,
                "chance_of_snow": 80 if snowy else 0,
                "will_it_rain": int(rainy),
                "will_it_snow": int(snowy),
                "condition": rain_condition if rainy else "Снег" if snowy else cloud_condition,
                "condition_code": rain_code if rainy else 1213 if snowy else cloud_code,
            })
        cases.append({"name": name, "forecast": {
            "date": date,
            "temp_min": min(temperatures),
            "temp_max": max(temperatures),
            "max_wind": wind,
            "chance_of_rain": 70 if rain_hours else 10 if wind == 35 else 0,
            "chance_of_snow": 80 if snow_hours else 0,
            "condition": (
                "Пасмурно, местами небольшой дождь" if overcast
                else "Местами дождь" if rain_hours
                else "Снег" if snow_hours else cloud_condition
            ),
            "humidity": 80 if rain_hours or snow_hours else 60,
            "hourly": hourly,
        }})
    return cases


def run_preview():
    cases = synthetic_forecasts()
    if any(weather_advice._forecast_facts(case["forecast"], "Звенигород") is None for case in cases):
        raise ValueError("Incomplete synthetic forecast; no requests made")
    results = []
    original_client = weather_advice.httpx.Client
    try:
        for case in cases:
            observation = {}
            weather_advice.httpx.Client = partial(OpenAIOnlyClient, observation=observation)
            advice = weather_advice.generate_weather_advice(case["forecast"])
            result = {
                "scenario": case["name"],
                "http_status": observation.get("http_status"),
                "status": "generated" if advice else "failed",
                "comment": advice,
                "length": len(advice.encode("utf-16-le")) // 2 if advice else None,
            }
            if advice is None and observation.get("http_status") == 200:
                candidate = observation.get("candidate_comment")
                if candidate is not None:
                    result["candidate_comment"] = candidate
            results.append(result)
    finally:
        weather_advice.httpx.Client = original_client
    return results


def main():
    if not ((os.getenv("LLM_API_KEY") or "").strip() or (os.getenv("OPENAI_API_KEY") or "").strip()):
        print("LLM_API_KEY is missing; no requests made")
        return 1
    results = run_preview()
    print(json.dumps({"source": "synthetic_test_forecasts", "results": results}, ensure_ascii=False, indent=2))
    return 0 if all(result["status"] == "generated" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
