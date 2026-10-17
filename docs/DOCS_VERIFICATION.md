# SereneDB docs verification

We connected the SereneDB docs MCP server (`serenedb-docs`) and used
`search_docs` / `read_section` to check our SQL against the official docs. All
four checks confirm our implementation is valid; native refinements are noted.

| # | What | Our implementation | Doc says | Status |
|---|------|--------------------|----------|--------|
| 1 | Any-term full-text + scorer | OR of `message @@ ts_phrase('word')`, ranked `BM25(idx.tableoid)` (`fts.py`) | `(p1 OR p2 ...)` is supported; native alternatives exist (see below) | ✅ Valid — keep; native form optional |
| 2 | Index build + refresh coverage | `CREATE INDEX ... USING inverted(...)` + `VACUUM (REFRESH_TABLE)` | REFRESH_TABLE publishes pending writes to readers → searchable **immediately** | ✅ Correct; 2.4s build was real & complete |
| 3 | Remote `read_parquet` + external-view index | `CREATE VIEW ... read_parquet([...])` + `CREATE INDEX ... inverted(...)` + `REINDEX INDEX` (`otel.py`) | CREATE INDEX on a view over `read_parquet` (local/S3) is supported; refresh via `REINDEX INDEX` / `reindex_interval` | ✅ Matches |
| 4 | Week bucket | `date_trunc('week', to_timestamp(ts))` (`bgl_trend_by_week`) | `date_trunc(part, timestamp)` correct (alias `datetrunc`); `time_bucket` also exists | ✅ Correct |

## 1. Any-term full-text search + scorer

Our query ORs per-term `ts_phrase` and ranks by `BM25(idx.tableoid)`. The docs
confirm an `(p1 OR p2 ...)` query is valid, so our approach is correct and is
what the demo uses (verified live).

**Native alternatives** (possible refinement, not required):
- bare-string match — `col @@ 'kernel parity error'` — analyzed into terms and
  OR-matched (Elasticsearch "match" semantics);
- `has_any_tokens(col, list)` / `ts_any(list)` for an explicit any-of-terms match;
- `::min_match(K)` to require at least K of the terms.

We keep the OR-of-`ts_phrase` builder in `fts.py` for the submission (it is
verified end-to-end); swapping to the bare-string / `ts_any` form is a one-line
change there if desired.

Source: serenedb.com/docs/sql/functions/search/full-text

## 2. Index build + refresh coverage (the 2.4s question)

`VACUUM (REFRESH_TABLE)` **publishes pending writes to readers**, so rows are
searchable **immediately** after it runs — the 2.4s full-corpus index build over
4.7M rows was real and complete, not lazy/partial. A background refresh also runs
on `refresh_interval` (default 1000 ms). Row identity is derived automatically,
so **no primary key is required** on the indexed table. For scoring, **BM25 and
TFIDF need only the `frequency` flag**; the `norm` flag is only needed for the
`lm_*` / `dfi` scorers (which we do not use).

Sources: serenedb.com/docs/sql/statements/vacuum ·
serenedb.com/docs/sql/indexes/inverted ·
serenedb.com/docs/sql/functions/search/scoring#requirements

## 3. Indexing external data (remote Parquet)

Building a `CREATE INDEX ... USING inverted(...)` on a **view over
`read_parquet(...)`** (local file or S3 URL) is supported; the index is a
snapshot refreshed by `REINDEX INDEX` or on `reindex_interval`. Our `otel.py`
does exactly this (view → inverted index on `Body` → `REINDEX INDEX`), so it
matches the documented pattern.

Source: serenedb.com/docs/sql/statements/create_index/inverted#indexing-tables-and-views

## 4. Date/week truncation

`date_trunc(part, timestamp)` is the correct function (alias `datetrunc`), and
`time_bucket` also exists. Our `bgl_trend_by_week` uses
`date_trunc('week', to_timestamp(ts))`, which is right.

Source: serenedb.com/docs/sql/functions/timestamp

---

All SereneDB-specific syntax remains isolated (`fts.py`, `otel.py`,
`bgl_trend_by_week`) so any future refinement is a one-line change.
