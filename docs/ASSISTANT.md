# The question assistant (Phase 7)

Ask in plain English ("Which payouts are missing from the bank?"). You get the answer **and the exact SQL that produced it**.

## How an answer is made
1. **Refuse early.** Questions that ask to change data, read files or reach outside the warehouse are turned down with a reason before any SQL exists.
2. **Plan.** A deterministic planner composes SQL from fixed vocabularies (finding classes, merchants, time words, measures). An optional language-model provider sits behind the same interface for questions the planner does not know; it needs an API key supplied through the environment and is **not exercised in CI or in the numbers below**.
3. **Validate (three independent layers).** Whatever wrote the SQL, it must pass all of these:
   - *Syntax tree check* (sqlglot): one `SELECT` only, no write or DDL nodes, only allow-listed tables, no file-reading functions.
   - *Plan check*: DuckDB `EXPLAIN` is read back; scans of anything outside the allow-list, file readers, or an estimated row count above the limit are refused.
   - *Engine lock*: the connection runs with external access disabled and configuration locked, so even a validator bug cannot read or write a file.
4. **Run with a cap.** Results are capped; the query fetches one extra row so the screen can say honestly when it was truncated.
5. **Log.** Question, SQL, outcome, row count and time go to `ops.ask_log`.

## How it is graded
| Check | Size | Result |
|---|---|---|
| Evaluation set (answers compared with reference queries) | 45 questions | 45 of 45 correct |
| Red team: unsafe SQL (writes, DDL, file reads, multiple statements, comment tricks, unlisted tables, expensive cross joins) | 54 cases | 54 of 54 refused |
| Red team: unsafe natural-language requests (delete, drop, export to file, change settings) | 14 cases | 14 of 14 refused |

Both are enforced by `tests/test_ask.py`. What this does **not** show: the evaluation questions were written by the same people who wrote the planner, so 45 of 45 measures regression protection and coverage of the supported vocabulary, not how it copes with arbitrary phrasing. The language-model path is untested against a live model.

Run it yourself: `python -m trueup ask-eval --db data/ui/serve.duckdb`, `python -m trueup ask --db data/ui/serve.duckdb "How many open exceptions are there?"`.
