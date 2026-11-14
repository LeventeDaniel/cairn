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
