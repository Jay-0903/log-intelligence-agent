# Optional: Working with Huge Datasets (separate award)

This is the **optional** "Working with Huge Datasets" award — judged separately,
it does **not** change the main score. It queries 50 billion rows of
OpenTelemetry logs that live as Parquet in public S3, **without downloading
them**: SereneDB reads remote Parquet in place (zero-ETL).

Attempt this only after the core (BGL + OpenStack) works — it does.

## What the data is

- 50 Parquet files, `part_000.parquet` … `part_049.parquet`, ~1 billion rows
  each, sorted by timestamp (one day of OTel demo-app telemetry).
- Base URL: `https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/`
- Record fields: `Timestamp, TraceId, SpanId, TraceFlags, SeverityText,
  SeverityNumber, ServiceName, Body` (+ `*Attributes` maps). **`Body`** is the
  searchable text field.
- Scale by file: `part_000` ≈ first 30 min; `part_000..009` ≈ first 5 hours;
  all 50 ≈ full 24h. **One file is already ~1 billion rows** — start there.

## How to run it

The remote read needs network access to S3 (so run it on your machine, not an
isolated build box). No download, no mount — SereneDB reads the URL directly.

```sh
# One file (~1B rows): create the view + timed aggregations
python load_logs.py --otel-files 1

# Five hours of data + full-text on Body (reports query times):
python load_logs.py --otel-files 10 --otel-index
```

Or via MCP (so Claude can drive it):
`otel_setup(n_files=1, build_index=true)` → `otel_aggregate(metric="service")`
→ `otel_search(phrase="timeout")`.

## What happens under the hood

```sql
-- 1. Point at the remote files (nothing downloaded):
CREATE VIEW otel_logs AS
    SELECT * FROM read_parquet('https://.../part_000.parquet');
-- reading several at once: read_parquet(['.../part_000.parquet', '.../part_001.parquet'])

-- 2. Prove it works small (timed):
SELECT COUNT(*) FROM otel_logs;
SELECT ServiceName, COUNT(*) AS n FROM otel_logs GROUP BY ServiceName ORDER BY n DESC LIMIT 10;

-- 3. Make Body searchable (index streams from source; only the index is local):
CREATE INDEX otel_idx ON otel_logs USING inverted(TraceId, Body english);
REINDEX INDEX otel_idx;
SELECT ServiceName, Body, ROUND(BM25(otel_idx.tableoid)::NUMERIC,3) AS score
FROM otel_idx WHERE Body @@ ts_phrase('timeout') ORDER BY score DESC LIMIT 20;
```

All of this is in `otel.py`, isolated so the SereneDB-specific syntax is easy to
adjust against the live docs.

## Report these for the award (fill in from your run)

| Measure | Value |
|---------|-------|
| Files queried (of 50) | _e.g. 1_ |
| Rows queried | _from `otel_aggregate(metric="count")`_ |
| `COUNT(*)` time | _s_ |
| Top-services aggregation time | _s_ |
| Index build time (Body) | _s_ |
| Full-text query time | _s_ |
| Did results stay useful at this scale? | _yes/no + note_ |

## Known limitations / caveats

- The exact multi-file `read_parquet([...])` and `REINDEX INDEX` syntax is from
  the brief + organiser Q&A; verify against your SereneDB build. If anything is
  rejected, it is all in `otel.py` to adjust.
- Indexing a billion-row `Body` uses **your machine's** resources and time —
  start with one file and scale to what you have.
- This path is independent of the core BGL/OpenStack workflow; it does not change
  the main submission.
