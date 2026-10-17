# SereneDB docs verification

We connected the SereneDB docs MCP server (`serenedb-docs`) and used
`search_docs` / `read_section` to check our SQL against the official docs. This
file records the four things we verified, our current implementation, and the
doc answer. Update the "Doc says" / "Status" columns from your MCP lookups.

| # | What | `search_docs` query | Our implementation | Doc says | Status |
|---|------|---------------------|--------------------|----------|--------|
| 1 | Any-term full-text + best scorer | `full-text query operators ts_query any term`; `BM25 scorers` | OR of `message @@ ts_phrase('word')`, ranked `BM25(idx.tableoid)` (`fts.py`) | _(fill)_ | _(fill: keep / swap to native any-term op / change scorer)_ |
| 2 | Index build + refresh; coverage | `CREATE INDEX inverted VACUUM REFRESH_TABLE` | `CREATE INDEX ... USING inverted(id, message english)` + `VACUUM (REFRESH_TABLE)` (`fts.py`, `load_logs.py`) | _(fill)_ | _(fill: does REFRESH index all 4.7M rows synchronously? 2.4s build — incremental/background?)_ |
| 3 | Remote `read_parquet` + indexing external data | `read_parquet remote S3 HTTPS`; `Indexing External Data REINDEX` | `CREATE VIEW ... read_parquet(['<url>', ...])` + `CREATE INDEX ... USING inverted(TraceId, Body english)` + `REINDEX INDEX` (`otel.py`) | _(fill)_ | _(fill: multi-file syntax? REINDEX vs VACUUM for views?)_ |
| 4 | Week bucket for week-over-week | `date_trunc week truncate timestamp` | `date_trunc('week', to_timestamp(ts))` (`bgl_trend_by_week`) | _(fill)_ | _(fill: date_trunc supported? or time_bucket?)_ |

## Notes to resolve

- **#1** — if there's a native any-term query function (e.g. a `ts_query('a b c')`
  that ORs terms), swap the single `fts.search` builder in `fts.py`. If a specific
  BM25 scorer is recommended for short text, set it there too.
- **#2 (important)** — the full-corpus index build reported only **2.4s** for
  4.7M rows. Confirm `VACUUM (REFRESH_TABLE)` makes **all existing rows**
  searchable immediately (not lazy/background). If it is incremental, document the
  step needed to force a full build before querying.
- **#3** — confirm the exact multi-file remote syntax (`read_parquet([...])` vs a
  glob/range) and whether external-view indexes refresh with `REINDEX INDEX`
  (what `otel.py` uses) rather than `VACUUM (REFRESH_TABLE)`.
- **#4** — if `date_trunc('week', ...)` is not the SereneDB spelling, change the
  one expression in `bgl_trend_by_week`.

All SereneDB-specific syntax is isolated (`fts.py`, `otel.py`,
`bgl_trend_by_week`) so a doc correction is a one-line change.
