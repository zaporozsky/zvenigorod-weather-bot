import os
import asyncio
import urllib.parse
import urllib.request
import json
import random
from datetime import datetime

from telegram import Bot


TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
WEATHER_API_KEY = os.environ["WEATHER_API_KEY"]

CHANNEL_ID = -1004382412226
# Звенигород, Московская область
CITY = "Звенигород"
LOCATION = "55.7352,36.8553"
GREETING_ICONS = [
    "☀️",
    "🌼",
    "❤️",
    "💚",
    "🩵",
    "🧡",
    "💜",
    "🙌",
]

PHOTO_DIR = "photos"

PHOTO_SCENARIOS = {
    "sunny_warm": "sunny_warm",
    "cloudy_comfortable": "cloudy_comfortable",
    "rainy": "rainy",
    "small_rain_possible": "small_rain_possible",
    "snowy": "snowy",
    "fog": "fog",
    "cold": "cold",
    "strong_wind": "strong_wind",
    "sharp_cooling": "cold",
    "sharp_warming": "sunny_warm",
    "unusually_warm": "sunny_warm",
    "ordinary_calm": "cloudy_comfortable",
    "very_cold": "cold",
}

def format_time_24(time):
    return datetime.strptime(time, "%I:%M %p").strftime("%H:%M")

def get_weather():
    params = urllib.parse.urlencode({
        "key": WEATHER_API_KEY,
        "q": LOCATION,
        "days": 1,
        "lang": "ru",
    })

    url = "https://api.weatherapi.com/v1/forecast.json?" + params

    with urllib.request.urlopen(url) as response:
        return json.load(response)

    url = "https://api.weatherapi.com/v1/forecast.json?" + params

    with urllib.request.urlopen(url) as response:
        return json.load(response)


def analyze_rain(forecast):
    hourly = forecast["hourly"]

    # Считаем час дождевым, если прогнозируются заметные осадки
    # или WeatherAPI явно указывает, что в этот час будет дождь.
    rain_hours = []

    for hour in hourly:
        is_rain = (
            hour["precip_mm"] > 0.1
            or hour["will_it_rain"] == 1
        )

        if is_rain:
            rain_hours.append(hour)

    # Если дождя нет
    if not rain_hours:
        return {
            "rain_hours": 0,
            "episodes": 0,
            "max_precip_mm": 0.0,
            "max_precip_time": None,
            "duration": "none",
            "pattern": "none",
        }

    # Максимальная интенсивность дождя
    max_rain_hour = max(
        rain_hours,
        key=lambda hour: hour["precip_mm"]
    )

    max_precip_mm = max_rain_hour["precip_mm"]
    max_precip_time = max_rain_hour["time"]

    # Определяем отдельные эпизоды дождя.
    # Новый эпизод начинается, если между дождевыми часами
    # есть хотя бы один сухой час.
    rain_times = {
        hour["time"] for hour in rain_hours
    }

    from datetime import datetime, timedelta

    episodes = 0
    previous_time = None

    for hour in rain_hours:
        current_time = datetime.strptime(
            hour["time"],
            "%Y-%m-%d %H:%M"
        )

        if (
            previous_time is None
            or current_time - previous_time > timedelta(hours=1)
        ):
            episodes += 1

        previous_time = current_time

    # Определяем продолжительность
    rain_hour_count = len(rain_hours)

    if rain_hour_count <= 1:
        duration = "short"
    elif rain_hour_count <= 3:
        duration = "intermittent"
    elif rain_hour_count <= 7:
        duration = "prolonged"
    else:
        duration = "most_of_day"

    # Определяем, в какое время суток дождь наиболее вероятен
    periods = {
        "morning": 0,      # 06:00–09:59
        "daytime": 0,      # 10:00–13:59
        "afternoon": 0,    # 14:00–17:59
        "evening": 0,      # 18:00–21:59
        "night": 0,        # остальные часы
    }

    for hour in rain_hours:
        hour_number = int(hour["time"][11:13])

        if 6 <= hour_number < 10:
            periods["morning"] += 1
        elif 10 <= hour_number < 14:
            periods["daytime"] += 1
        elif 14 <= hour_number < 18:
            periods["afternoon"] += 1
        elif 18 <= hour_number < 22:
            periods["evening"] += 1
        else:
            periods["night"] += 1

    pattern = max(periods, key=periods.get)

    # Если дождь распределён достаточно равномерно в течение дня,
    # считаем его характером "all_day".
    daytime_hours = (
        periods["morning"]
        + periods["daytime"]
        + periods["afternoon"]
        + periods["evening"]
    )

    active_periods = sum(
        1 for period in (
            "morning",
            "daytime",
            "afternoon",
            "evening",
        )
        if periods[period] > 0
    )

    if daytime_hours >= 6 and active_periods >= 3:
        pattern = "all_day"

    return {
        "rain_hours": rain_hour_count,
        "episodes": episodes,
        "max_precip_mm": max_precip_mm,
        "max_precip_time": max_precip_time,
        "duration": duration,
        "pattern": pattern,
    }

def get_temperature_level(temp_min, temp_max):
    # Для определения характера дня используем максимальную температуру.
    temp = temp_max

    if temp < -20:
        return "severe_frost"
    elif temp < -15:
        return "strong_frost"
    elif temp < -10:
        return "very_cold"
    elif temp < -5:
        return "cold"
    elif temp < 5:
        return "cool"
    elif temp < 10:
        return "autumn_cool"
    elif temp < 18:
        return "moderate"
    elif temp < 25:
        return "warm"
    elif temp < 30:
        return "hot"
    else:
        return "very_hot"

def analyze_temperature_change(forecast):
    hourly = forecast["hourly"]

    if len(hourly) < 2:
        return "none"

    for i in range(len(hourly)):
        current_time = datetime.strptime(
            hourly[i]["time"],
            "%Y-%m-%d %H:%M"
        )

        current_temp = hourly[i]["temp_c"]

        for j in range(i):
            previous_time = datetime.strptime(
                hourly[j]["time"],
                "%Y-%m-%d %H:%M"
            )

            time_difference = current_time - previous_time

            if time_difference.total_seconds() == 6 * 60 * 60:
                previous_temp = hourly[j]["temp_c"]
                temperature_change = current_temp - previous_temp

                if temperature_change > 15:
                    return "sharp_warming"

                if temperature_change < -15:
                    return "sharp_cooling"

    return "none"

def get_precipitation_probability_text(probability, precipitation_type):
    if precipitation_type == "snow":
        if probability <= 10:
            return "Снега не предвидится"
        elif probability <= 30:
            return "Снега, скорее всего, не будет"
        elif probability <= 50:
            return "Возможно, пойдет снег"
        elif probability <= 70:
            return "Скорее всего, пойдет снег"
        elif probability <= 90:
            return "Наверняка выпадет снег"
        else:
            return "Пойдет снег"

    else:
        if probability <= 10:
            return "Дождя не предвидится"
        elif probability <= 30:
            return "Дождя, скорее всего, не будет"
        elif probability <= 50:
            return "Возможен дождь"
        elif probability <= 70:
            return "Скорее всего, будет дождь"
        elif probability <= 90:
            return "Большая вероятность дождя"
        else:
            return "Будет дождь"

        

def get_precipitation_timing(forecast, precipitation_type):
    hourly = forecast["hourly"]

    precipitation_hours = []

    for hour in hourly:
        hour_number = int(hour["time"][11:13])

        # Ночью не учитываем осадки для основного описания дня.
        # Они могут быть добавлены отдельно позже, если понадобится.
        if hour_number < 6:
            continue

        if precipitation_type == "snow":
            is_precipitation = (
                hour["precip_mm"] > 0.1
                or hour["will_it_snow"] == 1
                or hour["chance_of_snow"] >= 30
            )
        else:
            is_precipitation = (
                hour["precip_mm"] > 0.1
                or hour["will_it_rain"] == 1
                or hour["chance_of_rain"] >= 30
            )

        if is_precipitation:
            precipitation_hours.append(hour)

    if not precipitation_hours:
        return ""

    # Группируем часы по периодам
    periods = {
        "morning": [],
        "daytime": [],
        "afternoon": [],
        "evening": [],
    }

    for hour in precipitation_hours:
        hour_number = int(hour["time"][11:13])

        if 6 <= hour_number < 10:
            periods["morning"].append(hour)

        elif 10 <= hour_number < 14:
            periods["daytime"].append(hour)

        elif 14 <= hour_number < 18:
            periods["afternoon"].append(hour)

        elif 18 <= hour_number < 24:
            periods["evening"].append(hour)

    active_periods = [
        name
        for name, hours in periods.items()
        if hours
    ]

    total_hours = len(precipitation_hours)

    # Практически весь день
    if (
        total_hours >= 8
        and len(active_periods) >= 3
    ):
        return f"{get_precipitation_word(precipitation_type)} на весь день"

    # Только один короткий эпизод
    if total_hours <= 2:
        if active_periods == ["morning"]:
            return f"Утром возможен кратковременный {get_precipitation_word(precipitation_type)}"

        if active_periods == ["daytime"]:
            return f"Днём возможен кратковременный {get_precipitation_word(precipitation_type)}"

        if active_periods == ["afternoon"]:
            return f"После обеда возможен кратковременный {get_precipitation_word(precipitation_type)}"

        if active_periods == ["evening"]:
            return f"Вечером возможен кратковременный {get_precipitation_word(precipitation_type)}"

        if active_periods == ["morning", "evening"]:
            return f"{get_precipitation_word(precipitation_type).capitalize()} возможен утром и вечером"

    # Несколько периодов
    if active_periods == ["morning", "evening"]:
        return f"Осадки возможны утром и вечером"

    if active_periods == ["daytime", "evening"]:
        return f"{get_precipitation_word(precipitation_type).capitalize()} ожидается днём и вечером"

    if active_periods == ["afternoon", "evening"]:
        return f"{get_precipitation_word(precipitation_type).capitalize()} ожидается после обеда и вечером"

    if active_periods == ["morning", "daytime", "afternoon", "evening"]:
        return f"{get_precipitation_word(precipitation_type).capitalize()} в течение всего дня"

    # Отдельные периоды
    if active_periods == ["morning"]:
        return f"{get_precipitation_word(precipitation_type).capitalize()} ожидается утром"

    if active_periods == ["daytime"]:
        return f"{get_precipitation_word(precipitation_type).capitalize()} ожидается днём"

    if active_periods == ["afternoon"]:
        return f"{get_precipitation_word(precipitation_type).capitalize()} ожидается после обеда"

    if active_periods == ["evening"]:
        return f"{get_precipitation_word(precipitation_type).capitalize()} ожидается вечером"

    return ""


def get_precipitation_word(precipitation_type):
    if precipitation_type == "snow":
        return "снег"

    return "дождь"

def get_day_scenario(forecast, rain_analysis):
    rain = forecast["chance_of_rain"]
    wind = forecast["max_wind"]
    humidity = forecast["humidity"]
    temp_min = forecast["temp_min"]
    temp_max = forecast["temp_max"]
    condition = forecast["condition"].lower()
    temperature_change = analyze_temperature_change(forecast)

    # 1. Снег
    # При отрицательной температуре значительные осадки
    # считаем снегом независимо от классификации WeatherAPI.
    precipitation_probability = max(
        forecast["chance_of_rain"],
        forecast["chance_of_snow"]
    )

    has_hourly_precipitation = any(
        hour["precip_mm"] > 0.1
        for hour in forecast["hourly"]
    )

    if (
        temp_max < 0
        and (
            precipitation_probability >= 30
            or has_hourly_precipitation
        )
    ):
        return "snowy"

    # 2. Дождь
    if rain >= 70:
        return "rainy"

    if rain >= 30:
        return "small_rain_possible"

    # 3. Очень холодно
    if temp_max < -10:
        return "very_cold"

    # 4. Холодный день
    # Температура имеет приоритет над сильным ветром.
    if temp_max < 5:
        return "cold"

    # 5. Резкое изменение температуры
    if temperature_change == "sharp_cooling":
        return "sharp_cooling"

    if temperature_change == "sharp_warming":
        return "sharp_warming"

    # 6. Сильный ветер
    if wind >= 30:
        return "strong_wind"

    # 7. Туман / высокая влажность
    if humidity >= 90 and (
        "туман" in condition
        or "мгла" in condition
    ):
        return "fog"

    # 9. Очень тепло
    if temp_max >= 30:
        return "unusually_warm"

    # 10. Солнечно и тепло
    if (
        "солнечно" in condition
        or "ясно" in condition
    ) and temp_max >= 18:
        return "sunny_warm"

    # 11. Облачно, но комфортно
    if (
        "облачно" in condition
        or "переменная облачность" in condition
    ) and 10 <= temp_max < 25:
        return "cloudy_comfortable"

    # 12. Обычный спокойный день
    return "ordinary_calm"

def normalize_weather(weather):
    forecast_day = weather["forecast"]["forecastday"][0]

    day = forecast_day["day"]
    astro = forecast_day["astro"]

    hourly = []

    for hour in forecast_day["hour"]:
        hourly.append({
            "time": hour["time"],
            "temp_c": hour["temp_c"],
            "precip_mm": hour["precip_mm"],
            "chance_of_rain": hour["chance_of_rain"],
            "chance_of_snow": hour["chance_of_snow"],
            "will_it_rain": hour["will_it_rain"],
            "will_it_snow": hour["will_it_snow"],
            "condition": hour["condition"]["text"],
            "condition_code": hour["condition"]["code"],
        })

    return {
        "date": forecast_day["date"],
        "temp_min": day["mintemp_c"],
        "temp_max": day["maxtemp_c"],
        "condition": day["condition"]["text"],
        "chance_of_rain": day["daily_chance_of_rain"],
        "chance_of_snow": day["daily_chance_of_snow"],
        "max_wind": day["maxwind_kph"],
        "humidity": day["avghumidity"],
        "total_precip_mm": day["totalprecip_mm"],
        "pressure_mb": weather["current"]["pressure_mb"],
        "sunrise": astro["sunrise"],
        "sunset": astro["sunset"],
        "hourly": hourly,
    }

def normalize_condition(condition):
    condition = condition.lower().strip()

    condition_map = {
        "солнечно": "Ясно",
        "ясно": "Ясно",

        "малооблачно": "Малооблачно",
        "переменная облачность": "Малооблачно",

        "облачно": "Облачно",
        "облачно с прояснениями": "Облачно с прояснениями",

        "пасмурно": "Пасмурно",

        "местами дождь поблизости": "Небольшой дождь",
        "небольшой дождь": "Небольшой дождь",
        "небольшой дождь местами": "Небольшой дождь",

        "умеренный дождь": "Дождь",
        "дождь": "Дождь",

        "сильный дождь": "Сильный дождь",

        "гроза": "Гроза",

        "небольшой снег": "Снег",
        "снег": "Снег",
        "умеренный снег": "Снег",
        "сильный снег": "Сильный снег",

        "туман": "Туман",
        "дымка": "Дымка",
    }

    return condition_map.get(condition, condition)

def get_weather_icon(condition, is_night=False):

    if condition == "Ясно":
        return "🌙" if is_night else "☀️"

    if condition == "Малооблачно":
        return "🌙" if is_night else "🌤️"

    if condition == "Облачно":
        return "☁️"

    if condition == "Облачно с прояснениями":
        return "⛅"

    if condition == "Пасмурно":
        return "☁️"

    if condition == "Небольшой дождь":
        return "🌦"

    if condition == "Дождь":
        return "🌧️"

    if condition == "Сильный дождь":
        return "🌧️"

    if condition == "Гроза":
        return "🌩"

    if condition == "Снег":
        return "❄️"

    if condition == "Сильный снег":
        return "❄️"

    if condition == "Туман":
        return "🌫️"

    if condition == "Дымка":
        return "🌫️"

    return "🌤️"

print("\nТЕСТ ИКОНОК:")

test_icons = [
    ("Ясно", False),
    ("Ясно", True),
    ("Малооблачно", False),
    ("Малооблачно", True),
    ("Облачно", False),
    ("Небольшой дождь", False),
    ("Дождь", False),
    ("Гроза", False),
    ("Снег", False),
    ("Туман", False),
]

for condition, is_night in test_icons:
    print(
        condition,
        "ночь" if is_night else "день",
        "→",
        get_weather_icon(condition, is_night)
    )

def get_period_weather(forecast):
    periods = {
        "Утром": (6, 9),
        "Днём": (10, 13),
        "Вечером": (18, 21),
        "Ночью": (0, 5),
    }

    result = []

    for period_name, (start_hour, end_hour) in periods.items():
        period_hours = []

        for hour in forecast["hourly"]:
            hour_number = int(hour["time"][11:13])

            if start_hour <= hour_number <= end_hour:
                period_hours.append(hour)

        if not period_hours:
            continue

        middle_hour = period_hours[len(period_hours) // 2]

        temp = middle_hour["temp_c"]

        condition = normalize_condition(
            middle_hour["condition"]
        )

        is_night = period_name == "Вечером" or period_name == "Ночью"

        weather_icon = get_weather_icon(
            condition,
            is_night
        )

        print(
            "DEBUG:",
            period_name,
            condition,
            weather_icon
        )

        result.append(
            f"{period_name} {temp:+.0f}°  {condition} {weather_icon}"
        )

    return "\n".join(result)

def get_precipitation_type(forecast, day_scenario):
    if day_scenario == "snowy":
        return "snow"

    return "rain"


def format_date_ru(date):
    months = {
        1: "января",
        2: "февраля",
        3: "марта",
        4: "апреля",
        5: "мая",
        6: "июня",
        7: "июля",
        8: "августа",
        9: "сентября",
        10: "октября",
        11: "ноября",
        12: "декабря",
    }

    date_obj = datetime.strptime(date, "%Y-%m-%d")

    return f"{date_obj.day} {months[date_obj.month]}"


def pressure_to_mmhg(pressure_mb):
    return round(pressure_mb * 0.750062)


def format_date_ru(date):
    months = {
        1: "января",
        2: "февраля",
        3: "марта",
        4: "апреля",
        5: "мая",
        6: "июня",
        7: "июля",
        8: "августа",
        9: "сентября",
        10: "октября",
        11: "ноября",
        12: "декабря",
    }

    date_obj = datetime.strptime(date, "%Y-%m-%d")

    return f"{date_obj.day} {months[date_obj.month]}"


def pressure_to_mmhg(pressure_mb):
    return round(pressure_mb * 0.750062)


def make_post(forecast):
    date = forecast["date"]
    date_text = format_date_ru(date)
    greeting_icon = random.choice(GREETING_ICONS)

    pressure = pressure_to_mmhg(
        forecast["pressure_mb"]
    )

    precipitation_type = get_precipitation_type(
        forecast,
        day_scenario
    )

    precipitation_probability = (
        forecast["chance_of_snow"]
        if precipitation_type == "snow"
        else forecast["chance_of_rain"]
    )

    precipitation_text = get_precipitation_probability_text(
        precipitation_probability,
        precipitation_type
    )

    precipitation_timing = get_precipitation_timing(
        forecast,
        precipitation_type
    )

    weather_comment = get_editorial_text(
        day_scenario,
        forecast
    )

    temp_min = forecast["temp_min"]
    temp_max = forecast["temp_max"]

    if temp_min < 5:
        clothing = "Утром понадобится тёплая куртка."
    elif temp_min < 12:
        clothing = "Утром лучше захватить лёгкую куртку или ветровку."
    elif temp_max >= 25:
        clothing = "Утром пригодится лёгкая куртка, днём можно переходить на более лёгкую одежду."
    elif temp_max >= 18:
        clothing = "Для утра лучше взять лёгкую куртку или кофту."
    else:
        clothing = "Лучше одеться потеплее."

    post = f"""Доброе утро, Звенигород! {greeting_icon}

Погода на {date_text}

{get_period_weather(forecast)}

💨 Ветер — до {forecast["max_wind"]:.0f} км/ч
💧 Влажность — {forecast["humidity"]:.0f}%
🧭 Давление — {pressure} мм рт. ст.

{weather_comment}


🌅 Восход — {format_time_24(forecast["sunrise"])}
🌇 Закат — {format_time_24(forecast["sunset"])}
"""

    return post

weather = get_weather()

forecast = normalize_weather(weather)

rain_analysis = analyze_rain(forecast)

temperature_level = get_temperature_level(
    forecast["temp_min"],
    forecast["temp_max"]
)

day_scenario = get_day_scenario(
    forecast,
    rain_analysis
)


SUNNY_WARM_TEXTS = [
    "Солнечно и тепло — до +{temp_max:.0f} °C, дождя не ожидается. Хороший день, чтобы провести побольше времени на улице.",

    "ПСолнечно, до +{temp_max:.0f} °C, без дождя. Можно смело планировать прогулку.",

    "Солнечно, тепло, сухо — до +{temp_max:.0f} °C. Если есть возможность, стоит выйти на улицу.",

    "До +{temp_max:.0f} °C и почти без дождя. Утром комфортно, днём пригодится что-то полегче. Погода почти идеальная для прогулки.",

    "Солнце сегодня в главной роли. До +{temp_max:.0f} °C, небо ясное, дождя нет. Хороший повод немного замедлиться и пройтись пешком.",
]

CLOUDY_COMFORTABLE_TEXTS = [
    "Облачно, но вполне комфортно — до +{temp_max:.0f} °C, сильного дождя не ожидается. Нормальный день для обычных дел.",

    "Солнце сегодня взяло выходной. Зато без жары и дождя — до +{temp_max:.0f} °C. Можно спокойно идти по делам.",

    "Немного серо, зато погода не подведёт. До +{temp_max:.0f} °C, без существенного дождя. Для прогулки — вполне.",

    "Облачно большую часть дня, но без хлопот — около +{temp_max:.0f} °C, осадков почти нет. Лёгкая куртка — и вперёд.",

    "Не самый солнечный день, зато удобный. До +{temp_max:.0f} °C, сильного дождя нет. Можно не менять планы.",
]

RAINY_TEXTS = [
    "Сегодня дождливо. Осадки ожидаются в течение дня, так что лучше одеться по погоде.",

    "Дождь будет, скорее всего, возвращаться несколько раз за день. Непромокаемая куртка и сухая обувь точно пригодятся.",

    "Дождь сегодня, скорее всего, продолжительный. Для долгих прогулок день не лучший. Но когда нас это останавливало, правда?",

    "Мокро и прохладно. Дождь будет идти с перерывами, поэтому лучше сразу одеться по погоде.",

    "Дождливый день. Для коротких маршрутов — терпимо, для долгих прогулок — нет. Непромокаемая куртка обязательна.",
]

SMALL_RAIN_POSSIBLE_TEXTS = [
    "Возможен небольшой дождь. В целом спокойно, но лучше иметь зонт под рукой.",

    "День без сюрпризов, но дождь всё же возможен. Если планируете долго быть на улице — лучше подстраховаться.",

    "Погода немного переменчивая. Дождь возможен, но вряд ли испортит весь день — между осадками успеть можно.",

    "Кратковременный дождь не исключён. Лёгкая куртка и зонт будут хорошим запасным вариантом.",

    "Небольшой дождь возможен, но отменять планы не нужно. Осадки, скорее всего, пройдут быстро.",
]

STRONG_WIND_TEXTS = [
    "Сегодня будет ветрено. Ветровка или куртка точно пригодятся.",

    "День обещает быть довольно ветреным. Одежду лучше выбрать такую, чтобы она хорошо защищала от ветра.",

    "Ветер сегодня — главный погодный фактор. На открытых участках будет ощущаться холоднее, чем по термометру.",

    "етрено. Для обычных дел — нормально, для долгой прогулки лучше выбрать маршрут по лесу, там меньше дует.",

    "Ветер заметно усилится. Даже при комфортной температуре пригодится одежда, которая не продувается.",
]

COLD_TEXTS = [
    "Сегодня холодно. Тёплая куртка и подходящая обувь — не опция, а необходимость.",

    "По-настоящему холодный день. На тёплое солнце рассчитывать не стоит — лучше несколько слоёв одежды.",

    "Сегодня погода заставит одеться потеплее. Холодно, особенно утром, а днём прогреется совсем немного.",

    "Прохладно весь день. Лёгкой курткой лучше не ограничиваться.",

    "Холодно, и это стоит учесть заранее. Тёплая одежда и обувь обязательны, а для прогулки лучше выбрать место без ветра.",
]

FOG_TEXTS = [
    "Утро туманное — тихое и немного влажное. К середине дня туман, скорее всего, рассеется.",

    "Утром туман и высокая влажность. На улице свежо — тёплая куртка с утра не помешает.",

    "Туманное настроение с утра: воздух влажный, видимость снижена. Днём станет заметно комфортнее.",

    "День начнётся с тумана. Прохладно, но без серьёзной непогоды. Если выходите рано — оденьтесь теплее.",

    "Утром туман добавит немного атмосферного настроения. Прохладно и влажно — тёплая одежда будет кстати.",
]

SHARP_COOLING_TEXTS = [
    "Температура заметно меняется в течение дня. Утром прохладно, днём теплее — лучше одеться слоями.",

    "Утро прохладное, но к середине дня станет теплее. Перепад заметный, так что утром не стоит выходить налегке.",

    "Погода меняется прямо на ходу: утром прохладно, днём значительно теплее. Слои одежды — лучший вариант.",

    "Утром нужна одежда потеплее, к обеду уже будет уже помягче. Температура изменится довольно сильно.",

    "Два разных настроения за один день: прохладное утро и тёплый день. Удобнее всего — одеться так, чтобы легко адаптироваться к изменениям погоды.",
]

SHARP_WARMING_TEXTS = [
    "После прохладного утра температура заметно поднимется. К середине дня станет теплее — не одевайтесь слишком тепло сразу.",

    "Утро прохладное, но воздух быстро прогреется. Многослойная одежда сегодня особенно кстати.",

    "Прохладное утро и тёплый день. Погода меняется — выбирайте одежду, которую легко адаптировать."
]

UNUSUALLY_WARM_TEXTS = [
    "Сегодня заметно теплее, чем обычно для этого времени года — до +{temp_max:.0f} °C. Го на реку.",

    "Погода решила дать жару. До +{temp_max:.0f} °C. Хороший повод провести больше времени на улице.",

    "Сегодня классно — до +{temp_max:.0f} °C. Греемся, кайфуем.",

    "Приятный сюрприз: до +{temp_max:.0f} °C. Утром прохладнее, но днём можно одеться полегче.",

    "Ну что, тепло! До +{temp_max:.0f} °C. Если есть возможность, стоит провести часть дня на улице.",
]

ORDINARY_CALM_TEXTS = [
    "Спокойная погода без сюрпризов. Комфортная температура, без дождя и сильного ветра.",

    "Обычный ровный день. Без жары, дождя и резких перемен — можно не подстраивать планы под погоду.",

    "Погода сегодня не станет темой для разговоров — и это хорошо. Спокойно, умеренно, без неприятностей.",

    "Обычный день: температура без крайностей, погода без сюрпризов. Живите по своему плану.",

    "Всё предсказуемо: умеренно, спокойно, без осадков. Можно идти по делам или выбрать время для прогулки.",
]

VERY_COLD_TEXTS = [
    "Сегодня очень холодно. Зимняя одежда обязательна — и куртка, и обувь, и всё остальное.",

    "Морозный день. Особенно холодно утром — несколько слоёв одежды точно пригодятся.",

    "Погода потребует настоящей зимней экипировки. Долгие прогулки лучше сократить.",

    "Серьёзный мороз. Лёгкой одеждой не обойтись — нужны куртка, обувь, перчатки и головной убор.",

    "Холод сегодня лучше не недооценивать. Хорошо утеплитесь и по возможности не задерживайтесь надолго на улице.",
]

def get_weather_photo(scenario):

    folder_name = PHOTO_SCENARIOS.get(
        scenario,
        "default"
    )

    folder = os.path.join(
        PHOTO_DIR,
        folder_name
    )

    if not os.path.exists(folder):
        folder = os.path.join(
            PHOTO_DIR,
            "default"
        )

    if not os.path.exists(folder):
        return None

    photos = [
        os.path.join(folder, filename)
        for filename in os.listdir(folder)
        if filename.lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp")
        )
    ]

    if not photos:
        return None

    return random.choice(photos)

def get_editorial_text(scenario, forecast):

    if scenario == "sunny_warm":
        texts = SUNNY_WARM_TEXTS

    elif scenario == "cloudy_comfortable":
        texts = CLOUDY_COMFORTABLE_TEXTS

    elif scenario == "rainy":
        texts = RAINY_TEXTS

    elif scenario == "small_rain_possible":
        texts = SMALL_RAIN_POSSIBLE_TEXTS

    elif scenario == "strong_wind":
        texts = STRONG_WIND_TEXTS

    elif scenario == "cold":
        texts = COLD_TEXTS

    elif scenario == "fog":
        texts = FOG_TEXTS

    elif scenario == "sharp_cooling":
        texts = SHARP_COOLING_TEXTS
    elif scenario == "sharp_warming":
        texts = SHARP_WARMING_TEXTS

    elif scenario == "unusually_warm":
        texts = UNUSUALLY_WARM_TEXTS

    elif scenario == "ordinary_calm":
        texts = ORDINARY_CALM_TEXTS

    elif scenario == "very_cold":
        texts = VERY_COLD_TEXTS

    else:
        return ""

    text = random.choice(texts)

    return text.format(
        temp_max=forecast["temp_max"]
    )



editorial_text = get_editorial_text(
    day_scenario,
    forecast
)

post = make_post(forecast)

print("\nПОГОДА ПО ВРЕМЕНИ СУТОК:")
print(get_period_weather(forecast))

print("\n" + "=" * 60)

print("\n" + "=" * 60)
print("ТЕСТ ВЫБОРА СЦЕНАРИЕВ")
print("=" * 60)

test_conditions = [
    {
        "name": "Солнечно и тепло",
        "chance_of_rain": 5,
        "chance_of_snow": 0,
        "max_wind": 15,
        "humidity": 40,
        "temp_min": 12,
        "temp_max": 22,
        "condition": "Солнечно",
        "hourly": [],
    },
    {
        "name": "Облачно и комфортно",
        "chance_of_rain": 10,
        "chance_of_snow": 0,
        "max_wind": 15,
        "humidity": 60,
        "temp_min": 10,
        "temp_max": 18,
        "condition": "Облачно",
        "hourly": [],
    },
    {
        "name": "Дождливый день",
        "chance_of_rain": 80,
        "chance_of_snow": 0,
        "max_wind": 15,
        "humidity": 80,
        "temp_min": 10,
        "temp_max": 15,
        "condition": "Дождь",
        "hourly": [],
    },
    {
        "name": "Возможен небольшой дождь",
        "chance_of_rain": 40,
        "chance_of_snow": 0,
        "max_wind": 15,
        "humidity": 70,
        "temp_min": 10,
        "temp_max": 18,
        "condition": "Облачно",
        "hourly": [],
    },
    {
        "name": "Сильный ветер",
        "chance_of_rain": 10,
        "chance_of_snow": 0,
        "max_wind": 35,
        "humidity": 60,
        "temp_min": 10,
        "temp_max": 18,
        "condition": "Облачно",
        "hourly": [],
    },
    {
        "name": "Холодно",
        "chance_of_rain": 10,
        "chance_of_snow": 0,
        "max_wind": 10,
        "humidity": 60,
        "temp_min": 0,
        "temp_max": 3,
        "condition": "Облачно",
        "hourly": [],
    },
    {
        "name": "Туман",
        "chance_of_rain": 10,
        "chance_of_snow": 0,
        "max_wind": 5,
        "humidity": 95,
        "temp_min": 5,
        "temp_max": 12,
        "condition": "Туман",
        "hourly": [],
    },
    {
        "name": "Необычно тепло",
        "chance_of_rain": 10,
        "chance_of_snow": 0,
        "max_wind": 10,
        "humidity": 50,
        "temp_min": 18,
        "temp_max": 31,
        "condition": "Облачно",
        "hourly": [],
    },
    {
    "name": "Резкое похолодание",
    "chance_of_rain": 0,
    "chance_of_snow": 0,
    "max_wind": 10,
    "humidity": 60,
    "temp_min": -6,
    "temp_max": 12,
    "condition": "Облачно",
    "hourly": [
        {"time": "2026-09-09 09:00", "temp_c": 12, "precip_mm": 0},
        {"time": "2026-09-09 12:00", "temp_c": 5, "precip_mm": 0},
        {"time": "2026-09-09 15:00", "temp_c": -4, "precip_mm": 0},
        {"time": "2026-09-09 18:00", "temp_c": -6, "precip_mm": 0},
    ],
    },
    {
    "name": "Резкое потепление",
    "chance_of_rain": 0,
    "chance_of_snow": 0,
    "max_wind": 10,
    "humidity": 60,
    "temp_min": -5,
    "temp_max": 13,
    "condition": "Облачно",
    "hourly": [
        {"time": "2026-09-09 09:00", "temp_c": -5, "precip_mm": 0},
        {"time": "2026-09-09 12:00", "temp_c": 2, "precip_mm": 0},
        {"time": "2026-09-09 15:00", "temp_c": 11, "precip_mm": 0},
        {"time": "2026-09-09 18:00", "temp_c": 13, "precip_mm": 0},
    ],
    },
    {
        "name": "Обычный спокойный день",
        "chance_of_rain": 10,
        "chance_of_snow": 0,
        "max_wind": 15,
        "humidity": 60,
        "temp_min": 8,
        "temp_max": 15,
        "condition": "Пасмурно",
        "hourly": [],
    },
    {
        "name": "Очень холодно",
        "chance_of_rain": 0,
        "chance_of_snow": 0,
        "max_wind": 10,
        "humidity": 60,
        "temp_min": -15,
        "temp_max": -11,
        "condition": "Ясно",
        "hourly": [],
    },
    {
        "name": "Снег при -12 °C",
        "chance_of_rain": 80,
        "chance_of_snow": 0,
        "max_wind": 15,
        "humidity": 80,
        "temp_min": -15,
        "temp_max": -12,
        "condition": "Дождь",
        "hourly": [],
    },
    {
        "name": "Снег при -3 °C",
        "chance_of_rain": 60,
        "chance_of_snow": 0,
        "max_wind": 15,
        "humidity": 80,
        "temp_min": -5,
        "temp_max": -3,
        "condition": "Дождь",
        "hourly": [],
    },
    {
        "name": "Холод + сильный ветер",
        "chance_of_rain": 0,
        "chance_of_snow": 0,
        "max_wind": 35,
        "humidity": 60,
        "temp_min": -1,
        "temp_max": 2,
        "condition": "Облачно",
        "hourly": [],
    },
]


print("\n" + "=" * 60)
print("ТЕСТ ПОЧАСОВЫХ ОСАДКОВ")
print("=" * 60)

precipitation_tests = [
    {
        "name": "Кратковременный дождь днём",
        "precipitation_type": "rain",
        "hourly": [
            {
                "time": "2026-09-11 12:00",
                "precip_mm": 0.3,
                "chance_of_rain": 60,
                "will_it_rain": 1,
                "chance_of_snow": 0,
                "will_it_snow": 0,
            },
        ],
    },
    {
        "name": "Дождь утром и вечером",
        "precipitation_type": "rain",
        "hourly": [
            {
                "time": "2026-09-11 08:00",
                "precip_mm": 0.3,
                "chance_of_rain": 60,
                "will_it_rain": 1,
                "chance_of_snow": 0,
                "will_it_snow": 0,
            },
            {
                "time": "2026-09-11 20:00",
                "precip_mm": 0.3,
                "chance_of_rain": 60,
                "will_it_rain": 1,
                "chance_of_snow": 0,
                "will_it_snow": 0,
            },
        ],
    },
    {
        "name": "Дождь после обеда и вечером",
        "precipitation_type": "rain",
        "hourly": [
            {
                "time": "2026-09-11 15:00",
                "precip_mm": 0.3,
                "chance_of_rain": 60,
                "will_it_rain": 1,
                "chance_of_snow": 0,
                "will_it_snow": 0,
            },
            {
                "time": "2026-09-11 20:00",
                "precip_mm": 0.3,
                "chance_of_rain": 60,
                "will_it_rain": 1,
                "chance_of_snow": 0,
                "will_it_snow": 0,
            },
        ],
    },
    {
        "name": "Снег утром и вечером",
        "precipitation_type": "snow",
        "hourly": [
            {
                "time": "2026-09-11 08:00",
                "precip_mm": 0.3,
                "chance_of_rain": 0,
                "will_it_rain": 0,
                "chance_of_snow": 70,
                "will_it_snow": 1,
            },
            {
                "time": "2026-09-11 20:00",
                "precip_mm": 0.3,
                "chance_of_rain": 0,
                "will_it_rain": 0,
                "chance_of_snow": 70,
                "will_it_snow": 1,
            },
        ],
    },
]

for test in precipitation_tests:
    timing = get_precipitation_timing(
        {
            "hourly": test["hourly"]
        },
        test["precipitation_type"]
    )

    print(f"\n{test['name']}:")
    print(timing)

for test in test_conditions:
    scenario = get_day_scenario(test, {})

    print(f"{test['name']}: {scenario}")

    import asyncio

async def send_post():

    photo_path = get_weather_photo(
        day_scenario
    )

    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:

        if photo_path:

            with open(photo_path, "rb") as photo:

                await bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=photo,
                    caption=post
                )

        else:

            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=post
            )


asyncio.run(send_post())