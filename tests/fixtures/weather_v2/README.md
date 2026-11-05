# Weather Logic V2 — synthetic contract fixtures

All 18 root-level JSON files describe artificial hourly forecasts from the
approved `docs/weather-logic-v2-editorial-contract-1.1.md`, not saved API responses
or historical observations. No synthetic fixture is replaced by fresh API data.

`columns` specifies every explicit input row in `hours`. `condition_code` is
expanded into WeatherAPI's `condition: {code: ...}` shape. The loader supplies no
weather values. Missing hours are absent, never replaced with dry hours. Dates
and `is_day` flags are explicit synthetic inputs, including summer and winter.

`expected` in the 18 Core fixtures contains calculation decisions only: coverage,
temperature, categories/daylight, amounts, probabilities, episodes, wind/gusts,
feels-like and supported hazards. Public entry points are `normalize_hours` and
`analyze_hours`. Their immutable outputs preserve a field allowlist with
valid/missing/null/invalid states. Provider text, arbitrary fields, URLs,
credentials and invalid payload strings are not retained. Source inputs are not
mutated. Unknown valid numeric condition codes remain diagnostic data.

Duplicate equality uses the allowed projection, including missing/null states.
Conflicting timestamps and redacted-invalid duplicate groups are quarantined;
no arbitrary record wins. The accepted PO rule allows the remaining partial
period, recording `DUPLICATE_IDENTITY_QUARANTINED`. Time/epoch disagreements
remain conflicts. TEMP_JUMP preserves the original values and is not bridged
across missing hours or automatically corrected.

## Accepted PO supplements

All seven formerly open rules are implemented. `weather_logic.OPEN_RULES` is
empty; `CLOSED_RULES` records their dispositions. Disagreement diagnostics do not
mean an unanswered editorial rule. No source rain/snow probability is summed or
used as a sleet/ice-pellet probability. Quantities are not multiplied by
probability or converted between mm and snow cm. Missing totals are not zero.
Type conflicts use generic possible precipitation; freezing risk survives as a
separate possible warning. Intensity ties retain their histogram and timed
supported peak, without choosing a winner. See `docs/weather-v2-integration.md`.

## Rendering and release fixtures

`rendering/expected.json` contains exact period lines, comments, complete public
text and photo decisions for all 18 scenarios. Tests compare lines/comments/photo
choices directly to the authoritative Markdown contract, not to generated code
outputs. The full text adds the fixed greeting and safe weather-detail block.

`rendering/extreme_hazards.json` is an extra synthetic 24-hour stress input. Its
four periods combine multiple hazards, conflicting evidence, wind and gusts. It
checks the pretested compact template, all warnings/uncertainty/coverage markers,
both dates and the 1024 UTF-16 budget. It is outside the root-level 18 scenarios.

`test_weather_v2_release.py` additionally tests all accepted evidence matrices,
clothing thresholds and coincident hours, photo precipitation priority, retention,
preflight safety, and the complete app-to-photo-to-four-transports chain using a
synthetic approved/hash-matching catalogue and mocked transports. Real APIs and
messages are never used by tests. Importing Core performs no network or file I/O.
