"""Pure, offline Weather Logic V2 calculations (Editorial Contract 1.1).

No rendering, clothing advice, photo selection, persistence or delivery lives
here. Input is an iterable of WeatherAPI-style hourly mappings. Only allowed
weather fields enter the immutable source projection; arbitrary provider text,
URLs, credentials and exceptions are never retained.

An unresolved rule is explicit data, not an invented editorial decision.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import math
from statistics import median
from types import MappingProxyType
from zoneinfo import ZoneInfo

from weather_conditions import Condition, condition_for


CONTRACT_VERSION = "1.1"
TIMEZONE = "Europe/Moscow"
NUMERIC_FIELDS = (
    "temp_c", "feelslike_c", "precip_mm", "snow_cm", "chance_of_rain",
    "chance_of_snow", "wind_kph", "gust_kph", "cloud",
)
NONNEGATIVE_FIELDS = frozenset({"precip_mm", "snow_cm", "wind_kph", "gust_kph"})
PERCENT_FIELDS = frozenset({"chance_of_rain", "chance_of_snow", "cloud"})
HOUR = timedelta(hours=1)

# PO accepted the seven documented proposals. Closed rules remain auditable;
# diagnostic disagreements are data, not unanswered editorial decisions.
OPEN_RULES = MappingProxyType({})
CLOSED_RULES = MappingProxyType({
    "PRECIPITATION_EVIDENCE_UNRESOLVED": "Code/probability/amount occurrence matrix; no invented amount or percentage",
    "PRECIPITATION_TYPE_CONFLICT": "Generic possible precipitation; keep possible freezing hazard",
    "PRECIPITATION_KIND_UNRESOLVED": "Sleet/ice code defines phase; positive precip_mm supports occurrence",
    "AMBIGUOUS_SNOW_INTENSITY": "Preserve ambiguous intensity; confirmed gate permits possible heavy hazard only",
    "HAZARD_CONFIRMATION_UNRESOLVED": "Code-only hazards possible; heavy rain uses existing evidence bands",
    "INTENSITY_PREVALENCE_UNRESOLVED": "Tie uses generic phase; confirmed heavy episode remains separately timed",
    "DUPLICATE_IDENTITY_UNRESOLVED": "Quarantine unprovable duplicate timestamp; retain partial-period evidence",
})


@dataclass(frozen=True)
class Diagnostic:
    code: str
    time: datetime | None = None
    field: str | None = None
    source_indices: tuple[int, ...] = ()
    delta_c: float | None = None


@dataclass(frozen=True)
class SourceField:
    name: str
    state: str  # valid / missing / null / invalid
    value: int | float | str | None = None


@dataclass(frozen=True)
class SourceHour:
    index: int
    time: datetime | None
    fields: tuple[SourceField, ...]


@dataclass(frozen=True)
class ForecastHour:
    time: datetime
    condition_code: int | None
    temp_c: float | None = None
    feelslike_c: float | None = None
    precip_mm: float | None = None
    snow_cm: float | None = None
    chance_of_rain: float | None = None
    chance_of_snow: float | None = None
    wind_kph: float | None = None
    gust_kph: float | None = None
    cloud: float | None = None
    is_day: int | None = None


@dataclass(frozen=True)
class NormalizedHours:
    hours: tuple[ForecastHour, ...]
    sources: tuple[SourceHour, ...]
    diagnostics: tuple[Diagnostic, ...]
    conflict_times: tuple[datetime, ...]


@dataclass(frozen=True)
class Metric:
    count: int
    total: float | None
    minimum: float | None
    maximum: float | None
    complete: bool
    total_error: str | None = None


@dataclass(frozen=True)
class Temperature:
    count: int
    minimum: float | None
    maximum: float | None
    median: float | None
    mode: str  # range / representative / unavailable
    rounded_minimum: int | None = None
    rounded_maximum: int | None = None
    representative: int | None = None


@dataclass(frozen=True)
class Hazard:
    kind: str
    time: datetime
    likelihood: str  # expected / possible / unresolved


@dataclass(frozen=True)
class Assessment:
    hour: ForecastHour
    condition: Condition
    precipitation: str | None
    likelihood: str  # none / expected / possible / unresolved
    intensity: str | None
    strong_snow_supported: bool
    wind_level: str
    gust_level: str
    hazards: tuple[Hazard, ...]
    diagnostics: tuple[Diagnostic, ...]
    unresolved_rules: tuple[str, ...]


@dataclass(frozen=True)
class Episode:
    kind: str
    likelihood: str
    start: datetime
    end: datetime  # exclusive
    times: tuple[datetime, ...]
    intensity_counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class Precipitation:
    kind: str
    expected_hours: int
    possible_hours: int
    unresolved_hours: int
    episodes: tuple[Episode, ...]
    duration: str | None
    intensity_counts: tuple[tuple[str, int], ...]
    predominant_intensity: str | None
    peak_intensity: str | None
    probability: Metric | None
    unresolved_rules: tuple[str, ...]


@dataclass(frozen=True)
class Wind:
    speed: Metric
    gust: Metric
    speed_level: str
    gust_level: str
    candidate_speed_times: tuple[datetime, ...]
    high_speed_times: tuple[datetime, ...]
    candidate_gust_times: tuple[datetime, ...]
    high_gust_times: tuple[datetime, ...]


@dataclass(frozen=True)
class Period:
    name: str
    start: datetime
    end: datetime
    hours: tuple[Assessment, ...]
    time_count: int
    condition_count: int
    condition_coverage: str  # complete / limited / insufficient
    category_counts: tuple[tuple[str, int], ...]
    predominant: str | None
    category_runs: tuple[Episode, ...]
    is_day: int | None
    temperature: Temperature
    feelslike: Metric
    felt_colder_episodes: tuple[Episode, ...]
    rain_probability: Metric
    snow_probability: Metric
    precipitation_mm: Metric
    snowfall_cm: Metric
    cloud: Metric
    precipitation: tuple[Precipitation, ...]
    wind: Wind
    hazards: tuple[Hazard, ...]
    diagnostics: tuple[Diagnostic, ...]
    unresolved_rules: tuple[str, ...]


@dataclass(frozen=True)
class Forecast:
    publish_date: date
    normalized: NormalizedHours
    periods: tuple[Period, ...]
    hazards: tuple[Hazard, ...]
    diagnostics: tuple[Diagnostic, ...]
    unresolved_rules: tuple[str, ...]


def probability_band(value: float | None) -> str:
    if value is None:
        return "unknown"
    if not _numeric(value) or not 0 <= value <= 100:
        raise ValueError("probability must be finite and within 0..100")
    return "likely" if value >= 70 else "possible" if value >= 30 else "low"


def wind_level(value: float | None, *, gust: bool = False) -> str:
    if value is None:
        return "unknown"
    if not _numeric(value) or value < 0:
        raise ValueError("wind must be finite and nonnegative")
    candidate, high = (30, 40) if gust else (20, 30)
    return "high" if value >= high else "candidate" if value >= candidate else "none"


def _numeric(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _number_field(record, key):
    if key not in record:
        return SourceField(key, "missing")
    value = record[key]
    if value is None:
        return SourceField(key, "null")
    valid = _numeric(value)
    if valid and key in NONNEGATIVE_FIELDS:
        valid = value >= 0
    if valid and key in PERCENT_FIELDS:
        valid = 0 <= value <= 100
    return SourceField(key, "valid", value) if valid else SourceField(key, "invalid")


def _integer_field(record, key, *, binary=False):
    if key not in record:
        return SourceField(key, "missing")
    value = record[key]
    if value is None:
        return SourceField(key, "null")
    if type(value) is int and (not binary or value in (0, 1)):
        return SourceField(key, "valid", value)
    return SourceField(key, "invalid")


def _parse_time(value):
    if type(value) is not str:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M")
        if parsed.strftime("%Y-%m-%d %H:%M") != value:
            return None
        return parsed.replace(tzinfo=ZoneInfo(TIMEZONE))
    except ValueError:
        return None


def normalize_hours(records: Iterable[Mapping]) -> NormalizedHours:
    """Keep only sanitized source fields; quarantine every conflicting hour.

    Duplicate identity is equality of the allowed weather-field projection,
    including missing/null states. Unknown fields never influence decisions.
    Invalid values are not stored; therefore their duplicate equality cannot
    be proved and such duplicate groups are quarantined rather than guessed.
    """
    sources, diagnostics, groups = [], [], {}
    quarantined = {}
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            sources.append(SourceHour(index, None, ()))
            diagnostics.append(Diagnostic("INVALID_HOUR", source_indices=(index,)))
            continue
        parsed = _parse_time(record.get("time"))
        if "time" not in record:
            time_state = "missing"
        elif record["time"] is None:
            time_state = "null"
        else:
            time_state = "valid" if parsed is not None else "invalid"
        fields = [SourceField("time", time_state,
                              record["time"] if parsed is not None else None)]
        condition = record.get("condition")
        code_record = condition if isinstance(condition, Mapping) else {}
        code = _integer_field(code_record, "code")
        if "condition" in record and not isinstance(condition, Mapping):
            code = SourceField("code", "null" if condition is None else "invalid")
        fields.append(replace(code, name="condition_code"))
        fields.extend(_number_field(record, key) for key in NUMERIC_FIELDS)
        fields.append(_integer_field(record, "is_day", binary=True))
        epoch = _integer_field(record, "time_epoch")
        fields.append(epoch)
        source = SourceHour(index, parsed, tuple(fields))
        sources.append(source)
        for field in fields:
            if field.state != "valid":
                diagnostics.append(Diagnostic(
                    field.state.upper() + "_FIELD", parsed, field.name, (index,)
                ))
        if parsed is None:
            continue
        if parsed.minute != 0:
            diagnostics.append(Diagnostic("OFF_HOUR_TIMESTAMP", parsed, "time", (index,)))
            continue
        if epoch.state == "valid":
            try:
                epoch_time = datetime.fromtimestamp(epoch.value, ZoneInfo(TIMEZONE))
            except (OverflowError, OSError, ValueError):
                diagnostics.append(Diagnostic("INVALID_EPOCH", parsed,
                                              "time_epoch", (index,)))
                quarantined.setdefault(parsed, []).append(index)
                continue
            if epoch_time != parsed:
                diagnostics.append(Diagnostic("TIME_CONFLICT", parsed,
                                              "time_epoch", (index,)))
                quarantined.setdefault(parsed, []).append(index)
                continue
        values = {field.name: field.value if field.state == "valid" else None
                  for field in fields}
        hour = ForecastHour(parsed, values["condition_code"],
                            **{key: values[key] for key in NUMERIC_FIELDS},
                            is_day=values["is_day"])
        groups.setdefault(parsed, []).append((hour, source))

    hours, conflicts = [], set(quarantined)
    for time, group in sorted(groups.items()):
        signature = group[0][1].fields
        indices = tuple(item[1].index for item in group)
        if time in quarantined:
            diagnostics.append(Diagnostic("QUARANTINED_TIME", time,
                                          source_indices=indices + tuple(quarantined[time])))
            continue
        invalid = any(field.state == "invalid" for _, src in group for field in src.fields)
        different = any(src.fields != signature for _, src in group)
        if len(group) > 1 and (invalid or different):
            conflicts.add(time)
            code = "CONFLICTING_DUPLICATES" if different else "DUPLICATE_IDENTITY_QUARANTINED"
            diagnostics.append(Diagnostic(code, time,
                                          source_indices=indices))
            continue
        hours.append(group[0][0])
        if len(group) > 1:
            diagnostics.append(Diagnostic("IDENTICAL_DUPLICATES", time,
                                          source_indices=indices))
    for previous, current in zip(hours, hours[1:]):
        if (current.time - previous.time == HOUR
                and previous.temp_c is not None and current.temp_c is not None):
            delta = Decimal(str(current.temp_c)) - Decimal(str(previous.temp_c))
            if abs(delta) >= 6:
                numeric_delta = float(delta)
                finite_delta = numeric_delta if math.isfinite(numeric_delta) else None
                diagnostics.append(Diagnostic("TEMP_JUMP", current.time,
                                              "temp_c", delta_c=finite_delta))
                if finite_delta is None:
                    diagnostics.append(Diagnostic("TEMP_DELTA_OVERFLOW", current.time, "temp_c"))
    return NormalizedHours(tuple(hours), tuple(sources), tuple(diagnostics), tuple(sorted(conflicts)))


def _round(value):
    return int(Decimal(str(value)).to_integral_value(rounding=ROUND_HALF_UP))


def aggregate_temperature(hours: Iterable[ForecastHour]) -> Temperature:
    values = [hour.temp_c for hour in hours if hour.temp_c is not None]
    if not values:
        return Temperature(0, None, None, None, "unavailable")
    low, high = min(values), max(values)
    middle = median([Decimal(str(value)) for value in values])
    result = Temperature(len(values), low, high, float(middle), "unavailable")
    if len(values) < 4:
        return result
    if Decimal(str(high)) - Decimal(str(low)) >= 3:
        return replace(result, mode="range", rounded_minimum=_round(low),
                       rounded_maximum=_round(high))
    return replace(result, mode="representative", representative=_round(middle))


def resolve_is_day(hours: Iterable[ForecastHour]) -> int | None:
    values = [hour.is_day for hour in sorted(hours, key=lambda item: item.time)
              if hour.is_day is not None]
    if len(values) < 4:
        return None
    ones = values.count(1)
    if ones * 2 == len(values):
        return values[len(values) // 2]
    return int(ones * 2 > len(values))


def assess_hour(hour: ForecastHour) -> Assessment:
    condition = condition_for(hour.condition_code)
    phase, likelihood, intensity = condition.precipitation, "none", condition.intensity
    diagnostics, hazards = [], []
    strong = False

    def reason(code):
        diagnostics.append(Diagnostic(code, hour.time))

    if condition.category == "unknown":
        reason("UNKNOWN_CONDITION_CODE")
    probability = hour.chance_of_snow if phase == "snow" else hour.chance_of_rain
    if phase in ("rain", "freezing_rain", "freezing_drizzle") and (hour.snow_cm or 0) > 0:
        if phase in ("freezing_rain", "freezing_drizzle"):
            hazards.append(Hazard(phase, hour.time, "possible"))
            reason("FREEZING_EVIDENCE_CONFLICT")
        phase, likelihood, intensity = "unknown", "possible", None
        reason("PRECIPITATION_TYPE_CONFLICT")
    elif phase in ("freezing_rain", "freezing_drizzle"):
        likelihood = ("expected" if probability is not None and probability >= 70
                      and (hour.precip_mm or 0) > 0 else "possible")
        if probability == 0:
            reason("FREEZING_EVIDENCE_CONFLICT")
        hazards.append(Hazard(phase, hour.time, likelihood))
    elif phase in ("snow", "rain"):
        positive = (hour.precip_mm or 0) > 0 or (phase == "snow" and (hour.snow_cm or 0) > 0)
        likelihood = "expected" if positive and (probability is None or probability >= 70) else "possible"
        if positive and probability is not None and probability < 30:
            reason("PRECIPITATION_PROBABILITY_AMOUNT_CONFLICT")
        elif probability is not None and probability >= 70 and not positive:
            reason("PRECIPITATION_AMOUNT_NOT_CONFIRMED")
        elif not positive:
            reason("PRECIPITATION_CODE_ONLY")
        if phase == "snow" and condition.intensity in ("heavy", "moderate_or_heavy"):
            supported = (probability is not None and probability >= 30
                         and (hour.snow_cm or 0) > 0 and (hour.precip_mm or 0) > 0)
            if supported:
                strong = condition.intensity == "heavy"
                hazards.append(Hazard("heavy_snow", hour.time,
                                      likelihood if strong else "possible"))
                if not strong:
                    reason("AMBIGUOUS_SNOW_INTENSITY_PRESERVED")
            else:
                intensity = None
                likelihood = "possible"
                reason("STRONG_SNOW_NOT_SUPPORTED")
                if probability == 0 and hour.snow_cm == 0 and hour.precip_mm == 0:
                    reason("SNOW_EVIDENCE_CONFLICT")
    elif phase is not None:  # sleet and ice pellets, never substitute rain/snow probability
        likelihood = "expected" if (hour.precip_mm or 0) > 0 else "possible"
        reason("MIXED_PRECIPITATION_CODE_EVIDENCE")
    else:
        rain = (hour.chance_of_rain or 0) >= 30
        snow = (hour.chance_of_snow or 0) >= 30
        if (hour.precip_mm or 0) > 0 or (hour.snow_cm or 0) > 0 or (rain and snow):
            phase, likelihood, intensity = "unknown", "possible", None
            reason("PRECIPITATION_PHASE_NOT_CONFIRMED")
        elif rain or snow:
            phase, likelihood, intensity = "snow" if snow else "rain", "possible", None
            reason("PRECIPITATION_PROBABILITY_ONLY")

    for kind in condition.potential_hazards:
        if kind in ("heavy_snow", "freezing_rain", "freezing_drizzle"):
            continue
        if kind == "heavy_rain" and phase == "unknown":
            reason("HAZARD_PHASE_NOT_CONFIRMED")
            continue
        hazard_likelihood = "possible"
        if kind == "heavy_rain" and phase == "rain":
            if (condition.intensity == "heavy" and (hour.precip_mm or 0) > 0
                    and probability is not None and probability >= 70):
                hazard_likelihood = "expected"
            reason("HEAVY_RAIN_EVIDENCE" if hazard_likelihood == "expected" else "HEAVY_RAIN_POTENTIAL")
        else:
            reason("HAZARD_CODE_ONLY")
        hazards.append(Hazard(kind, hour.time, hazard_likelihood))
    return Assessment(hour, condition, phase, likelihood, intensity, strong,
                      wind_level(hour.wind_kph), wind_level(hour.gust_kph, gust=True),
                      tuple(hazards), tuple(diagnostics), ())


def _metric(hours, field):
    values = [getattr(hour, field) for hour in hours if getattr(hour, field) is not None]
    total, total_error = None, None
    if values and field in ("precip_mm", "snow_cm"):
        # Preserve decimal weather amounts without binary accumulation noise.
        total = float(sum((Decimal(str(value)) for value in values), Decimal(0)))
        if not math.isfinite(total):
            total = None
            total_error = "QUANTITY_TOTAL_OVERFLOW"
    return Metric(len(values), total,
                  min(values) if values else None, max(values) if values else None,
                  len(values) == 6, total_error)


def _episodes(items):
    """Items are (time, kind, likelihood, intensity); never bridge absent hours."""
    groups = []
    for time, kind, likelihood, intensity in sorted(items):
        if (groups and groups[-1][-1][0] + HOUR == time
                and groups[-1][-1][1:3] == (kind, likelihood)):
            groups[-1].append((time, kind, likelihood, intensity))
        else:
            groups.append([(time, kind, likelihood, intensity)])
    return tuple(Episode(
        group[0][1], group[0][2], group[0][0], group[-1][0] + HOUR,
        tuple(item[0] for item in group),
        tuple(sorted(Counter(item[3] for item in group if item[3] is not None).items())),
    ) for group in groups)


def _precipitation(assessments, kind, complete):
    matching = [item for item in assessments if item.precipitation == kind]
    episodes = _episodes((item.hour.time, kind, item.likelihood, item.intensity)
                         for item in matching)
    expected = sum(item.likelihood == "expected" for item in matching)
    possible = sum(item.likelihood == "possible" for item in matching)
    unresolved = sum(item.likelihood == "unresolved" for item in matching)
    expected_episodes = [item for item in episodes if item.likelihood == "expected"]
    duration = None
    if complete and expected and not unresolved:
        if len(expected_episodes) > 1 or expected in (3, 4):
            duration = "intermittent"
        elif expected >= 5:
            duration = "prolonged"
        else:
            duration = "brief"
    counts = Counter(item.intensity for item in matching if item.intensity is not None)
    predominant = None
    questions = set()
    if counts:
        winners = [key for key, count in counts.items() if count == max(counts.values())]
        if len(winners) == 1:
            predominant = winners[0]
        # An intensity tie deliberately leaves the generic phase; no winner.
    rank = {"light": 1, "moderate": 2, "heavy": 3}
    peak = max(counts, key=rank.get) if counts and set(counts) <= rank.keys() else None
    probability = None
    hours = [item.hour for item in assessments]
    if kind in ("rain", "freezing_rain", "freezing_drizzle"):
        probability = _metric(hours, "chance_of_rain")
    elif kind == "snow":
        probability = _metric(hours, "chance_of_snow")
    return Precipitation(kind, expected, possible, unresolved, episodes, duration,
                         tuple(sorted(counts.items())), predominant, peak,
                         probability, tuple(sorted(questions)))


def _make_period(name, start, end, normalized):
    hours = tuple(hour for hour in normalized.hours if start <= hour.time < end)
    assessed = tuple(assess_hour(hour) for hour in hours)
    def category(item):
        # Retain source category in Assessment.condition, but do not resolve a
        # disputed precipitation type by counting its raw code as editorial truth.
        return "unknown" if item.precipitation == "unknown" else item.condition.category

    known = sum(category(item) != "unknown" for item in assessed)
    counts = Counter(category(item) for item in assessed)
    dominant = next((category for category, count in counts.items()
                     if category != "unknown" and count >= 4), None)
    category_runs = _episodes((item.hour.time, category(item), "source", None)
                              for item in assessed)
    daylight_hours = [item.hour for item in assessed if category(item) == dominant]
    precipitation = tuple(_precipitation(assessed, kind, known == 6)
                          for kind in sorted({item.precipitation for item in assessed
                                              if item.precipitation is not None}))
    colder = _episodes((hour.time, "felt_colder", "candidate", None) for hour in hours
                       if hour.temp_c is not None and hour.feelslike_c is not None
                       and Decimal(str(hour.temp_c)) - Decimal(str(hour.feelslike_c)) >= 5)
    colder = tuple(item for item in colder if len(item.times) >= 2)
    wind = Wind(
        _metric(hours, "wind_kph"), _metric(hours, "gust_kph"),
        wind_level(_metric(hours, "wind_kph").maximum),
        wind_level(_metric(hours, "gust_kph").maximum, gust=True),
        tuple(item.hour.time for item in assessed if item.wind_level == "candidate"),
        tuple(item.hour.time for item in assessed if item.wind_level == "high"),
        tuple(item.hour.time for item in assessed if item.gust_level == "candidate"),
        tuple(item.hour.time for item in assessed if item.gust_level == "high"),
    )
    diagnostics = [reason for reason in normalized.diagnostics
                   if reason.time is not None and start <= reason.time < end]
    diagnostics.extend(reason for item in assessed for reason in item.diagnostics)
    if len(hours) < 6:
        diagnostics.append(Diagnostic("INCOMPLETE_PERIOD", start))
    for field in ("precip_mm", "snow_cm"):
        metric = _metric(hours, field)
        if metric.total_error:
            diagnostics.append(Diagnostic(metric.total_error, start, field))
    unresolved = {reason for item in assessed for reason in item.unresolved_rules}
    unresolved.update(reason for item in precipitation for reason in item.unresolved_rules)
    unresolved.update(item.code for item in diagnostics if item.code in OPEN_RULES)
    for item in precipitation:
        if item.intensity_counts and item.predominant_intensity is None:
            diagnostics.append(Diagnostic("INTENSITY_PREVALENCE_TIE", start, "intensity"))
        diagnostics.extend(Diagnostic(reason, start, "intensity")
                           for reason in item.unresolved_rules)
    return Period(
        name, start, end, assessed, len(hours), known,
        "complete" if known == 6 else "limited" if known >= 4 else "insufficient",
        tuple(sorted(counts.items())), dominant, category_runs,
        resolve_is_day(daylight_hours), aggregate_temperature(hours),
        _metric(hours, "feelslike_c"), colder,
        _metric(hours, "chance_of_rain"), _metric(hours, "chance_of_snow"),
        _metric(hours, "precip_mm"), _metric(hours, "snow_cm"), _metric(hours, "cloud"),
        precipitation, wind, tuple(hazard for item in assessed for hazard in item.hazards),
        tuple(diagnostics), tuple(sorted(unresolved)),
    )


def analyze_hours(records: Iterable[Mapping], publish_date: str) -> Forecast:
    """Analyze D 06:00 through D+1 06:00; never substitute the preceding night.

    Partial and unusable data remain explicit. Whether an incomplete forecast
    may be published is deliberately outside this calculation-only module.
    """
    if type(publish_date) is not str:
        raise ValueError("publish_date must be YYYY-MM-DD")
    try:
        target = date.fromisoformat(publish_date)
        if target.isoformat() != publish_date:
            raise ValueError
    except ValueError:
        raise ValueError("publish_date must be YYYY-MM-DD") from None
    normalized = normalize_hours(records)
    start = datetime(target.year, target.month, target.day, 6, tzinfo=ZoneInfo(TIMEZONE))
    names = ("morning", "day", "evening", "night")
    periods = tuple(_make_period(name, start + HOUR * (index * 6),
                                 start + HOUR * ((index + 1) * 6), normalized)
                    for index, name in enumerate(names))
    diagnostics = list(normalized.diagnostics)
    for period in periods:
        diagnostics.extend(reason for reason in period.diagnostics
                           if reason not in normalized.diagnostics)
    unresolved = {rule for period in periods for rule in period.unresolved_rules}
    unresolved.update(item.code for item in normalized.diagnostics if item.code in OPEN_RULES)
    return Forecast(target, normalized, periods,
                    tuple(hazard for period in periods for hazard in period.hazards),
                    tuple(diagnostics),
                    tuple(sorted(unresolved)))
