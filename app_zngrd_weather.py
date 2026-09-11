import os
import asyncio
import urllib.parse
import urllib.request
import json
from datetime import datetime

from telegram import Bot


TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
WEATHER_API_KEY = os.environ["WEATHER_API_KEY"]

CHANNEL_ID = -1004382412226
# Звенигород, Московская область
CITY = "Звенигород"
LOCATION = "55.7352,36.8553"

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

    post = f"""Доброе утро, Звенигород! ☀️

**Погода на** {date_text}

🌡 От +{temp_min:.0f} до +{temp_max:.0f} °C
☔ {precipitation_text}
     **{precipitation_timing}**
💨 Ветер — до {forecast["max_wind"]:.0f} км/ч
💧 Влажность — {forecast["humidity"]:.0f}%
🧭 Давление — {pressure} мм рт. ст.

{weather_comment}

{clothing}

🌅 Восход — {forecast["sunrise"]}
🌇 Закат — {forecast["sunset"]}
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
    "Сегодня Звенигород встречает нас солнцем и настоящим теплом. Днём воздух прогреется почти до +{temp_max:.0f} °C, дождя практически не ожидается. Отличный день, чтобы больше времени провести на улице.",

    "Похоже, сегодня лето решило задержаться. С утра солнечно, днём до +{temp_max:.0f} °C, дождя не ожидается. Можно спокойно планировать прогулку, дела на свежем воздухе или просто выбрать маршрут подлиннее.",

    "Сегодня тот самый день, когда Звенигород особенно хорош для прогулок. Солнечно, тепло, сухо — днём температура поднимется до +{temp_max:.0f} °C. Если есть возможность, стоит провести хотя бы часть дня на улице.",

    "День обещает быть солнечным и тёплым: до +{temp_max:.0f} °C и практически без дождя. Утро ещё довольно комфортное, а днём понадобится лёгкая одежда. Для прогулок погода практически идеальная.",

    "Солнце сегодня будет главным героем дня. Воздух прогреется до +{temp_max:.0f} °C, небо останется ясным, а дождя можно не ждать. Хороший повод немного замедлиться и погулять по Звенигороду.",
]

CLOUDY_COMFORTABLE_TEXTS = [
    "Сегодня в Звенигороде будет облачно, но вполне комфортно. Днём воздух прогреется до +{temp_max:.0f} °C, сильного дождя не ожидается. Хорошая погода для обычных городских дел и прогулки.",

    "Солнце сегодня, похоже, возьмёт выходной. Небо будет облачным, зато без жары и серьёзных осадков — днём до +{temp_max:.0f} °C. Можно спокойно отправляться по делам или пройтись по городу.",

    "Звенигород сегодня будет немного спокойнее и серее обычного, зато погода останется комфортной. Температура поднимется до +{temp_max:.0f} °C, существенного дождя не ожидается. Для прогулки — вполне подходящий день.",

    "Облака будут держаться большую часть дня, но погода не должна доставить хлопот. Днём около +{temp_max:.0f} °C, без заметных осадков. Лёгкая куртка — и можно отправляться по своим делам.",

    "Не самый солнечный день, зато очень удобный для жизни в городе. Воздух прогреется до +{temp_max:.0f} °C, сильного дождя не ожидается. Самое время пройтись по Звенигороду без спешки.",
]

RAINY_TEXTS = [
    "Сегодня в Звенигороде будет дождливо. Дождь ожидается в течение заметной части дня, поэтому прогулку лучше планировать с учётом погоды. На улице будет свежо и влажно.",

    "Звенигород сегодня встретит нас дождём. Осадки будут время от времени возвращаться в течение дня, так что сухая обувь и непромокаемая куртка точно пригодятся.",

    "Сегодня тот случай, когда погода предлагает немного сбавить темп. В Звенигороде ожидается дождь, местами довольно продолжительный. Для долгих прогулок день не самый подходящий, зато для спокойных городских дел — вполне.",

    "День обещает быть мокрым и прохладным. Дождь будет идти с перерывами или затронет большую часть дня, поэтому лучше сразу одеться по погоде и не рассчитывать на длительные сухие окна.",

    "Сегодня Звенигород будет под дождём. Погода скорее для коротких маршрутов и дел по городу, чем для долгих прогулок. Непромокаемая куртка и обувь сегодня будут особенно кстати.",
]

SMALL_RAIN_POSSIBLE_TEXTS = [
    "Сегодня в Звенигороде возможен небольшой дождь. В целом день обещает быть спокойным, но погода может ненадолго испортиться. Лучше иметь под рукой небольшой зонт.",

    "День начинается без особых сюрпризов, но дождь время от времени всё же возможен. Если планируете долго быть на улице, лучше предусмотреть защиту от осадков.",

    "Сегодня погода будет немного переменчивой. Дождь возможен, но вряд ли станет главным событием дня. Между осадками вполне можно успеть погулять и сделать всё запланированное.",

    "В Звенигороде сегодня возможен кратковременный дождь. Погода скорее требует небольшой готовности, чем серьёзных планов на непогоду: лёгкая куртка и зонт будут хорошим запасным вариантом.",

    "Сегодня стоит быть готовыми к небольшому дождю, но отменять планы из-за него не обязательно. Осадки могут пройти быстро, а остальная часть дня останется вполне подходящей для обычных дел и прогулок.",
]

STRONG_WIND_TEXTS = [
    "Сегодня в Звенигороде будет ветрено. Порывы особенно хорошо почувствуются на открытых местах, поэтому лёгкая куртка или ветровка сегодня будет кстати.",

    "День обещает быть довольно ветреным. На улицах ветер будет заметно ощущаться, особенно утром и на открытых пространствах. Одежду лучше выбрать такую, чтобы она хорошо защищала от ветра.",

    "Сегодня ветер станет главным погодным фактором. Температура может казаться ниже фактической, особенно на открытых участках. Для прогулки лучше выбрать непродуваемую куртку.",

    "В Звенигороде сегодня свежо и ветрено. Погода вполне подходит для обычных дел, но долгую прогулку лучше планировать без открытых и продуваемых маршрутов.",

    "Сегодня воздух будет постоянно в движении. Ветер заметно усилится, особенно на открытых местах, поэтому даже при вполне комфортной температуре пригодится одежда, защищающая от ветра.",
]

COLD_TEXTS = [
    "Сегодня в Звенигороде будет холодно. Температура останется низкой в течение дня, поэтому тёплая куртка и подходящая обувь точно пригодятся. Для долгих прогулок лучше выбрать хорошо защищённый от холода маршрут.",

    "День обещает быть по-настоящему холодным. На улице лучше не рассчитывать на тёплое солнце — пригодятся несколько слоёв одежды и тёплая куртка.",

    "Сегодня погода заставит одеться потеплее. В Звенигороде будет холодно, особенно утром, а днём воздух прогреется совсем немного. Для прогулки лучше выбрать тёплую одежду и не задерживаться надолго на открытом ветру.",

    "Звенигород сегодня встретит нас холодной погодой. Температура будет держаться на низком уровне, поэтому лёгкой курткой лучше не ограничиваться. Самое время достать тёплую одежду.",

    "Сегодня тот самый день, когда тепло становится особенно ценным. На улице холодно, поэтому стоит одеться с запасом и не забыть про тёплую обувь. Если планируете прогулку, выбирайте защищённые от ветра места.",
]

FOG_TEXTS = [
    "Сегодня Звенигород будет окутан туманом. Утро получится тихим и немного загадочным, а воздух — прохладным и влажным. К середине дня туман, скорее всего, начнёт рассеиваться.",

    "Утро в Звенигороде сегодня встретит туманом. Из-за высокой влажности на улице будет особенно свежо, поэтому тёплая куртка утром точно не помешает.",

    "Сегодня у Звенигорода будет немного туманное настроение. Воздух влажный, видимость местами может быть снижена, а утро получится прохладным. Днём станет заметно комфортнее.",

    "День начнётся с тумана и влажного воздуха. В Звенигороде сегодня прохладно, но без серьёзной непогоды. Если выходите рано утром, лучше одеться потеплее.",

    "Сегодня утром Звенигород может выглядеть совсем иначе — туман скроет привычные детали и добавит городу немного атмосферы. На улице прохладно и влажно, поэтому утром пригодится тёплая одежда.",
]

SHARP_COOLING_TEXTS = [
    "Сегодня в Звенигороде температура заметно изменится в течение дня. Утро будет прохладным, а днём воздух прогреется сильнее. Лучше выбрать одежду, которую можно легко снять или добавить по ходу дня.",

    "День начнётся прохладно, но постепенно станет теплее. Перепад температуры будет довольно заметным, поэтому утром не стоит выходить налегке — днём лишний слой одежды уже может не понадобиться.",

    "Сегодня погода будет меняться прямо на глазах. Утром в Звенигороде прохладно, зато днём температура ощутимо поднимется. Самый удобный вариант — одеться слоями.",

    "Утро сегодня потребует тёплой одежды, но к середине дня станет заметно мягче. Температура изменится достаточно сильно, поэтому гардероб лучше подобрать с учётом обеих частей дня.",

    "Сегодня у погоды два разных настроения: прохладное утро и значительно более тёплый день. Если предстоит провести на улице несколько часов, лучше предусмотреть возможность быстро адаптироваться к температуре.",
]

SHARP_WARMING_TEXTS = [
    "После прохладного утра температура заметно пойдёт вверх. К середине дня станет значительно теплее, поэтому лучше сразу учитывать перемену погоды и не одеваться слишком тепло.",
    "День начнётся прохладно, но затем воздух быстро прогреется. Температура заметно изменится в течение дня, так что многослойная одежда сегодня будет особенно кстати.",
    "Утро встретит прохладой, зато днём станет ощутимо теплее. Погода будет меняться на ходу, поэтому лучше выбрать одежду, которую легко адаптировать к температуре."
]

UNUSUALLY_WARM_TEXTS = [
    "Сегодня в Звенигороде будет заметно теплее, чем обычно для этого времени года. Днём воздух прогреется до +{temp_max:.0f} °C, так что тёплую одежду сегодня можно отложить.",

    "Похоже, погода решила немного продлить тёплый сезон. Сегодня температура поднимется до +{temp_max:.0f} °C — для этого времени года это заметно выше привычного. Можно смело планировать больше времени на улице.",

    "Сегодня Звенигород порадует необычным для сезона теплом. Днём до +{temp_max:.0f} °C, поэтому тяжёлая одежда точно не понадобится. Хороший повод воспользоваться тёплым днём по максимуму.",

    "Температура сегодня приятно удивит: воздух прогреется до +{temp_max:.0f} °C, что заметно теплее обычного для этого времени года. Утром прохладнее, но днём можно будет одеться значительно легче.",

    "Сегодня погода даст нам ещё один шанс почувствовать почти летнее тепло. До +{temp_max:.0f} °C днём — для сезона это необычно много. Если есть возможность, стоит провести часть дня на улице.",
]

ORDINARY_CALM_TEXTS = [
    "Сегодня в Звенигороде спокойная погода без заметных сюрпризов. Температура будет комфортной для обычных дел, а существенных осадков или сильного ветра не ожидается.",

    "День обещает быть вполне спокойным. Без жары, сильного дождя и резких перемен — можно просто заниматься своими делами и не подстраивать планы под погоду.",

    "Сегодня погода не станет главным событием дня — и это, пожалуй, хорошо. В Звенигороде спокойно и умеренно, без серьёзных осадков и сильного ветра.",

    "Обычный спокойный день в Звенигороде. Температура без крайностей, погода без неприятных сюрпризов. Хороший вариант просто жить по своему плану.",

    "Сегодня всё довольно предсказуемо: умеренная температура, спокойный ветер и без существенных осадков. Можно спокойно отправляться по делам или выбрать время для прогулки.",
]

VERY_COLD_TEXTS = [
    "Сегодня в Звенигороде очень холодно. Температура опустится значительно ниже нуля, поэтому тёплая зимняя одежда и хорошая защита от холода обязательны.",

    "День будет морозным. На улице очень холодно, особенно утром, поэтому лучше одеться с запасом: тёплая куртка, обувь и несколько слоёв одежды сегодня действительно пригодятся.",

    "Сегодня погода потребует настоящей зимней экипировки. В Звенигороде сильный холод, поэтому долгие прогулки лучше сократить, а на улицу выходить хорошо утеплённым.",

    "Звенигород сегодня встретит серьёзным морозом. Лёгкой одеждой точно не обойтись — пригодятся тёплая куртка, обувь, перчатки и головной убор.",

    "Сегодня тот случай, когда холод лучше не недооценивать. Температура будет очень низкой, поэтому стоит хорошо утеплиться и по возможности не планировать долгое пребывание на улице.",
]

def get_editorial_text(scenario, forecast):
    date = datetime.strptime(
        forecast["date"],
        "%Y-%m-%d"
    )

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

    variant_index = date.timetuple().tm_yday % len(texts)

    text = texts[variant_index]

    return text.format(
        temp_max=forecast["temp_max"]
    )

    return ""

editorial_text = get_editorial_text(
    day_scenario,
    forecast
)

post = make_post(forecast)

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
    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=post
        )

asyncio.run(send_post())