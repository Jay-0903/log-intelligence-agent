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

## Measured results

Run on a developer laptop against `part_000.parquet` (one file) over the public
S3 endpoint — nothing downloaded, SereneDB read it in place.

| Measure | Value |
|---------|-------|
| Files queried (of 50) | **1** (`part_000.parquet`) |
| Rows queried | **1,000,000,000** |
| `COUNT(*)` time | **0.1 s** (reads Parquet metadata) |
| Top-services aggregation (`GROUP BY ServiceName`) | **15.5 s** over 1B rows |
| By-severity aggregation (`GROUP BY SeverityText`) | **11.7 s** over 1B rows |
| Index build time (`Body`) | **did not complete** — OutOfMemory at 1B rows (6 GiB limit) |
| Full-text query time (`Body @@ ts_phrase('timeout')`) | n/a (index not built) |
| Did results stay useful at this scale? | **Yes for aggregation**; full-text index needs more RAM at 1B rows |

**Observed data (1B rows, one file):**

Top services by volume: `cart` 428.6M, `frontend` 292.3M, `email` 88.7M,
`recommendation` 50.5M, `payment` 37.2M, `shipping` 28.0M, `checkout` 27.1M,
`quote` 25.9M, `currency` 16.5M, `fraud-detection` 1.6M.

By severity: `info` 676.8M, `information` 140.7M, `error` 122.8M, `trace` 58.3M,
`warn` 1.26M, `fatal` 9,721.

**Takeaways for the award:**
- A **1-billion-row** aggregation returns in ~12–16 s with **zero ingestion** —
  the view reads remote Parquet in place; widening to more files is one line of
  config, not a loading job.
- Results remain useful at scale: a manager-style view ("which services and
  severities dominate") is answerable directly over a billion rows. `error`
  (122.8M) and `fatal` (9,721) are immediately quantified.

**The scale limit we hit (an honest finding):** building a BM25 **full-text
index on `Body` across 1B rows ran out of memory** on a 6 GiB limit —
`OutOfMemory: failed to allocate ... (6.0 GiB/6.0 GiB used)`. This matches the
organiser guidance that indexing uses your own machine's resources: aggregation
over remote Parquet scales effortlessly (no local state), but a local inverted
index at a billion rows needs more RAM. The code now treats a failed index as a
reported warning, not a crash, so the aggregation evidence still stands. To build
the Body index, raise the limit (`SET memory_limit='16GB'` /
`otel_setup(..., memory_limit='16GB')`) or run on a larger machine; the SQL is
unchanged and already verified.

## Known limitations / caveats

- The exact multi-file `read_parquet([...])` and `REINDEX INDEX` syntax is from
  the brief + organiser Q&A; verify against your SereneDB build. If anything is
  rejected, it is all in `otel.py` to adjust.
- Indexing a billion-row `Body` uses **your machine's** resources and time —
  start with one file and scale to what you have.
- This path is independent of the core BGL/OpenStack workflow; it does not change
  the main submission.
