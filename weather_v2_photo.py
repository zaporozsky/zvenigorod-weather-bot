"""Offline photo decision plus delegation to the existing approved catalogue.

Contract §9 precipitation priorities precede the existing V1 ordinary scenarios.
Landscape season, catalogue approvals and hash checks remain independent.
"""
from dataclasses import dataclass
import os

from weather_logic import Forecast
from weather_photo_selector import SEASONS, select_weather_photo


@dataclass(frozen=True)
class PhotoDecision:
    scenario: str | None
    reason: str


def photo_scenario(forecast: Forecast) -> PhotoDecision:
    if forecast.unresolved_rules:
        return PhotoDecision(None, 'UNRESOLVED_RULES')
    daytime = forecast.periods[:3]
    if any(item.precipitation == 'unknown' for period in daytime for item in period.hours):
        return PhotoDecision(None, 'PRECIPITATION_PHASE_NOT_CONFIRMED')
    if any(period.time_count < 4 or period.condition_count < 4 for period in daytime):
        return PhotoDecision(None, 'INCOMPLETE_DAYTIME')
    hazards = [item for period in daytime for item in period.hazards]
    if any(item.kind in ('freezing_rain', 'freezing_drizzle') for item in hazards):
        return PhotoDecision(None, 'HAZARDOUS_WEATHER_TEXT_ONLY')
    events = [item for period in daytime for item in period.precipitation]
    snow_hours = sum(item.expected_hours for item in events if item.kind == 'snow')
    confirmed_heavy = any(item.strong_snow_supported for period in daytime for item in period.hours)
    if snow_hours >= 3 or confirmed_heavy:
        return PhotoDecision('snowy', 'EXPECTED_SNOW')
    if any(reason.code == 'STRONG_SNOW_NOT_SUPPORTED' for period in daytime
           for item in period.hours for reason in item.diagnostics):
        return PhotoDecision(None, 'UNCONFIRMED_STRONG_SNOW_TEXT_ONLY')
    rain_hours = sum(item.expected_hours for item in events if item.kind == 'rain')
    if rain_hours >= 3:
        return PhotoDecision('rainy', 'EXPECTED_RAIN')
    if any(item.kind == 'rain' for item in events):
        return PhotoDecision('small_rain_possible', 'POSSIBLE_OR_BRIEF_RAIN')
    if any(item.kind not in ('rain', 'snow') for item in events):
        return PhotoDecision(None, 'NO_COMPATIBLE_PRECIPITATION_PHOTO')
    if any(item.kind not in ('heavy_snow', 'heavy_rain') for item in hazards):
        return PhotoDecision(None, 'NO_COMPATIBLE_HAZARD_PHOTO')
    if any(period.wind.speed_level == 'high' or period.wind.gust_level == 'high' for period in daytime):
        return PhotoDecision('strong_wind', 'HIGH_WIND')
    temps = [item.hour.temp_c for period in daytime if period.temperature.mode != 'unavailable'
             for item in period.hours if item.hour.temp_c is not None]
    # Retain V1's existing ordinary-scenario thresholds, after Contract §9's
    # precipitation priorities. No new landscape or warmth thresholds.
    if temps:
        maximum = max(temps)
        if maximum < -10:
            return PhotoDecision('very_cold', 'EXISTING_V1_TEMPERATURE_RULE')
        if maximum < 5:
            return PhotoDecision('cold', 'EXISTING_V1_TEMPERATURE_RULE')
        if maximum >= 30:
            return PhotoDecision('unusually_warm', 'EXISTING_V1_TEMPERATURE_RULE')
        if maximum >= 18 and all(period.predominant == 'clear' for period in daytime):
            return PhotoDecision('sunny_warm', 'EXISTING_V1_TEMPERATURE_RULE')
    if any(period.predominant in ('fog', 'mist') for period in daytime):
        return PhotoDecision('fog', 'PREDOMINANT_FOG')
    if all(period.predominant in ('cloudy', 'overcast', 'partly_cloudy') for period in daytime):
        return PhotoDecision('cloudy_comfortable', 'PREDOMINANT_CLOUD')
    return PhotoDecision('ordinary_calm', 'EXISTING_ORDINARY_FALLBACK')


def select_v2_photo(decision, photo_scenarios, *, photo_dir='photos',
                    manifest='photos/photo_seasons.csv', season=None):
    """Explicit runtime I/O only. Never infer landscape season from forecast."""
    if decision.scenario is None or decision.scenario not in photo_scenarios:
        return None
    selected_season = season if season is not None else os.getenv('PHOTO_SEASON', '')
    if type(selected_season) is not str or selected_season.strip().lower() not in SEASONS:
        print('PHOTO_SELECTION_V2: INVALID_SEASON; text-only', flush=True)
        return None
    return select_weather_photo(decision.scenario, photo_scenarios,
                                photo_dir=photo_dir, manifest=manifest,
                                season=selected_season)
