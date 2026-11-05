"""Offline condition-code registry for Weather Logic V2, contract 1.1.

Provider text is never used for classification. Hazards here are candidates;
the evidence rules in weather_logic decide whether an alert is supported.
"""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class Condition:
    code: int | None
    category: str
    intensity: str | None
    precipitation: str | None
    text_ru: str
    emoji_day: str
    emoji_night: str
    potential_hazards: tuple[str, ...] = ()

    def emoji(self, is_day: int | None) -> str | None:
        """Do not guess daylight for solar/lunar icons."""
        if self.emoji_day == self.emoji_night:
            return self.emoji_day
        if type(is_day) is not int or is_day not in (0, 1):
            return None
        return self.emoji_day if is_day else self.emoji_night


def _entry(code, category, text, emoji, *, night=None, intensity=None,
           precipitation=None, hazards=()):
    return Condition(code, category, intensity, precipitation, text,
                     emoji, night or emoji, hazards)


_ENTRIES = (
    _entry(1000, "clear", "Ясно", "☀️", night="🌙"),
    _entry(1003, "partly_cloudy", "Переменная облачность", "🌤️", night="🌙"),
    _entry(1006, "cloudy", "Облачно", "☁️"),
    _entry(1009, "overcast", "Пасмурно", "☁️"),
    _entry(1012, "haze", "Мгла", "🌫️"),
    _entry(1015, "dust_haze", "Пыльная мгла", "🌫️"),
    _entry(1018, "blowing_dust", "Перенос пыли ветром", "🌫️"),
    _entry(1021, "dust_storm", "Пыльная буря", "🌫️", hazards=("dust_storm",)),
    _entry(1024, "sandstorm", "Песчаная буря", "🌫️", hazards=("sandstorm",)),
    _entry(1027, "sandstorm", "Сильная песчаная буря", "🌫️",
           intensity="heavy", hazards=("sandstorm",)),
    _entry(1030, "mist", "Дымка", "🌫️"),
    _entry(1033, "smoke", "Дым", "🌫️"),
    _entry(1036, "smoky_haze", "Дымная мгла", "🌫️"),
    _entry(1039, "smog", "Смог", "🌫️"),
    _entry(1042, "smog", "Сильный смог", "🌫️", intensity="heavy"),
    _entry(1045, "saharan_dust", "Сахарская пыль", "🌫️"),
    _entry(1048, "dust", "Пыль", "🌫️"),
    _entry(1063, "rain", "Местами возможен дождь", "🌦️", precipitation="rain"),
    _entry(1066, "snow", "Местами возможен снег", "❄️", precipitation="snow"),
    _entry(1069, "sleet", "Местами возможен дождь со снегом", "🌨️",
           precipitation="sleet"),
    _entry(1072, "freezing_drizzle", "Возможна замерзающая морось", "🌧️",
           precipitation="freezing_drizzle", hazards=("freezing_drizzle",)),
    _entry(1087, "thunder", "Возможна гроза", "🌩️", hazards=("thunder",)),
    _entry(1114, "blowing_snow", "Перенос снега ветром", "🌨️",
           hazards=("blowing_snow",)),
    _entry(1117, "blizzard", "Метель", "🌨️", hazards=("blizzard",)),
    _entry(1135, "fog", "Туман", "🌫️"),
    _entry(1147, "freezing_fog", "Замерзающий туман", "🌫️",
           hazards=("freezing_fog",)),
    _entry(1150, "drizzle", "Местами небольшая морось", "🌦️",
           precipitation="rain", intensity="light"),
    _entry(1153, "drizzle", "Небольшая морось", "🌦️",
           precipitation="rain", intensity="light"),
    _entry(1168, "freezing_drizzle", "Замерзающая морось", "🌧️",
           precipitation="freezing_drizzle", hazards=("freezing_drizzle",)),
    _entry(1171, "freezing_drizzle", "Сильная замерзающая морось", "🌧️",
           precipitation="freezing_drizzle", intensity="heavy",
           hazards=("freezing_drizzle",)),
    _entry(1180, "rain", "Местами небольшой дождь", "🌦️",
           precipitation="rain", intensity="light"),
    _entry(1183, "rain", "Небольшой дождь", "🌦️",
           precipitation="rain", intensity="light"),
    _entry(1186, "rain", "Временами умеренный дождь", "🌧️",
           precipitation="rain", intensity="moderate"),
    _entry(1189, "rain", "Умеренный дождь", "🌧️",
           precipitation="rain", intensity="moderate"),
    _entry(1192, "rain", "Временами сильный дождь", "🌧️",
           precipitation="rain", intensity="heavy", hazards=("heavy_rain",)),
    _entry(1195, "rain", "Сильный дождь", "🌧️",
           precipitation="rain", intensity="heavy", hazards=("heavy_rain",)),
    _entry(1198, "freezing_rain", "Слабый ледяной дождь", "🌧️",
           precipitation="freezing_rain", intensity="light",
           hazards=("freezing_rain",)),
    _entry(1201, "freezing_rain", "Ледяной дождь", "🌧️",
           precipitation="freezing_rain", intensity="moderate_or_heavy",
           hazards=("freezing_rain",)),
    _entry(1204, "sleet", "Небольшой дождь со снегом", "🌨️",
           precipitation="sleet", intensity="light"),
    _entry(1207, "sleet", "Умеренный или сильный дождь со снегом", "🌨️",
           precipitation="sleet", intensity="moderate_or_heavy"),
    _entry(1210, "snow", "Местами небольшой снег", "❄️",
           precipitation="snow", intensity="light"),
    _entry(1213, "snow", "Небольшой снег", "❄️",
           precipitation="snow", intensity="light"),
    _entry(1216, "snow", "Местами умеренный снег", "❄️",
           precipitation="snow", intensity="moderate"),
    _entry(1219, "snow", "Умеренный снег", "❄️",
           precipitation="snow", intensity="moderate"),
    _entry(1222, "snow", "Местами сильный снег", "❄️",
           precipitation="snow", intensity="heavy", hazards=("heavy_snow",)),
    _entry(1225, "snow", "Сильный снег", "❄️",
           precipitation="snow", intensity="heavy", hazards=("heavy_snow",)),
    _entry(1237, "ice_pellets", "Ледяная крупа", "🌨️",
           precipitation="ice_pellets", hazards=("ice_pellets",)),
    _entry(1240, "rain", "Небольшой ливневый дождь", "🌦️",
           precipitation="rain", intensity="light"),
    _entry(1243, "rain", "Умеренный или сильный ливневый дождь", "🌧️",
           precipitation="rain", intensity="moderate_or_heavy",
           hazards=("heavy_rain",)),
    _entry(1246, "rain", "Очень сильный ливневый дождь", "🌧️",
           precipitation="rain", intensity="heavy", hazards=("heavy_rain",)),
    _entry(1249, "sleet", "Небольшой ливневый дождь со снегом", "🌨️",
           precipitation="sleet", intensity="light"),
    _entry(1252, "sleet", "Умеренный или сильный ливневый дождь со снегом", "🌨️",
           precipitation="sleet", intensity="moderate_or_heavy"),
    _entry(1255, "snow", "Небольшой ливневый снег", "❄️",
           precipitation="snow", intensity="light"),
    _entry(1258, "snow", "Умеренный или сильный ливневый снег", "❄️",
           precipitation="snow", intensity="moderate_or_heavy",
           hazards=("heavy_snow",)),
    _entry(1261, "ice_pellets", "Небольшие ливневые осадки ледяной крупы", "🌨️",
           precipitation="ice_pellets", intensity="light", hazards=("ice_pellets",)),
    _entry(1264, "ice_pellets", "Умеренные или сильные осадки ледяной крупы", "🌨️",
           precipitation="ice_pellets", intensity="moderate_or_heavy",
           hazards=("ice_pellets",)),
    _entry(1273, "rain", "Местами небольшой дождь с грозой", "🌩️",
           precipitation="rain", intensity="light", hazards=("thunder",)),
    _entry(1276, "rain", "Умеренный или сильный дождь с грозой", "🌩️",
           precipitation="rain", intensity="moderate_or_heavy",
           hazards=("thunder", "heavy_rain")),
    _entry(1279, "snow", "Местами небольшой снег с грозой", "❄️",
           precipitation="snow", intensity="light", hazards=("thunder",)),
    _entry(1282, "snow", "Умеренный или сильный снег с грозой", "❄️",
           precipitation="snow", intensity="moderate_or_heavy",
           hazards=("thunder", "heavy_snow")),
)

CONDITIONS = MappingProxyType({entry.code: entry for entry in _ENTRIES})
UNKNOWN = Condition(None, "unknown", None, None,
                    "Погодные условия не уточнены", "❔", "❔")


def condition_for(code: int | None) -> Condition:
    """Unknown or malformed codes never fall back to sunny weather."""
    if type(code) is not int:
        return UNKNOWN
    return CONDITIONS.get(code, UNKNOWN)


# Shared phase labels are used by the renderer; source Condition.text_ru and
# ambiguous intensity remain independently preserved in the hourly diagnostics.
PRECIPITATION_LABELS = MappingProxyType({
    "rain": ("дождь", "небольшой дождь", "сильный дождь", "🌧️"),
    "snow": ("снег", "небольшой снег", "сильный снег", "❄️"),
    "freezing_rain": ("ледяной дождь", "слабый ледяной дождь", "ледяной дождь", "🌧️"),
    "freezing_drizzle": ("замерзающая морось", "замерзающая морось", "замерзающая морось", "🌧️"),
    "sleet": ("дождь со снегом", "небольшой дождь со снегом", "сильный дождь со снегом", "🌨️"),
    "ice_pellets": ("ледяная крупа", "небольшая ледяная крупа", "сильная ледяная крупа", "🌨️"),
    "unknown": ("осадки", "осадки", "осадки", "❔"),
})
