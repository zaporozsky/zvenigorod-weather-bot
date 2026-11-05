# Weather Logic V2 — Production Preflight preparation

## Inactive release assembly — 2026-11-05

Current release is assembled from approved candidate
`a245beacf44cf7f0a3eaf24683840542a7e32f31` on diagnostic main
`8b3db77d000ae4fa8b8972489819f3ff25db8343`. The seven diagnostic files
are byte-identical; existing workflows, advice, selector and photo archive
are unchanged. All seven CLOSED_RULES and 18 Contract 1.1 scenarios are retained.

The one authorized [WeatherAPI preflight run 42001284526](https://github.com/zaporozsky/zvenigorod-weather-bot/actions/runs/42001284526)
completed successfully on diagnostic main: request_attempts=1, HTTP 200,
2026-11-05 and 2026-11-06 each have 24 valid unique hours, D+1 00–05 is
available, required fields are complete, v2.status=compatible. Rendering used
561 UTF-16 units. Mixed precipitation and probability/amount conflicts were
reported as diagnostics, without blocking preparation. No additional API request
or workflow dispatch is part of this release assembly.

V1 remains the default. V2_CHAIN_VERIFIED=False and V2_LIVE_ENABLED=False;
no environment/variable/Secret selector is changed. Release publication is
separately authorized; production activation and real V2 publications are not.
The following sections retain the earlier preparation-phase record; statements
about a pending/unexecuted preflight or unpublished diagnostic workflow are
historical and superseded by this section. A successful preflight does not
prove delivery permissions or eliminate duplicate-trigger risks: no cross-run
idempotency ledger exists, and no automatic resend is introduced.

Status: local preparation only; no push, merge, workflow dispatch, WeatherAPI
request, Telegram/MAX send or V2 activation. The existing Secret is used by
reference, never retrieved, printed or copied to source. The prior base is
`4777ae2a5af9dd19d6e6cb96c2ead01c4b2f3e0f`.

## Verified configuration

- `.github/workflows/weather.yml` maps `secrets.WEATHER_API_KEY` to process env
  `WEATHER_API_KEY` for `python app_zngrd_weather.py`. The app reads that env name.
  Secret existence is supplied by PO; its value was not accessed locally.
- The publication workflow has only `workflow_dispatch`, no YAML `schedule`.
  The other three existing active workflows are manual scheduler-test, LLM
  preview and Telegram access diagnostics. None is invoked by this preparation.
- cron-job.org is the external initiator according to PO. Its job URL, cron
  expression, timezone and credentials are outside this checkout and were not
  queried or changed. The repository evidence establishes the dispatch entry
  point, not the external service configuration.
- Existing four YAML workflows remain byte-identical to the base. Backups ending
  in `.bak` are not active workflows and are excluded from the candidate commit.

## New workflow and the one-response check

Path: `.github/workflows/weatherapi-preflight.yml`.
Name: **WeatherAPI V2 preflight without publishing**.

Only `workflow_dispatch`, contents:read, no checkout credential persistence,
Python 3.11, five-minute timeout. No dependency installation is needed; the
client and pure V2 import closure use the standard library. Only the diagnostic
step receives `WEATHER_API_KEY: ${{ secrets.WEATHER_API_KEY }}`; no Telegram/MAX
or LLM Secret is supplied. No main-workflow dispatch or schedule is added.

One initial attempt executes one fixed-host HTTPS GET to forecast.json with
q=55.7352,36.8553, days=2, lang=ru. No redirects, retries or additional WeatherAPI
endpoints. A rerun attempt fails before checkout/Secret use/API code. Separate
manual dispatches are separate runs, so an operator must dispatch exactly once;
concurrency serializes them but is not a cross-run once-only ledger. Missing
Secret or a blocked rerun sends zero requests. `request_attempts` is a client
attempt count; a network failure cannot prove whether the server received it.

D is fixed before the request in Europe/Moscow. Only metadata from the returned
response is logged:

- HTTP status and categorical error, with numeric provider error code if present;
- two consecutive calendar dates matching D/D+1;
- exactly 24 unique aligned hour timestamps on each enclosing date;
- malformed timestamps, wrong-date rows, duplicates, missing clocks and optional
  time_epoch inconsistency (without copying malformed values);
- D+1 00:00–05:00 availability, never substituted with D's early hours;
- separate valid/missing/null/invalid counts for condition.code, temp_c,
  feelslike_c, chance_of_rain, chance_of_snow, precip_mm, snow_cm, wind_kph,
  gust_kph and is_day; cloud is also measured as optional Core input;
- pure V2 preparation status on the SAME response: period coverage, safe
  diagnostic codes, rendered UTF-16 length and photo decision, without text.

No app, Telegram, MAX, LLM or publishing module is imported. Source import closure
is checked in offline tests. No raw response, forecast field values, provider
text/location/PII, keys, headers, URL/path, full public message or snapshot is
logged/uploaded. The response exists in memory only. This does not alter the
repository's general GitHub log-retention setting; there is no forecast snapshot
archive or artifact in this workflow.

Exit 0 requires HTTP 200, the full correct temporal structure, all required
fields valid, and successful pure V2 preparation (`category=OK`). Field gaps are
reported as `REQUIRED_FIELD_GAPS`, not filled or treated as success; exit 2 also
covers structural/API/compatibility errors. V2 may support safe missing-field
fallback, which is reported independently. An error does not trigger a second
request. A green preflight neither activates V2 nor proves real channel access.

## Local checks and scope

Full suite: 145 test methods PASS, with socket connects and DNS denied.
Includes the prior 128 tests, 18 approved Contract 1.1 scenarios and 17 new
preflight checks. The shared sender still attempts four destinations once each,
continues after individual errors and does not resend via V1 after partial V2
failure. There is no cross-run idempotency ledger; manual reruns/duplicate
external triggers can still duplicate publications.

Python AST/compile/tabnanny, fixture JSON and code/other-file whitespace checks
pass. Full staged whitespace check reports only 18 intentional Markdown
two-space line breaks in the PO-supplied contract; its bytes are preserved.
The new YAML is parsed locally with Ruby/Psych and its manual trigger/read-only
permissions/single command checked. The rerun shell guard is checked offline.
Actionlint/Ruff/flake8/Pylint are unavailable; no packages were downloaded.

Live V2 flags remain False and V1 remains default. Existing workflow bytes,
recipient/photo-mapping constants, original selector/manifest and V1 advice are
checked against the base. No foto archive or scheduler configuration is changed.

This task adds/updates:

1. `.github/workflows/weatherapi-preflight.yml` — new manual job.
2. `weather_v2_preflight.py` — complete temporal/field checks and pure V2
   compatibility on the single response.
3. `tests/test_weather_v2_preflight.py` — offline verification.
4. `docs/weather-v2-production-preflight.md` — this runbook.
5. `docs/weather-v2-integration.md`, `docs/weather-v2-release-report.md` — replace
   the obsolete local-key blocker with the existing GitHub Secret route.

The local candidate commit also packages all previously prepared V2 release
files, which had not been committed. Its exact file list is obtainable with
`git show --name-only --format= HEAD`; it contains only the following allowlist:

- `app_zngrd_weather.py` and `tests/test_publication.py`;
- `weather_conditions.py`, `weather_logic.py`, `weather_rendering.py`,
  `weather_v2_photo.py`, `weather_v2_integration.py`, `weather_v2_preflight.py`;
- `tests/test_weather_conditions.py`, `tests/test_weather_logic.py`,
  `tests/test_weather_rendering.py`, `tests/test_weather_v2_integration.py`,
  `tests/test_weather_v2_release.py`, `tests/test_weather_v2_preflight.py`;
- the 18 root JSON fixtures under `tests/fixtures/weather_v2/`, their README,
  `rendering/expected.json`, `rendering/extreme_hazards.json`;
- `docs/weather-logic-v2-editorial-contract-1.1.md`,
  `docs/weather-v2-integration.md`, `docs/weather-v2-release-report.md`, this runbook;
- the new workflow above.

The authoritative contract is included unchanged. Pre-existing unrelated files,
photo assets, .gitignore edits and backups are excluded. This is a local
**candidate**, not a claim that a real preflight has succeeded or production is
approved. No existing workflow is modified by the commit.

## Exact one-run procedure — ONLY after the next PO authorization

1. Obtain explicit authorization to publish this reviewed candidate/workflow and
   perform ONE diagnostic dispatch. This preparation grants neither. For a new
   workflow_dispatch workflow, ensure the workflow file is available on the
   repository's default branch before using the Actions UI; publication/any
   required merge needs separate permission. The local branch is not proof of
   the remote default branch, which was not queried.
2. In **zaporozsky/zvenigorod-weather-bot → Actions**, select
   **WeatherAPI V2 preflight without publishing**. Click **Run workflow**, select
   the reviewed revision containing this workflow and its V2 modules, and click
   the final **Run workflow** button ONCE. Do not select **Zvenigorod weather**.
   There are no inputs, key entry or Secret changes.
3. Wait for that one run to finish. Open the **Check WeatherAPI and V2 (one
   forecast request, no publication)** step. Record its run URL, checked commit,
   `request_attempts=1`, HTTP status, dates, two complete days, next-night
   availability, field states and `v2.status`. Inspect `category`, not just the
   UI color. Store no copy of the key or raw response.
4. If failed, report the safe category and stop. Do NOT use **Re-run jobs** or
   dispatch again without a new PO instruction. The rerun guard prevents a
   repeated API call within the same run; a new manual dispatch is not blocked.
5. After success, review the actual compatibility result and approve the exact
   release revision. Keep both V2 flags False and V1 default until a separate
   production-activation permission. Activation/rollback steps are in
   `weather-v2-integration.md`; neither workflow dispatch nor API success enables
   production sends automatically.

## Remaining production blockers

- New diagnostic workflow/candidate is local only: no push/merge authorized or
  performed, so the new workflow is not yet available remotely.
- No real preflight dispatched; actual two-day availability/fields/V2
  compatibility remain unverified. Existing Secret avoids any need for a new key.
- After that result, reviewed release publication and separate activation
  permission are required. V2_CHAIN_VERIFIED=False, V2_LIVE_ENABLED=False, V1
  default; no live process selector changed.
- Mocked delivery does not prove current Telegram/MAX permissions. No real
  messages are sent to obtain such proof in this preflight.
