"""Deterministic, offline rendering of resolved Editorial Contract 1.1 data."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import math
import re

from weather_logic import Forecast, Period, Precipitation
from weather_conditions import PRECIPITATION_LABELS as PHASE_NAMES

LIMIT = 1024
COMMENT_LIMIT = 180
LABELS = {'morning': 'Утро', 'day': 'День', 'evening': 'Вечер', 'night': 'Ночь'}
ADVERBS = {'morning': 'Утром', 'day': 'Днём', 'evening': 'Вечером', 'night': 'Ближайшей ночью'}
MONTHS = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
          'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря')
WARNING_NAMES = {
    'freezing_rain': 'ледяной дождь', 'freezing_drizzle': 'замерзающая морось',
    'heavy_snow': 'сильный снег', 'heavy_rain': 'сильный дождь',
    'thunder': 'гроза', 'blizzard': 'метель', 'blowing_snow': 'перенос снега ветром',
    'freezing_fog': 'замерзающий туман', 'ice_pellets': 'ледяная крупа',
    'dust_storm': 'пыльная буря', 'sandstorm': 'песчаная буря',
}
FEMININE = {'freezing_drizzle', 'thunder', 'blizzard', 'ice_pellets', 'dust_storm', 'sandstorm'}
CATEGORY_NAMES = {
    'clear': 'ясно', 'partly_cloudy': 'переменная облачность', 'cloudy': 'облачно',
    'overcast': 'пасмурно', 'mist': 'дымка', 'fog': 'туман', 'haze': 'мгла',
    'dust_haze': 'пыльная мгла', 'blowing_dust': 'перенос пыли ветром',
    'smoke': 'дым', 'smoky_haze': 'дымная мгла', 'smog': 'смог',
    'saharan_dust': 'сахарская пыль', 'dust': 'пыль',
}



class RenderingBlocked(ValueError):
    def __init__(self, code, blockers=()):
        self.code = code
        self.blockers = tuple(blockers)
        super().__init__(code)


@dataclass(frozen=True)
class Ancillary:
    humidity: float | None = None
    pressure_mb: float | None = None
    sunrise: str | None = None  # validated HH:MM
    sunset: str | None = None


@dataclass(frozen=True)
class RenderedForecast:
    period_lines: tuple[str, ...]
    comment: str
    text: str
    mandatory_warnings: tuple[tuple[str, str], ...]  # period, kind
    compact: bool


def utf16_length(text):
    return len(text.encode('utf-16-le')) // 2


def rounded(value):
    return int(Decimal(str(value)).to_integral_value(rounding=ROUND_HALF_UP))


def _signed(value):
    return f'{value:+d}' if value else '0'


def _temperature(period):
    value = period.temperature
    if value.mode == 'range':
        return f'{_signed(value.rounded_minimum)}…{_signed(value.rounded_maximum)}°'
    if value.mode == 'representative':
        return f'{_signed(value.representative)}°'
    return '—'


def _resolved(forecast):
    blockers = set(forecast.unresolved_rules)
    for period in forecast.periods:
        blockers.update(period.unresolved_rules)
        for item in period.precipitation:
            blockers.update(item.unresolved_rules)
            if item.unresolved_hours:
                blockers.add('UNRESOLVED_PRECIPITATION')
        for item in period.hours:
            blockers.update(item.unresolved_rules)
            if item.likelihood == 'unresolved':
                blockers.add('UNRESOLVED_HOUR')
        if any(hazard.likelihood == 'unresolved' for hazard in period.hazards):
            blockers.add('UNRESOLVED_HAZARD')
    if blockers:
        raise RenderingBlocked('UNRESOLVED_RULES', sorted(blockers))


def _warning_phrase(kind, possible):
    if kind not in WARNING_NAMES:
        raise RenderingBlocked('UNKNOWN_HAZARD')
    text = WARNING_NAMES[kind]
    if possible:
        return ('возможна ' if kind in FEMININE else 'возможен ') + text
    return text


def _warnings(period):
    result = []
    for kind in WARNING_NAMES:  # fixed editorial priority; preserve every kind
        evidence = [item for item in period.hazards if item.kind == kind]
        if evidence:
            possible = not any(item.likelihood == 'expected' for item in evidence)
            result.append((kind, _warning_phrase(kind, possible)))
    if any(item.kind not in WARNING_NAMES for item in period.hazards):
        raise RenderingBlocked('UNKNOWN_HAZARD')
    return result


def _possible(kind):
    return 'возможны ' if kind == 'unknown' else 'возможна ' if kind in ('freezing_drizzle', 'ice_pellets') else 'возможен '


def _precipitation_phrase(item: Precipitation):
    if item.kind not in PHASE_NAMES:
        raise RenderingBlocked('UNSUPPORTED_PRECIPITATION_KIND')
    generic, light, heavy, _ = PHASE_NAMES[item.kind]
    if item.expected_hours == 0:
        return _possible(item.kind) + generic
    noun = (heavy if item.predominant_intensity == 'heavy' else
            light if item.predominant_intensity == 'light' else generic)
    if item.predominant_intensity == 'moderate_or_heavy' and item.kind in ('rain', 'snow', 'sleet', 'ice_pellets'):
        noun = ('умеренная или сильная ' if item.kind == 'ice_pellets' else 'умеренный или сильный ') + generic
    prefix = {'brief': 'кратковременно ', 'intermittent': '', 'prolonged': 'продолжительный '}.get(item.duration, '')
    if item.kind in ('freezing_drizzle', 'ice_pellets') and prefix == 'продолжительный ':
        prefix = 'продолжительная '
    phrase = prefix + noun
    if item.duration == 'intermittent':
        phrase += ' временами'
    if item.possible_hours:
        phrase += '; в другие часы ' + _possible(item.kind) + generic
    return phrase


def _hazard_timing(period, kind):
    times = sorted({item.time for item in period.hazards if item.kind == kind})
    if not times:
        return ''
    # Preserve distinct episodes and actual hours; do not bridge a dry gap.
    groups = []
    for time in times:
        if groups and (time - groups[-1][-1]).total_seconds() == 3600:
            groups[-1].append(time)
        else:
            groups.append([time])
    return ' в ' + ', '.join(group[0].strftime('%H:%M') if len(group) == 1 else
                              group[0].strftime('%H:%M') + '–' + group[-1].strftime('%H:%M')
                              for group in groups)


def _sky(period):
    if period.condition_count < 4:
        return 'погодные условия не уточнены'
    if period.predominant in CATEGORY_NAMES:
        return CATEGORY_NAMES[period.predominant]
    if period.predominant in PHASE_NAMES or period.predominant in WARNING_NAMES:
        return ''
    if period.predominant and any(item.condition.category == period.predominant
                                  and item.condition.precipitation is not None for item in period.hours):
        return ''
    categories = [run.kind for run in period.category_runs if run.kind in CATEGORY_NAMES]
    if len(categories) == 2:
        return CATEGORY_NAMES[categories[0]] + ', затем ' + CATEGORY_NAMES[categories[1]]
    unique = list(dict.fromkeys(categories))
    if unique:
        return ' / '.join(CATEGORY_NAMES[item] for item in unique)
    return 'погодные условия не уточнены'


def _compact_body(period, events, warnings):
    if not warnings:
        return '; '.join(_precipitation_phrase(item) for item in events) or _sky(period)
    # Group shared clocks and probability qualifiers instead of repeating each
    # hazard sentence. Keep every hazard name and its source hour(s).
    parts = []
    for likelihood, qualifier in (('expected', 'ожидаются: '), ('possible', 'возможны: ')):
        by_time = {}
        for hazard in period.hazards:
            if hazard.likelihood == likelihood:
                by_time.setdefault(hazard.time, set()).add(hazard.kind)
        groups = []
        for time, kinds in sorted(by_time.items()):
            ordered = tuple(kind for kind in WARNING_NAMES if kind in kinds)
            if groups and groups[-1][1] == ordered and (time - groups[-1][0][-1]).total_seconds() == 3600:
                groups[-1][0].append(time)
            else:
                groups.append(([time], ordered))
        phrases = []
        for times, kinds in groups:
            clock = times[0].strftime('%H:%M')
            if len(times) > 1:
                clock += '–' + times[-1].strftime('%H:%M')
            names = ', '.join(WARNING_NAMES[kind] for kind in kinds)
            # Only confirmed precipitation may be assigned a brief duration.
            brief = likelihood == 'expected' and period.condition_count == 6 and len(times) <= 2 and any(
                kind in ('heavy_snow', 'heavy_rain', 'freezing_rain', 'freezing_drizzle') for kind in kinds)
            phrases.append(clock + ' ' + ('кратковременно ' if brief else '') + names)
        if phrases:
            parts.append(qualifier + '; '.join(phrases))
    covered = {kind for kind, _ in warnings}
    phase_hazard = {'rain':'heavy_rain','snow':'heavy_snow','freezing_rain':'freezing_rain',
                    'freezing_drizzle':'freezing_drizzle','ice_pellets':'ice_pellets'}
    for event in events:
        if phase_hazard.get(event.kind) not in covered:
            parts.append(_precipitation_phrase(event))
        elif event.expected_hours and not any(h.likelihood == 'expected' and h.kind == phase_hazard.get(event.kind)
                                              for h in period.hazards):
            # Preserve confirmed ordinary precipitation separately from a merely
            # possible stronger hazard. Use the generic phase, never a tie winner.
            prefix = 'кратковременно ' if event.duration == 'brief' else 'временами ' if event.duration == 'intermittent' else ''
            parts.append(prefix + PHASE_NAMES[event.kind][0])
    return '; '.join(parts)


def render_period(period: Period, *, compact=False):
    if period.unresolved_rules or any(item.unresolved_rules for item in period.hours):
        raise RenderingBlocked('UNRESOLVED_RULES', period.unresolved_rules)
    label = LABELS[period.name]
    if period.name == 'night':
        label += ' ' + period.start.strftime('%d.%m')
    warnings = _warnings(period)
    if period.time_count < 4:
        text = label + ': данных недостаточно'
        if warnings:
            text += '; ' + '; '.join(phrase + ' в доступные часы' for _, phrase in warnings) + ' ⚠️'
        else:
            text += ' ❔'
        if period.time_count:
            text += f' [{period.time_count}/6 ч]'
        return text

    events = sorted(period.precipitation,
                    key=lambda item: item.episodes[0].start if item.episodes else period.end)
    sky = _sky(period)
    pieces = [] if compact and (events or warnings) else ([sky] if sky else [])
    pieces.extend(_precipitation_phrase(item) for item in events)
    joined = '; '.join(pieces)
    for kind, phrase in warnings:
        # A possible hazard must not lose its qualifier just because an
        # ambiguous source phrase already contains the hazard's noun.
        possible = phrase.startswith(('возможен ', 'возможна '))
        if (phrase if possible else WARNING_NAMES[kind]) not in joined:
            if kind in ('heavy_snow', 'heavy_rain'):
                phrase += _hazard_timing(period, kind)
            pieces.append(phrase)
    body = _compact_body(period, events, warnings) if compact else '; '.join(pieces) or 'погодные условия не уточнены'
    if warnings:
        icon = '⚠️'
    elif events:
        event = events[0]
        matching = [item.condition for item in period.hours
                    if item.condition.precipitation == event.kind
                    and (event.predominant_intensity is None or item.intensity == event.predominant_intensity)]
        icons = {item.emoji(period.is_day) for item in matching}
        icon = next(iter(icons)) if len(icons) == 1 else PHASE_NAMES[event.kind][3]
        if period.condition_count == 0:
            icon = '❔'
    elif period.predominant:
        candidates = [item.condition for item in period.hours if item.condition.category == period.predominant]
        icon = candidates[0].emoji(period.is_day) if candidates else None
    else:
        icon = '❔'
    # Heavy snowfall is already explicit and does not require a generic warning
    # glyph in addition to the contract's snowfall icon.
    if warnings and all(kind == 'heavy_snow' for kind, _ in warnings):
        icon = '❄️'
    text = f'{label}: {_temperature(period)} · {body}' + (f' {icon}' if icon else '')
    if period.temperature.mode == 'unavailable':
        text += ' (температура не уточнена)'
    elif period.temperature.count < period.time_count:
        text += f' [температура: {period.temperature.count}/{period.time_count} ч]'
    if period.time_count < 6:
        text += f' [{period.time_count}/6 ч]'
    elif period.condition_count < 6 and period.condition_count > 0:
        text += (f' [{period.condition_count}/6 ч]' if compact else f' [условия: {period.condition_count}/6 ч]')
    return text


def clothing_advice(period):
    """Contract §6: factors coincide in source hours; no inferred feels-like.

    Returns wording with an explicit clock qualifier for a one-hour episode.
    Umbrella advice is handled by the rain comment, not a temperature threshold.
    """
    candidates = []
    for item in period.hours:
        hour = item.hour
        freezing = ((hour.temp_c is not None and hour.temp_c <= 0)
                    or (hour.feelslike_c is not None and hour.feelslike_c <= 0))
        cool = (hour.temp_c is not None and hour.feelslike_c is not None
                and hour.temp_c <= 8 and hour.feelslike_c <= 5)
        cold = freezing or cool
        wind = (hour.wind_kph or 0) >= 20
        gust = (hour.gust_kph or 0) >= 30
        strong_gust = (hour.gust_kph or 0) >= 40
        wet = item.precipitation in ('rain', 'freezing_rain', 'freezing_drizzle') and item.likelihood in ('expected', 'possible')
        choices = (
            (cold and wet and (wind or gust), 0, 'пригодится тёплая непромокаемая одежда с капюшоном'),
            (cold and (wind or strong_gust), 1, 'пригодится тёплая непродуваемая одежда'),
            (wet and (wind or gust), 2, 'пригодится защита от дождя с капюшоном'),
            (freezing, 3, 'пригодится тёплая одежда'),
            (cool, 4, 'пригодится тёплый дополнительный слой'),
        )
        candidates.extend((key, hour.time, text) for allowed, key, text in choices if allowed)
    # Prefer a supported general recommendation over a more severe isolated hour.
    for key in range(5):
        matching = sorted((time, text) for rank, time, text in candidates if rank == key)
        for first, second in zip(matching, matching[1:]):
            if (second[0] - first[0]).total_seconds() == 3600:
                return first[1]
    if candidates:
        _, time, text = min(candidates)
        return 'в ' + time.strftime('%H:%M') + ' ' + text
    return None


def _with_advice(base, period, *, umbrella=False, separator=', '):
    advice = clothing_advice(period)
    if advice is None and umbrella:
        advice = 'зонт может пригодиться'
    result = base + separator + advice if advice else base
    return result if utf16_length(result) <= COMMENT_LIMIT else base


def _wind_comment(period):
    rain = any(item.precipitation == 'rain' and item.likelihood == 'expected' for item in period.hours)
    base = 'Сильный ветер' if period.wind.speed_level == 'high' else 'Сильные порывы'
    if rain:
        base += ' и дождь'
    if period.felt_colder_episodes:
        return _with_advice(base + ', по ощущениям холоднее', period, separator='; ')
    return _with_advice(base, period)


def _event_comment(period, event, likelihood):
    kind = event.kind
    prefix = ADVERBS[period.name]
    if kind == 'rain' and likelihood == 'expected' and event.duration == 'brief':
        phrase = prefix + ' кратковременный дождь'
    else:
        phrase = prefix + (' ожидается ' if likelihood == 'expected' else ' ' + _possible(kind)) + PHASE_NAMES[kind][0]
    return _with_advice(phrase, period, umbrella=kind == 'rain')


def deterministic_comment(forecast: Forecast):
    _resolved(forecast)
    periods = forecast.periods
    hazard_priority = ('freezing_rain', 'freezing_drizzle', 'thunder', 'blizzard',
                       'blowing_snow', 'freezing_fog', 'ice_pellets', 'dust_storm',
                       'sandstorm', 'heavy_snow', 'heavy_rain')
    for kind in hazard_priority:
        for period in periods:
            evidence = [item for item in period.hazards if item.kind == kind]
            if not evidence:
                continue
            expected = any(item.likelihood == 'expected' for item in evidence)
            noun = WARNING_NAMES[kind]
            qualifier = 'ожидается ' if expected else 'возможна ' if kind in FEMININE else 'возможен '
            if period.time_count < 6 or period.condition_count < 6:
                return f'{ADVERBS[period.name]} в доступные часы {qualifier}{noun}'
            times = sorted({item.time for item in evidence if item.likelihood == 'expected'})
            brief = ('кратковременно ' if kind == 'heavy_snow' and expected and 1 <= len(times) <= 2
                     and (len(times) == 1 or (times[1] - times[0]).total_seconds() == 3600) else '')
            phrase = f'{ADVERBS[period.name]} {brief}' + qualifier + noun
            return phrase + (', возможно обледенение' if expected and kind.startswith('freezing_') else '')

    # Contract §8: prolonged precipitation precedes unrelated wind; concurrent
    # rain and wind are combined (the exact scenario 14 wording).
    for period in periods:
        for event in period.precipitation:
            if event.expected_hours and event.duration == 'prolonged':
                if event.kind == 'rain' and (period.wind.speed_level == 'high' or period.wind.gust_level == 'high'):
                    return _wind_comment(period)
                return _event_comment(period, event, 'expected')
    for period in periods:
        if period.wind.speed_level == 'high' or period.wind.gust_level == 'high':
            return _wind_comment(period)
    for period in periods:
        if period.felt_colder_episodes:
            return _with_advice('По ощущениям холоднее', period)
    for likelihood in ('expected', 'possible'):
        for period in periods:
            for kind in ('snow', 'rain', 'sleet', 'ice_pellets', 'unknown'):
                event = next((item for item in period.precipitation if item.kind == kind
                              and (item.expected_hours if likelihood == 'expected' else item.possible_hours)), None)
                if event is not None:
                    return _event_comment(period, event, likelihood)
    if periods[3].time_count < 4:
        return 'Для ближайшей ночи данных недостаточно'
    if periods[1].time_count >= 4 and periods[1].condition_count == 0:
        return 'Для дневного периода погодные условия не уточнены'
    for period in periods:
        if period.wind.speed_level == 'candidate':
            return _with_advice(ADVERBS[period.name] + ' заметный ветер', period)
        if period.wind.gust_level == 'candidate':
            return _with_advice(ADVERBS[period.name] + ' порывистый ветер', period)
    daytime = [item for period in periods[:3] for item in period.hours]
    temperatures = [item.hour.temp_c for item in daytime if item.hour.temp_c is not None]
    if len(temperatures) == 18 and max(temperatures) < 0:
        return _with_advice('Морозно', periods[0])
    # Existing V1 warm threshold (18), retained for ordinary warm/clear wording.
    if len(daytime) == 18 and all(item.condition.category == 'clear' for item in daytime):
        day = periods[1].temperature
        warm = day.minimum is not None and day.minimum >= 18
        return 'Днём ясно и тепло' if warm else 'Днём ясно'
    for period in periods:
        advice = clothing_advice(period)
        if advice:
            return _with_advice('Погодные условия указаны в прогнозе', period)
    return 'День будет облачным' if all(period.predominant in ('cloudy', 'overcast') for period in periods[:3]) else 'Существенные погодные условия указаны в прогнозе'


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _clock(value):
    if type(value) is str and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        return value
    return None


def _weather_details(forecast, *, compact=False):
    hours = [item.hour for period in forecast.periods for item in period.hours]
    speeds = [item.wind_kph for item in hours if item.wind_kph is not None]
    gusts = [item.gust_kph for item in hours if item.gust_kph is not None]
    lines = []
    if compact:
        if speeds and max(speeds) >= 30:
            lines.append('💨 Сильный ветер')
        if gusts and max(gusts) >= 40:
            lines.append('💨 Сильные порывы')
        return lines
    if speeds:
        lines.append(f'💨 {"Сильный ветер" if max(speeds) >= 30 else "Ветер"} — до {rounded(max(speeds))} км/ч')
    if gusts and max(gusts) >= 30:
        lines.append(f'💨 {"Сильные порывы" if max(gusts) >= 40 else "Порывы"} — до {rounded(max(gusts))} км/ч')
    felt = [item.feelslike.minimum for item in forecast.periods
            if item.felt_colder_episodes and item.feelslike.minimum is not None]
    if felt:
        lines.append(f'По ощущениям — до {_signed(rounded(min(felt)))}°')
    return lines


def render_forecast(forecast: Forecast, ancillary: Ancillary | None = None) -> RenderedForecast:
    _resolved(forecast)
    ancillary = ancillary or Ancillary()
    date = forecast.publish_date
    heading = f'Доброе утро, Звенигород! 🌼\n\nПогода на {date.day} {MONTHS[date.month-1]}'
    lines = tuple(render_period(period) for period in forecast.periods)
    comment = deterministic_comment(forecast)
    if utf16_length(comment) > COMMENT_LIMIT:
        raise RenderingBlocked('COMMENT_TOO_LONG')
    mandatory = tuple((period.name, kind) for period in forecast.periods for kind, _ in _warnings(period))
    details = _weather_details(forecast)
    if _finite(ancillary.humidity) and 0 <= ancillary.humidity <= 100:
        details.append(f'💧 Влажность — {rounded(ancillary.humidity)}%')
    if _finite(ancillary.pressure_mb):
        details.append(f'🧭 Давление — {rounded(ancillary.pressure_mb * .750062)} мм рт. ст.')
    astronomy = []
    if _clock(ancillary.sunrise):
        astronomy.append('🌅 Восход — ' + ancillary.sunrise)
    if _clock(ancillary.sunset):
        astronomy.append('🌇 Закат — ' + ancillary.sunset)

    def compose(selected_lines, selected_details, selected_comment, footer=()):
        blocks = [heading, '\n'.join(selected_lines), '\n'.join(selected_details), selected_comment, '\n'.join(footer)]
        return '\n\n'.join(block for block in blocks if block)

    text = compose(lines, details, comment, astronomy)
    compact = False
    if utf16_length(text) > LIMIT:
        compact = True
        lines = tuple(render_period(period, compact=True) for period in forecast.periods)
        details = _weather_details(forecast, compact=True)
        text = compose(lines, details, comment)
    if utf16_length(text) > LIMIT:
        comment = ''  # Warnings remain in the four period lines and wind block.
        text = compose(lines, details, comment)
    if utf16_length(text) > LIMIT:
        heading = f'Погода на {date.day} {MONTHS[date.month-1]}'
        text = compose(lines, details, comment)
    if utf16_length(text) > LIMIT:
        raise RenderingBlocked('MESSAGE_TOO_LONG')
    for period_name, kind in mandatory:
        line = lines[list(LABELS).index(period_name)]
        if WARNING_NAMES[kind] not in line:
            raise RenderingBlocked('WARNING_LOST')
    return RenderedForecast(lines, comment, text, mandatory, compact)
