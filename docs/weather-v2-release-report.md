# Weather Logic V2 — Release Preparation report

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

Date: 2026-11-05, Europe/Moscow. Base HEAD:
`4777ae2a5af9dd19d6e6cb96c2ead01c4b2f3e0f`.

**Code preparation complete; production activation blocked pending the one real
WeatherAPI preflight and separate activation approval.** No production message,
workflow, merge, push, scheduler change or live V2 activation occurred.

## Final inactive-release checks

Fresh integrated worktree: 145 tests PASS, zero failures/errors/skips, with
socket connections and DNS denied. This includes all 18 document-verbatim
scenarios, both 32-case photo/text delivery matrices, photo season/approval/hash
checks, V2 live gates, rollback selection, preflight mocks and no-resend checks.
Nine deterministic mocked executions using the __main__ entrypoint produced
byte-identical V1 messages compared with diagnostic main. Twenty existing V1
function bodies are unchanged; only get_weather/send_post are parameterized.
All 163 approved photo files exist and match their manifest hashes.

Python compile/AST/tabnanny (21 files), JSON (20 fixtures), YAML (five workflows)
and critical Flake8 checks (E9,F63,F7,F82) PASS. Golden messages peak at 391
UTF-16 units; the extreme-hazard fixture is covered by the <=1024 assertion.
The default git diff --check reports only the 18 intentional Markdown hard
breaks already present in the approved contract. The contract bytes are
preserved; all other files pass the default check, and the full diff passes
with blank-at-eol explicitly exempted for those approved Markdown hard breaks.
No other whitespace issue, secret-pattern finding or unrelated file was found.
The original user worktree status and .gitignore/news.db hashes are unchanged.

## Specification and implemented decisions

The supplied `docs/weather-logic-v2-editorial-contract-1.1.md` is the approved
source, SHA-256:
`4c7445dc5bb8b01a3ab533258850c842f99c38be3bcf392746a9c02fe9e8a3d4`.
It was read, not edited. All seven accepted OPEN_RULE decisions supplement it;
OPEN_RULES is empty, CLOSED_RULES preserves all seven decisions. No additional
numeric editorial thresholds were introduced. Details and activation steps:
[weather-v2-integration.md](weather-v2-integration.md).

## Files changed in this preparation

| File | Purpose |
| --- | --- |
| weather_conditions.py | Shared precipitation names/icons, including mixed/generic types |
| weather_logic.py | Seven accepted evidence/ambiguity/quarantine/tie decisions with diagnostics |
| weather_rendering.py | Contract clothing, comment priorities, source icons, generic/mixed phrases, timed strong episodes, bounded compact hazard template |
| weather_v2_photo.py | Contract precipitation/photo precedence, ordinary existing V1 temperature thresholds, safe unsupported-scene fallback |
| weather_v2_integration.py | Unusable-day guard, private atomic snapshots, seven-day expiry and selective pruning |
| weather_v2_preflight.py (new) | Single-request, fixed-city days=2 diagnostic client; no delivery imports, retries or redirects |
| app_zngrd_weather.py | Future live snapshots are ephemeral and removed after success/failure; persistent live archive blocked until managed retention exists |
| tests/test_weather_logic.py | Old unresolved expectations replaced with the explicitly accepted results |
| tests/test_weather_rendering.py | Timed heavy peak, future-unapproved-rule guard |
| tests/test_weather_v2_integration.py | Accepted code-only hazard and timestamped snapshot expectations |
| tests/test_weather_v2_release.py (new) | Accepted matrices, clothing/photo boundaries, document-verbatim golden outputs, retention/privacy, preflight mocks, complete chain |
| tests/test_publication.py | Replace obsolete directory-only photo mock; keep all original delivery assertions |
| tests/fixtures/weather_v2/rendering/expected.json | Exact approved lines/comments/photo choices for all 18 scenarios |
| tests/fixtures/weather_v2/rendering/extreme_hazards.json (new) | Synthetic 24-hour extreme-hazard budget case |
| tests/fixtures/weather_v2/README.md | Accepted rules, approved fixture provenance and release coverage |
| docs/weather-v2-integration.md | Implemented dispositions, privacy/retention, root cause and activation handoff |
| docs/weather-v2-release-report.md (new) | This evidence summary |

Core's 18 original input/calculation JSON fixtures are unchanged. The contract
was supplied by PO during this preparation. Prior unrelated files, including
the existing .gitignore changes, were not included in the work. The later
Production Preflight preparation packages these V2 files into a local candidate
commit; it remains unverified against a real API response and is not activated.

## Verification

Final fresh-process suite: **128 methods, 0 failures, 0 errors, 0 skipped**.
Socket connections and DNS were denied around discovery and execution. This
includes all 18 approved scenarios, exact public comments and photo choices,
all seven accepted rule matrices, all registered codes, partial data, midnight,
clothing coincidence, privacy canaries, snapshot expiry and all 32 publication
success/failure combinations with/without photos.

Complete V2 app -> Core -> renderer -> real temporary approved/hash-matching
photo catalogue -> real four-destination sender -> mocked Telegram/MAX transport
was checked for all-success and unavailable-second-Telegram cases. Both MAX
attempts continue after the second Telegram fails. Payloads match, photos pass
through, order remains primary Telegram / second Telegram / primary MAX / second
MAX. No retry or V1 resend occurs. Ephemeral snapshots disappear after either
result. The future live gate is mocked ONLY inside tests; source flags stay False.

Maximum complete 18-scenario output (including supplied ancillary values):
**391 UTF-16 units**. Extreme hazard fixture: **1007 UTF-16 units**, preserving
all period warnings, both dates, uncertainty, limited coverage, wind/gust risk
and supported timing. If an even larger mandatory payload cannot be represented,
preparation fails before any send rather than truncating it.

AST parsing, compile, tabnanny, fixture JSON and git diff --check: PASS.
Ruff/flake8/Pylint are not installed; no packages were downloaded.

Byte comparison to base HEAD: weather.yml, weather_advice.py, original photo
selector and photo manifest unchanged. Address/photo mapping constants match.
All existing app function bodies except parameterized get_weather/send_post
match the base AST; entrypoint/refactoring changes preserve V1 as default.
No cron-job.org access or scheduling change occurred.

Read-only catalogue audit: all **163 approved files exist and match SHA-256**;
autumn 72, bare 33, summer 40, winter_snow 18. No archive file was written.
Local PHOTO_SEASON is unset; remote value is not inferred or changed.

Local detailed test evidence (temporary, not diagnostic forecast archives):
`/tmp/weather-v2-release-final-tests.txt`,
`/tmp/weather-v2-release-final-tests.json`,
`/tmp/weather-v2-release-static.json`.

## Original publication failures, not masked

Controlled isolated base HEAD with old test: **15 failures and 1 error**.
The same base app/selector with ONLY the stale photo mock replaced: **0/0**,
all 32 cases pass. Old mocks of os.listdir/os.path.exists did not satisfy the
new selector's PHOTO_SEASON/manifest/approval/hash contract. Correct text-only
fallback caused the test's mock MAX attachment assertions to fail; the sender
caught them and returned failure. The error case was the resulting unexpected
SystemExit for an assumed all-success photo run.

The fix mocks select_weather_photo at the delivery boundary; it does not bypass
checks in production. Separate catalogue tests exercise the real selector with
valid/invalid season, approval and hash data. Every original attempt/order,
shared text, failure status, upload-count and secret-log assertion remains.
Isolated proof directories:
`/tmp/weather-v2-publication-cause-base`,
`/tmp/weather-v2-publication-cause-fixed`.

## Retention and remaining limitations

Live diagnostic snapshots default to a private per-invocation temporary directory,
removed in finally on success/failure. Existing GitHub-hosted runners are also
ephemeral. Nothing is uploaded. Thus default live retention is one invocation,
less than the permitted seven days. Optional local archive snapshots are 0600,
atomic, expire within seven days and are pruned on access. This is not a physical
idle-time deletion guarantee: persistent live archive mode is explicitly blocked
until separately managed TTL/deletion is configured. No new janitor schedule or
workflow is introduced.

There is no cross-run idempotency ledger. An operator rerun/external duplicate
trigger after partial delivery can still duplicate messages; this preparation
preserves the no-retry contract and does not claim global exactly-once delivery.
Mocked transport checks do not prove current real Telegram/MAX permissions.

## Uncompleted real preflight / activation handoff

This report records the previous 128-test release-preparation phase. The latest
configuration audit and prepared diagnostic workflow are documented in
[Production Preflight runbook](weather-v2-production-preflight.md).

**Actual WeatherAPI requests remain 0.** No local key is needed: the existing
GitHub Actions Secret WEATHER_API_KEY is referenced directly by the new manual
workflow. Its publication and execution require the next separate PO permission.
The workflow uses one response for structure/field checks and pure V2 preparation,
without importing delivery code or sending any messages. No existing workflow is
edited. The lack of local credentials is not a request for a new key.

The local candidate commit is prepared before the authorized future preflight;
it is NOT evidence that actual account/two-day-field compatibility was checked.
After that one run, inspect the safe report and review the exact release revision.
Production activation still requires a separate authorization. Both V2 flags
remain False, V1 is the default, and rollback applies to the next invocation.
