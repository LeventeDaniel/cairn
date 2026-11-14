# Does Cairn save tokens? Results (2026-11-14)

**Verdict: not proven either way.** History cannot show a saving (no comparable baseline), and the A/B harness could not run (the CLI is not logged in, no API key). Nothing here supports a claim that Cairn saves a measurable amount.

## Measured (from ~/.claude/projects, 19 sessions, `bench/mine.py`, `bench/compactions.py`)
- Every session starts at about 80k tokens of context (median first reply 79.6k, range 78k-87k), before the user types anything. That is the harness (tools, skills, MCP list). Cairn's CLAUDE.md block is 4.6 KB, about 1.1k tokens, roughly 1.4% of that floor; its hooks add less per prompt. So Cairn is not what makes sessions start heavy.
- 11 compactions in history: context median 245k -> 98k. After a compaction the context never fell below ~83k (the same floor). Replies after each compaction: min 15, median 433.
- Before/after the kit (cutoff 2026-11-13 20:37): before n=15 sessions, 4305 turns, 0.22 USD/turn at an assumed price table; after n=4 sessions, 48 turns, 0.05 USD/turn. **Not comparable**: the "before" set holds 2 very long Opus-heavy sessions (3397 turns, avg context 531k); the "after" set is four 6-18 turn Sonnet sessions. Only the like-for-like slice is usable: Sonnet 5.5 sessions in the cairn repo, 0.047 USD/turn before vs 0.05 after, i.e. no difference, on tiny samples.
- Cairn's own ledger and `usage-days.json` started on 2026-11-14, so there is no Cairn-triggered compaction yet to measure.

## Not measured
- Any A/B with the same tasks. `bench/run.py` exists (4 tasks, Cairn config on/off, `claude -p --output-format json`); `--dry-run` prints ~2.61 USD for 2 runs per task per arm on Haiku. It needs a logged-in CLI or ANTHROPIC_API_KEY, then `python bench/run.py --runs 2 --model haiku`. It writes the result into the pane.
- Real prices: cost columns use an assumed Sonnet/Opus/Haiku table, not the 5.5 prices. Ratios between sessions are more trustworthy than the dollars.
- Quality effects of compaction (lost context), and the cost of Cairn's hooks per prompt.

## Estimates the data touched
- The ledger assumes 10 replies after a compaction. History shows at least 15 and a median of 433, so 10 is conservative and stays. Savings still count only Cairn-triggered compactions.
- The pane now has a separate "Measured" block (cyan, from state/measured.json) apart from the estimates.

## Improvements the data suggests
1. The ~80k floor dominates every small session; trimming Cairn's block would save ~1% of it. Real cuts have to come from the harness side (MCP servers, plugins, skills listed): run `context-audit`.
2. Run the A/B once logged in; it is the only way to get a defensible number.
3. Keep logging ledger events for a week, then compare Cairn-compacted sessions to app-compacted ones.
No code change beyond the measured pane block was justified by the data.

## A/B run (2026-11-14, `bench/run.py --runs 1 --model haiku`, 4 tasks, 1 run per task per arm)
Measured from `claude -p --output-format json` (reported cost, real total ~0.05 USD; the estimate of 1.30 was far too high).

| | Cairn off | Cairn on |
|---|---|---|
| cost per run | $0.0056 | $0.0070 (+24%) |
| turns per run | 3.0 | 3.5 |
| avg context per turn | 36.5k | 37.2k (+2%) |
| output tokens per run | 553 | 1215 |

Reading: Cairn did **not** save here; it cost slightly more (extra turns and output from its CLAUDE.md rules and hooks, +0.7k context per turn). Context per turn differs by only 2%, so the CLAUDE.md block is cheap; the extra cost comes from more turns/output. Caveats: n=4 per arm, one run each, one cheap model, tiny tasks where compaction never triggers (Cairn's main mechanism is untested), run-to-run noise on 3-turn tasks is large. Headless start context is ~36k, not the ~80k seen in the desktop app (that part is the app's own prompt).
Verdict stands: not proven to save; on short tasks it costs a little more. Its value case (compaction, cold-cache warnings on long sessions) needs long-session data.

## Round 2 (2026-11-14): why Cairn cost more, fixes, longer tasks
**Cause found (kit, not the model):** the session-start hook registered every new folder (the bench's temp dirs) as a repo and told Claude to "ask the user for a one-line purpose". That produced extra output and turns in every scratch session (first run: output 1215 vs 553 tokens). Fix: kit commit `c79ad00` stops registering temp or non-git folders (test added). Also removed the 4 junk bench entries from REPOS.md. Tightened the Cairn CLAUDE.md block (`b01e3c3`: no commentary on plain task work, routing line only when routing).

Re-run, Haiku, 3 arms (off / old block / lean block), n=12 short runs per arm and n=4 long runs per arm (long = 12-file audit, csv stats refactor; ~30 turns). Real spend about 0.4 USD total.

| | off | old block | lean block |
|---|---|---|---|
| short: cost/run | $0.00586 | $0.00645 (+10%) | $0.00657 (+12%) |
| short: output tokens | 663 | 763 | 763 |
| short: cache write | 22.9k | 25.5k | 25.8k |
| long: cost/run | $0.01346 | $0.01408 (+5%) | $0.01400 (+4%) |

Reading:
- The +24% shrank to about +10% after the registry fix. The rest is fixed injected context: about 2.6k extra cache-write tokens per session (CLAUDE.md block ~1.1k, router and hook notes). It shrinks to +4-5% on 30-turn tasks, because it is paid once.
- The lean block changed nothing measurable (763 vs 763 output tokens); the difference between the two blocks is inside noise.
- Hooks plus CLAUDE.md can only add cost; their benefit is behaviour (routing, handoff), not tokens. **Cairn does not save tokens by itself; it costs 4-10% extra fixed overhead.**
- Where a saving could exist: compaction at clean breaks, idle past-TTL compaction, cache warnings. These are mod features and do not run under `claude -p` (no mod, and a 30-turn task never nears compaction), so they are NOT measured here. Their value is the ledger's estimate (10 later replies x removed tokens at the cache-read price), nothing more. The measured fact behind it: compactions in history removed a median 147k tokens and were followed by 15+ replies.
- Not proven where it cannot be: a headless benchmark cannot show the mod's savings; that needs a week of ledger data from real sessions (Cairn-triggered vs app-triggered compactions).
Caveats: Haiku only, tiny tasks, n small, haiku cost from the CLI's own reported total.

## Round 3 (2026-11-14): compaction economics, headless (`bench/compact.py`) - INCONCLUSIVE
Build a big context (30 files read), then 8 follow-ups via `--resume`, straight vs after `/compact`, Cairn off in both. Real cost: 1.37 USD straight vs 1.55 USD compacted (includes 0.15 for the compaction itself); follow-ups alone 1.28 vs 1.30 although context was 271k vs 107k at the first follow-up. So compaction did not make the follow-ups cheaper here. Likely reason: each `claude -p --resume` call re-creates the prompt cache (cost looks like cache-write per call, ~0.16 USD per follow-up), so context size is paid at write price instead of the cheap read price Cairn's ledger assumes. That is a headless artefact, not evidence about interactive sessions, where replies within the cache TTL read at ~10% of the price. Single run, no repeat. The cost estimate was 0.8 USD; real 2.9 USD (3.5x over), so the harness's estimator is unreliable for resume runs.
Spend so far: about 3.4 USD of the 5 USD approved (0.05 + 0.4 + 2.9). Stopping here: the remaining budget cannot buy a repeat of this experiment, and headless runs cannot exercise the mod (idle compaction, cache warnings, model routing).

## Round 4 (2026-11-14): Sonnet, short tasks, n=8 per arm
Cairn off $0.0982/run, on $0.1049/run (+7%); turns 2.5 vs 2.5; output 324 vs 376 tokens; cache write 21.7k vs 23.5k (+1.7k tokens of injected context). Same shape as Haiku (+10%): a small fixed overhead, no saving on short tasks, on a second model. The round used about 7 points of the Pro plan's 5-hour limit (52% -> 59%, other sessions included), so with the stop line at 70% I did not run Opus or long Sonnet tasks. The plan, not the money, is the binding limit: Pro, weekly all-models at 57%.
Conclusion across Haiku and Sonnet: hooks + CLAUDE.md cost +7-10% on short tasks and +4-5% on 30-turn tasks; the overhead is ~1.7-2.6k cache-write tokens per session. Remaining lever to cut it: shrink the injected block further (routing table into a skill loaded on demand). Not done: it would change routing behaviour, which this benchmark cannot judge.

## Round 5 (2026-11-14): slim block (kit `5f57eb7`), Haiku short, n=12 per arm
CLAUDE block 4.5 KB -> 2.0 KB; routing table and spawn rules moved to the on-demand `route` skill (loaded only when an instruction is not a plain continuation). Result: cache write overhead 2.6k -> 1.3k tokens per session (off 22.2k, on 23.5k). Cost per run: off $0.00566, on $0.00617 (+9%, was +10-12%). Turns 3.17 vs 3.67 and output 595 vs 830 tokens: with 3-turn tasks one extra turn is +10% cost, and that noise is larger than the saving from 1.3k fewer tokens, so the cost change is NOT distinguishable from the earlier round. What is measured: injected context halved. What is not: a reliable cost difference at this sample size. Behaviour risk: the block no longer lists the routing rows, so routing now depends on the model invoking `route`; not tested here (needs interactive sessions).

## Round 6 (2026-11-14): long multi-stage scenario, Haiku (`bench/scenario.py`)
Five stages (package, tests, feature, docs, bugfix) with an idle gap of 330 s (past the 5-minute cache TTL) before stage 3. Arm A: Cairn off, one session continued with `--resume`. Arm B: Cairn on, each stage in a fresh session that reads SESSION.md and updates it (the handoff Cairn does). Correctness: a check command per stage.

| run | A one session | B handoff stages | correct (A / B) |
|---|---|---|---|
| 1 | $0.074, 117 s | $0.052, 156 s | 4/5, 4/5 (stage-1 check was a broken command, so these are false alarms) |
| 3 (checks fixed) | $0.106, 120 s | $0.049, 151 s | 5/5, 5/5 |
| 2 | cut off by the 5-hour limit in arm B (two stages recorded $0): invalid, kept as results-scenario-run2-partial.json | | |

Reading: with handoff stages, total cost was 30% (run 1) and 54% (run 3) lower, same correctness, but about 25% more wall time (each fresh session re-reads state). Per-stage cost in A grows with each stage; in B it stays flat at ~$0.008-0.011.
Caveats, important: (1) A pays an artefact of headless `--resume`: every call re-writes the prompt cache for the whole growing context (round 3). Interactive replies within the TTL read it at ~10% of that price, so the real gap is smaller than shown; how much smaller is not measured here. (2) B's gain comes from small fresh contexts, which one can also get without Cairn by starting fresh sessions by hand; it shows the handoff pattern works, not that Cairn does it better. (3) The mod's compaction, idle compaction and cache warnings did not run (no mod under `claude -p`). (4) The 'ctx' numbers in the json sum all inner turns of a call and are not a per-turn context curve. (5) 2 valid runs, Haiku, small project.
What the data says to build: handoff via SESSION.md plus fresh sessions per stage is the one measured saving (0.3-0.5x cost); a "stage boundary" nudge (suggest a fresh session + handoff when a stage ends and context is large) is the feature this supports. Not built yet.
