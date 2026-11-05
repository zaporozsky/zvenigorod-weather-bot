# Weather Logic V2 — Release Preparation

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

Status: prepared locally; production NOT activated. The base is
`4777ae2a5af9dd19d6e6cb96c2ead01c4b2f3e0f`. The authoritative specification is
[Editorial Contract 1.1](weather-logic-v2-editorial-contract-1.1.md), supplied by
PO. Seven accepted OPEN_RULE proposals below supplement it. The authoritative
contract itself is not edited by this release.

`V2_LIVE_ENABLED=False`, `V2_CHAIN_VERIFIED=False`, V1 default and existing
workflow/recipient/PHOTO_SEASON configuration remain in place. No merge, push,
workflow execution or real publication is part of preparation.

## Seven PO decisions implemented

`weather_logic.OPEN_RULES` is empty because all seven decisions have code and
regression tests. `CLOSED_RULES` retains their identifiers and dispositions.
Source values, missing/null/invalid states, codes and disagreement diagnostics
remain separate from public wording.

| Accepted rule | Implemented decision |
| --- | --- |
| PRECIPITATION_EVIDENCE_UNRESOLVED | Known rain/snow code + positive matching quantity: expected if probability absent or >=70, possible at lower probabilities. Lower probability with positive quantity is diagnosed. High probability without positive quantity remains possible. Code alone supports possible occurrence. Without a precipitation code, probability-only rain/snow is possible; quantities with unconfirmed phase or competing rain/snow signals become generic possible precipitation. Percentages/amounts are never invented. Heavy-snow confirmation retains the stricter Contract gate. |
| PRECIPITATION_TYPE_CONFLICT | Rain/freezing code with positive snow quantity becomes generic possible precipitation. No conversion of mm to cm or temperature-based phase inference. Freezing code retains a separate possible icing warning. Conflicts suppress phase-specific photos. |
| PRECIPITATION_KIND_UNRESOLVED | Sleet/ice pellets use their source type. Positive precip_mm supports occurrence, otherwise possible. Rain/snow probability is not used as their specific probability. |
| AMBIGUOUS_SNOW_INTENSITY | Moderate-or-heavy source intensity is preserved in diagnostics and supported wording; the full snow confirmation gate permits only a POSSIBLE heavy-snow warning. Without confirmation: possible snow, no intensity or heavy warning. |
| HAZARD_CONFIRMATION_UNRESOLVED | Thunder/blizzard/blowing snow/freezing fog/ice pellets/dust/sandstorm codes support possible phenomena. Unambiguous heavy rain requires >=70 rain probability and positive precip_mm for expected heavy rain; otherwise possible. Moderate-or-heavy rain never becomes definite heavy rain. |
| INTENSITY_PREVALENCE_UNRESOLVED | Equal counts leave generic intensity and an explicit tie diagnostic. The histogram remains intact. A supported heavy episode has its actual hour(s), never expands to the whole period. |
| DUPLICATE_IDENTITY_UNRESOLVED | Invalid redacted duplicates remain quarantined as a whole timestamp. DUPLICATE_IDENTITY_QUARANTINED records the reason; remaining hours can form an explicitly partial period. Invalid strings are not retained or compared. |

No additional numeric editorial thresholds were introduced. Contract §6 supplies
0/8/5 °C, wind 20/30, gusts 30/40 km/h, two consecutive hours and the feels-like
difference. Contract §9 supplies the three-hour precipitation photo threshold.
Ordinary photo thresholds reuse existing V1: very_cold below -10, cold below 5,
unusually_warm from 30, sunny_warm from 18 °C. No landscape-season inference.

## Rendering and photos

- Four periods: D06–11, D12–17, D18–23 and D+1 00–05; D is fixed in Moscow.
- Temperature: original spread >=3 gives range, otherwise half-away-from-zero
  rounded median; at least four valid temperatures. Actual is_day controls
  sun/moon; TEMP_JUMP is diagnostic only and never corrected automatically.
- Contract §6 clothing factors must coincide in source hours. General advice
  requires two adjacent hours; isolated advice carries a clock qualifier.
  Missing feels-like is not invented. Wind 20 alone cannot recommend a jacket.
- Hazard comments precede ordinary weather. Prolonged precipitation precedes
  unrelated wind; concurrent wind/rain are combined (scenario 14). All mandatory
  warnings remain in the period lines, even when another hazard wins the comment.
- All 18 period lines, comments and photo choices match Contract §10 verbatim.
  The fixture is checked directly against the approved Markdown document.
- Contract §9 photo precedence: freezing/conflicts/unknown daytime -> text only;
  agreed snow >=3 hours or confirmed strong snow -> snowy; agreed rain >=3
  hours -> rainy; brief/possible rain -> small_rain_possible; then strong wind;
  then existing temperature/ordinary scenarios. Next-night snow does not choose
  a daytime photo. Approval, hash and PHOTO_SEASON checks remain in the original
  unmodified selector. Missing eligible photo means text-only delivery.
- Entire message <=1024 UTF-16 units; comment <=180, no arbitrary slicing.
  Budget tiers remove ancillary details, use grouped clock/likelihood hazard
  wording, then drop the comment and optional greeting. Generic rain icons also come
  from the shared registry; actual light/moderate source icons remain distinct. Date, next-night date,
  uncertainty, brief duration where established, partial coverage and all hazard
  names survive. An unrepresentable mandatory payload blocks before sending.
  An extreme 24-hour hazard mixture is explicitly tested, including high wind
  and gusts in all four periods.

## Diagnosis, privacy and retention <=7 days

Snapshots contain only Core's validated projection and decisions, static
condition labels, safe diagnostic codes and public rendering. No raw provider
body/text, tokens, authorization headers, destination identifiers, user/location
records or exception strings enter the snapshot. Invalid field values are
redacted while their states/reasons are retained. No network operation at import.

`save_snapshot` writes a unique atomic JSON file with permissions 0600 in a
private 0700 directory. It stores created_at/expires_at UTC, with maximum expiry
of seven days, and prunes expired owned files on access. It never follows a
snapshot symlink or deletes unrelated filenames. A forged future expires_at
cannot extend created_at+7 days. Failed writes leave no partial file.

**Physical retention guarantee:** the future live branch uses a private
TemporaryDirectory and removes it on success/failure. Existing GitHub-hosted
runners are ephemeral; no diagnostic artifact is uploaded. This keeps live
snapshots only for the invocation, which is less than seven days. No new cron or
workflow retention setting is needed or changed.

The explicit offline --diagnostics-dir option is a local archive with expiry and
access-time cleanup. It does NOT promise deletion while the machine is idle.
Persistent live --diagnostics-dir is blocked until a separately approved managed
TTL/deletion service guarantees physical removal within seven days. Merely
putting expires_at into JSON is not presented as a deletion guarantee. Review any
future artifact upload/log retention separately before enabling it.

## Existing test_publication.py failures: cause and production impact

The old test's photo=True branch mocks os.path.exists, os.listdir and random
choice as though the old directory-only photo selector were still in use. The
current selector requires a valid PHOTO_SEASON plus approved/hash-matching
manifest entries and does not use os.listdir. With an unset/invalid season it
correctly returns None. The old test still asserts photo attachments and two
uploads. Its MAX mock raises an assertion on text-only payloads; the real sender
correctly catches those per-destination failures, giving 15 failing subcases and
one unexpected SystemExit error when no delivery failure was requested.

Controlled proof on isolated base HEAD: original test -> exactly 15 failures and
1 error; ONLY replacing that stale photo-selection mock -> all 32 combinations
pass on the identical base application/selector. No production code is changed
to bypass season/approval/hash checks. The updated test isolates delivery by
mocking select_weather_photo, while separate temp-catalogue tests exercise real
approval/hash/season validation. All original attempt/order/payload/log/failure
assertions remain. These failures were test-harness incompatibility, not evidence
of a Telegram/MAX transport regression. Real transport access is not proven by
mocked tests. Production needs eligible catalogue entries; otherwise deliberate
text-only fallback remains.

Local catalogue read-only audit: 163 rows approved, all 163 files present with
matching hashes; autumn 72, bare 33, summer 40, winter_snow 18. PHOTO_SEASON is
not set in this local shell; remote configuration was neither read nor changed.

## WeatherAPI preflight through the existing GitHub Secret

The application workflow already maps `secrets.WEATHER_API_KEY` to the same-name
process environment variable. The dedicated new
`.github/workflows/weatherapi-preflight.yml` uses this Secret directly, only on
its one diagnostic step. No local key export, new key or Secret change is needed.
Existing workflows are not edited. Manual dispatch and any workflow publication
remain subject to the next PO authorization; preparation performs zero API calls.

See [Production Preflight runbook](weather-v2-production-preflight.md) for the
exact single-run instructions, exit categories, remaining blockers and complete
release-candidate file list. The client checks both calendar days, all 24 unique
hour timestamps per day, the following night, required field states and V2
compatibility using the same response in memory. It never imports publication
code, sends messages, follows redirects or retries. Missing fields remain explicit
and fail the strict preflight without inventing values. A successful check does
not activate V2 or prove live delivery permissions. No forecast body/text or
snapshot is uploaded or logged.

## Verification and activation handoff

The full local suite is run with socket connects and DNS denied; logs and exact
results are recorded in the release report. Syntax, compile, indentation, JSON
and diff whitespace checks run locally. No packages are downloaded for lint.
Existing scheduling, address constants, destination order, MAX implementation,
V1 weather normalization/advice and the original photo selector remain unchanged.

Activation is a separate authorization, after the missing live preflight is
completed and the release diff/test evidence reviewed:

1. Add every V2 module, fixture/test and the authoritative contract to the release
   candidate commit. Review the exact commit and deploy only
   the approved revision. Do not include pre-existing unrelated workspace files.
2. Record the single successful days=2 preflight and confirm required fields or
   documented missing-field fallback. Confirm the intended PHOTO_SEASON through
   the operator; do not alter it based on forecast snow.
3. Under separate production-activation approval, set V2_CHAIN_VERIFIED=True and
   V2_LIVE_ENABLED=True in weather_v2_integration.py. They remain False now.
4. Pass WEATHER_LOGIC_VERSION=v2 to the existing process. GitHub repository vars
   are not automatically exported: a narrowly scoped future env wiring change
   is needed if using an Actions variable. Do not alter workflow triggers,
   cron-job.org, recipients or scheduling. The future authorized env entry is:

   ```yaml
   WEATHER_LOGIC_VERSION: ${{ vars.WEATHER_LOGIC_VERSION || 'v1' }}
   ```

   Then the operator sets that repository variable to v2. This env entry and
   variable switch are NOT applied in this preparation.
5. Let the next existing authorized run publish once; inspect all four results.
   Any recipient failure returns failure only after four attempts. Do not rerun
   a partially successful run automatically.
6. Roll back the NEXT invocation with WEATHER_LOGIC_VERSION=v1 (or explicit
   --logic-version v1). V1 does not import V2 implementation modules on this path.
   There is no automatic V1 resend after V2 preparation/delivery failure.

No cross-run idempotency ledger is added. Manual reruns or external duplicate
triggers can still duplicate messages. This release preserves no-retry behavior;
it does not claim exactly-once delivery across separate invocations.
