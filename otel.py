"""
OPTIONAL — "Working with Huge Datasets" award.

Query 50 billion rows of OpenTelemetry logs that live as Parquet in public S3,
WITHOUT downloading them: SereneDB reads remote Parquet in place (zero-ETL).

Based on the challenge brief + organiser Q&A:
  * Define a VIEW over the remote files:
        CREATE VIEW otel_logs AS
            SELECT * FROM read_parquet('https://.../part_000.parquet');
    Reading several at once works:
        read_parquet(['https://.../part_000.parquet',
                      'https://.../part_001.parquet'])
  * Make Body searchable by building an inverted index on the view; it streams
    from the source and only the index is stored locally. Refresh with
    REINDEX INDEX.
  * Scale by file: part_000 ~ first 30 min; part_000..009 ~ first 5 hours;
    all 50 ~ full 24h. One file is already ~1 billion rows.

OTel record fields: Timestamp, TraceId, SpanId, TraceFlags, SeverityText,
SeverityNumber, ServiceName, Body (+ *Attributes maps). Body is the text field.

Verified against the docs: CREATE INDEX on a view over read_parquet (local or
S3) is supported, and the snapshot is refreshed by REINDEX INDEX /
reindex_interval (serenedb.com/docs/sql/statements/create_index/inverted). This
matches what this module does. It is NOT part of the core submission.

Run it:
    python load_logs.py --otel-files 1        # just part_000 (~1B rows)
    python load_logs.py --otel-files 10 --otel-index   # 5 hours + full-text
"""
import time

from db import execute, query, scalar

S3_BASE = "https://public-pme.s3.eu-west-3.amazonaws.com/text_bench"
OTEL_VIEW = "otel_logs"
OTEL_IDX = "otel_idx"


def file_urls(n_files):
    """Return the first n_files Parquet URLs (part_000 .. part_{n-1})."""
    n = max(1, min(int(n_files), 50))
    return [f"{S3_BASE}/part_{i:03d}.parquet" for i in range(n)]


def _url_list_sql(urls):
    if len(urls) == 1:
        return f"read_parquet('{urls[0]}')"
    joined = ", ".join(f"'{u}'" for u in urls)
    return f"read_parquet([{joined}])"


def create_view(n_files=1):
    """Create (or replace) a view over the first n_files remote Parquet files.
    Nothing is downloaded; the view reads the files in place."""
    urls = file_urls(n_files)
    execute(f"DROP VIEW IF EXISTS {OTEL_VIEW}")
    execute(f"CREATE VIEW {OTEL_VIEW} AS SELECT * FROM {_url_list_sql(urls)}")
    print(f"[ok] View '{OTEL_VIEW}' over {len(urls)} remote file(s): "
          f"part_000 .. part_{len(urls) - 1:03d}")
    return urls


def _relax_session_for_indexing(memory_limit="12GB", threads=None):
    """Apply SereneDB session settings that make a large index build fit in RAM.

    Indexing the Body of ~1B rows is memory-heavy; SereneDB itself suggests
    these knobs on OutOfMemory. All are best-effort (ignored if unsupported)."""
    for stmt in (
        f"SET memory_limit='{memory_limit}'",
        "SET preserve_insertion_order=false",
    ):
        try:
            execute(stmt)
        except Exception:
            pass
    if threads:
        try:
            execute(f"SET threads={int(threads)}")
        except Exception:
            pass


def build_index(memory_limit="12GB", threads=None):
    """Build a BM25 inverted index on Body (streams from source; only the index
    is stored locally), then REINDEX.

    Returns the build time in seconds, or None if it could not be built (e.g.
    OutOfMemory at a billion rows). NEVER raises: a failed index must not kill
    the run — the aggregation results still stand. On OutOfMemory, the message
    explains how to retry with fewer files or a higher memory limit.
    """
    # Reuse the shared dictionary if fts.py already made it; otherwise create.
    try:
        execute("CREATE TEXT SEARCH DICTIONARY english "
                "AS split_text(case := 'lower') "
                "WITH (frequency, position, offset)")
    except Exception:
        pass

    _relax_session_for_indexing(memory_limit, threads)

    t0 = time.perf_counter()
    try:
        execute(f"DROP INDEX IF EXISTS {OTEL_IDX}")
        execute(f"CREATE INDEX {OTEL_IDX} ON {OTEL_VIEW} "
                f"USING inverted(TraceId, Body english)")
    except Exception as e:
        msg = str(e)
        print(f"[warn] Could not build the Body index at this scale ({msg.splitlines()[0]}).")
        if "memory" in msg.lower() or "allocate" in msg.lower():
            print("       Indexing ~1B rows of Body exceeded the memory limit.")
            print("       Retry with fewer files (e.g. --otel-files 1 is still 1B;")
            print("       there is no sub-file split), OR raise the limit, e.g.:")
            print("         build_index(memory_limit='16GB')  / SET memory_limit='16GB'")
            print("       Aggregations above do NOT need the index and still stand.")
        return None

    try:
        execute(f"REINDEX INDEX {OTEL_IDX}")
    except Exception as e:
        print(f"[warn] REINDEX INDEX failed ({e}); the index may still be usable.")

    secs = time.perf_counter() - t0
    print(f"[ok] Built inverted index '{OTEL_IDX}' on Body in {secs:.1f}s")
    return secs


# --- timed query helpers (for the award: report rows queried + query time) ---
def timed(sql, params=None):
    t0 = time.perf_counter()
    rows = query(sql, params)
    return rows, time.perf_counter() - t0


def row_count():
    """COUNT(*) over the remote view, with timing. One file ~ 1 billion rows."""
    t0 = time.perf_counter()
    n = int(scalar(f"SELECT COUNT(*) AS n FROM {OTEL_VIEW}") or 0)
    return n, time.perf_counter() - t0


def by_service(limit=10):
    """Top services by log volume over the remote data, with timing."""
    return timed(
        f"SELECT ServiceName, COUNT(*) AS n FROM {OTEL_VIEW} "
        f"GROUP BY ServiceName ORDER BY n DESC LIMIT {limit}")


def by_severity():
    """Counts by SeverityText over the remote data, with timing."""
    return timed(
        f"SELECT SeverityText, COUNT(*) AS n FROM {OTEL_VIEW} "
        f"GROUP BY SeverityText ORDER BY n DESC")


def search_body(phrase, limit=20):
    """BM25 full-text search of Body over the remote data (needs build_index).
    Returns (rows, seconds, sql)."""
    sql = (f"SELECT ServiceName, SeverityText, Body, "
           f"ROUND(BM25({OTEL_IDX}.tableoid)::NUMERIC, 3) AS score "
           f"FROM {OTEL_IDX} WHERE Body @@ ts_phrase(%s) "
           f"ORDER BY score DESC LIMIT %s")
    rows, secs = timed(sql, (phrase, limit))
    shown = sql.replace("%s", repr(phrase), 1).replace("%s", str(limit), 1)
    return rows, secs, shown


def demo(n_files=1, do_index=False):
    """End-to-end: create the view, prove it works small with timing, optionally
    index Body and run a full-text query. Prints a report for the award."""
    print("=" * 68)
    print("HUGE DATASETS (optional award) — remote OpenTelemetry Parquet")
    print("=" * 68)
    urls = create_view(n_files)

    n, t = row_count()
    print(f"\nRows queried: {n:,}  (COUNT(*) in {t:.1f}s over {len(urls)} file(s))")

    rows, t = by_service()
    print(f"\nTop services ({t:.1f}s):")
    for r in rows:
        print(f"  {str(r.get('ServiceName'))[:40]:<40} {r['n']:>12,}")

    rows, t = by_severity()
    print(f"\nBy severity ({t:.1f}s):")
    for r in rows:
        print(f"  {str(r.get('SeverityText')):<12} {r['n']:>12,}")

    if do_index:
        idx_secs = build_index()
        if idx_secs is not None:
            try:
                rows, qsecs, sql = search_body("timeout", limit=10)
                print(f"\nFull-text 'timeout' on Body: {len(rows)} hits in "
                      f"{qsecs:.1f}s (index built in {idx_secs:.1f}s)")
                for r in rows[:5]:
                    print(f"  [{r.get('SeverityText')}] {str(r.get('Body'))[:90]}")
                print(f"\n[query] {sql}")
            except Exception as e:
                print(f"[warn] full-text query failed ({e}).")
        else:
            print("\n(Full-text search skipped — index not built; see note above. "
                  "The aggregation results above are the huge-datasets evidence.)")

    print("\n--- Report these for the award: ---")
    print(f"  Files queried:   {len(urls)} of 50  ({S3_BASE}/part_000..)")
    print(f"  Rows queried:    {n:,}")
    print("  (Record the query times above; note whether results stay useful.)")
