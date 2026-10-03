# Funding Wire

A public-source funding feed for the Möbius owner. The app UI reads `feed.json` from its own storage and keeps saved companies separately. The seed `initial-feed.json` is a reviewed startup dataset for first installation; it is **not** an app source file or a live feed until the installer/owner writes it to app storage.

## Refresh contract

`collector.py` fetches eight public RSS feeds, strips HTML to bounded text, and writes **candidate evidence only**. Keyword filtering is a recall aid, not a funding classifier: acquisitions, venture-fund closes, historical mentions, etc. can be in the candidate file. The supervised `job.py` stores one snapshot at `evidence/<content-hash>.json` and starts one app-owned chat per new evidence/retry attempt through `POST /api/app-chats/start`. An active review is reused, unchanged evidence is skipped after a successful review, and a stopped review can be retried. The app-owned agent follows `refresh-prompt.md`, verifies actual company financings from publisher evidence, and CAS-merges `feed.json` by ETag. It leaves the prior verified feed intact on failure. The job does not run an AI provider CLI, keep credentials, or directly write the feed. A successful `run-job` response means **admitted**, not refreshed; the UI should subscribe to `feed.json` for the committed result.

The cadence should be declared in `mobius.json` with `schedule.job: "job.py"`, such as daily `30 5 * * *`. List `collector.py` and `refresh-prompt.md` in `source_files`. Do not also list `job.py`: `schedule.job` already includes it as an install-managed file. No extra manifest permissions are needed for the job to write its **own** app storage or start its **own** app chat; do not grant cross-app, proxy, secrets, or notifications permissions. The supervisor supplies short-lived `APP_TOKEN` and app id; never run `job.py` manually with owner credentials. A manual Refresh button can POST `/api/apps/{id}/run-job` with the app's scoped token. The app chat consumes the owner's configured agent provider/model usage on each newly admitted review; it does not require a paid news-data subscription. Daily cadence means roughly one background agent turn whenever source evidence changes; repeated unchanged evidence costs no new agent turn after a successful review. A manual retry after a failed review may consume another turn. Exact token cost depends on feed length and the owner's model. If all feeds fail, the job exits nonzero and leaves `feed.json` unchanged. Individual source failures are recorded in `sources` when another feed succeeds.

Publication dates are report dates, not close dates. Coverage is uneven and never exhaustive. The regional labels in records require publisher evidence about company geography; a publisher's region alone is not enough. Seed records with unknown investors/stage leave them unset rather than guessing. `initial-feed.json` contains 26 publisher-linked deals across Africa, Asia, Europe, Latin America, North America and Oceania (one US-publisher story without explicit company location uses Not stated).

## Tests

`python -m unittest -q test_collector.py`

Tests cover no automated deal extraction, old-story exclusion, article evidence retention, all-source failure preservation, and idempotent chat admission. They do not prove a live agent turn or installed schedule; those need the parent to apply the app and inspect a real refresh after activation.

## Visual verification
Phone and desktop renders were checked. Search, region filtering, empty results, saved-company persistence after reload and removal were exercised in the authenticated browser. `icon.png` is original code-drawn app branding (three ascending bars), not sourced artwork.

## Amount ordering and valuation

Latest sorts by publication date. Highest raise compares `amount_value` in
`amount_currency` using a dated `fx.json` USD-per-unit reference cache, fetched
from Frankfurter's ECB provider on daily/manual checks. Display keeps the
original currency and approximate qualifiers; comparison uses current reference
rates, not historical deal-date rates. A missing amount, unconfirmed currency or
unsupported rate sorts after comparable amounts, latest first. Bare dollar
symbols are never silently interpreted by the UI. `feed-order.mjs` owns this
contract without mutating records or saved snapshots.

The reviewer records only expressly disclosed current-financing `valuation`,
`valuation_basis` (Pre-money/Post-money/Not stated), and `valuation_sources`.
It must not infer a valuation from raise amount or bring forward an old round's
valuation. Legacy records render as unknown until source-reviewed enrichment.
Valuation evidence links are displayed alongside the report's original sources.
The refresh merge preserves additional fields in existing records.

Tests: `node --test test_feed_order.mjs`; Python tests additionally check the
rate direction and failed-cache preservation. An exchange-rate fetch failure
keeps the prior cache and does not block source review. The UI displays the rate
date, making older retained reference rates explicit.

## Historical coverage

Daily RSS checks continue accumulating reviewed records, but a wider age limit
alone cannot reach articles omitted from a publisher's finite feed. Historical
backfill needs publisher archives/pagination, source verification and the same
conditional merge preserving existing reports and saved companies. Backfill is
separate from the daily collection path; never re-upload initial-feed.json over
an already-live feed.

Facility ceilings remain visible as debt reports, but unknown drawn proceeds are not ranked as cash raised. Source-reviewed amount evidence is linked alongside valuation evidence. Historical and valuation research artifacts are outside the source tree at /data/shared/funding-wire/research; apply regenerates .gitignore, so do not rely on ad-hoc ignore entries for mutable artifacts.

## Six-month archive review and broader discovery

`archive.py` gathers public evidence from paged publisher RSS archives with a
fixed April2–October2 2026 review window, durable per-source checkpoints and
explicit repeated-page, chronology, cutoff and fetch-gap reports. This is a
bounded historical operation, not a promise of exhaustive six-month coverage.
Read the collection artifact's source health before describing its reach.
Mutable evidence/review artifacts belong outside the app source tree.

`discovery.py` follows original report links from Seb Johnson's public Scaling
Europe newsletters. In the daily job this is a rolling, bounded discovery
addition to all existing RSS sources, not a replacement or a funding-data
parser. Each original report still goes through the same source-review agent;
newsletter amounts/valuations never become verified records by copying them.
The supervisor's `APP_JOB_STATE_DIR` owns the discovery cache. Source errors
remain visible and do not erase publisher evidence or the previous feed.

Historical reviewers classify each candidate as a verified company financing,
excluded non-financing, or unresolved evidence. `review_import.py` applies their
explicit records/duplicate targets with a fresh feed ETag and re-merges on a
concurrent daily update. It preserves current check timestamps, evidence hash,
known fields and all existing reports. It does not write saved.json. Different
rounds of one company remain separate; only reviewers decide semantic matches.
Reviewed corrections use an optional `replace_fields` map: unlike ordinary
missing-field enrichment, these exact replacements can deliberately clear an
amount or correct a known field. The map applies last and is never stored in
the report. Unmentioned fields and owner notes remain intact.
Run `python3 review_import.py 133 REVIEW.json --history --preview` before the live import.

The daily feed retains its1000-record bound. Verified older reports live in
`history-reports.json`; the UI subscribes and searches/sorts/filters both as
one ledger. Historical import enriches existing live matches in place and
archives new historical records, without moving or removing live reports.
Archive acceptance precedes any live enrichment; interrupted batches are
replayable, additive and idempotent. Daily review checks matching historical
companies to avoid reintroducing the same round. It does not load the entire
history into model context. At the daily feed bound, report a retention error
rather than silently clipping any partner report.
Cursive's non-cash GPU access is not a cash funding round. Facility ceilings,
venture fund closes, targets and cumulative capital stay distinct from current
company-round proceeds. Unknown valuations remain unknown.

Tests additionally cover additive/idempotent history merges, explicit
same-round duplicates, unresolved targets, concurrent daily writes, preservation
at capacity, discovery failure isolation and richer original-story deduplication.
