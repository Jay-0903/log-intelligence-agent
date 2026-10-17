"""
Log tools backed by SereneDB — the functions the agent calls.

Design principles (from the challenge brief):
  * Search returns a LIMITED set of relevant lines; aggregation returns
    CALCULATED counts/trends over the whole stated scope.
  * Every result carries its provenance: the SQL query, the filters applied,
    the data scope, the row count, and whether it was truncated. This lets a
    reviewer check that every number came from a query that actually ran.
  * Full-text search uses SereneDB's BM25 inverted index (see fts.py), not
    substring LIKE.

Return envelope used by all tools:
  {
    "tool":      str,
    "scope":     str,     # which table/dataset + how many rows it covers
    "filters":   dict,    # the parameters applied
    "query":     str,     # the SQL that ran (for checking)
    "rows":      list,    # the result rows
    "count":     int,     # len(rows)
    "truncated": bool,    # True if a LIMIT may have cut results
    "limit":     int|None,
  }

Load the data first with:  python load_logs.py ...
"""
import re

from db import TABLE, query, scalar
import fts

OPENSTACK_TABLE = "openstack_logs"
OWNERS_TABLE = "component_owners"
ALL_TABLE = "logs"

BGL_IDX = "bgl_idx"
OPENSTACK_IDX = "openstack_idx"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _envelope(tool, scope, filters, sql, rows, limit):
    return {
        "tool": tool,
        "scope": scope,
        "filters": filters,
        "query": " ".join(sql.split()),
        "rows": rows,
        "count": len(rows),
        "truncated": limit is not None and len(rows) >= limit,
        "limit": limit,
    }


def _count(table, where="", params=None):
    sql = f"SELECT COUNT(*) AS n FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return int(scalar(sql, params) or 0)


def corpus_scope():
    """How big is each table right now? Used to state data scope in answers."""
    out = {}
    for name, tbl in (("BGL", TABLE), ("OpenStack", OPENSTACK_TABLE)):
        try:
            out[name] = _count(tbl)
        except Exception:
            out[name] = None
    return out


def _table_exists(table):
    try:
        _count(table)
        return True
    except Exception:
        return False


def _like_fallback(table, cols, phrase, limit, order_by="id"):
    """Word-wise LIKE search used when the BM25 index is unavailable.

    Splits the phrase into words and ANDs a LIKE per word, keeping only words
    that actually occur in the column (so an extra word like 'kernel' doesn't
    zero out a match on 'instruction cache parity error'). Returns (rows, sql).
    """
    words = [w for w in re.findall(r"[A-Za-z0-9_.\-]+", phrase.lower())
             if len(w) > 1]
    # Keep only words that appear somewhere in the message column.
    present = []
    for w in words:
        try:
            if _count(table, "LOWER(message) LIKE %s", (f"%{w}%",)) > 0:
                present.append(w)
        except Exception:
            present.append(w)
    terms = present or words or [phrase.lower()]

    where = " AND ".join("LOWER(message) LIKE %s" for _ in terms)
    params = [f"%{t}%" for t in terms] + [limit]
    sql = (f'SELECT {", ".join(cols)} FROM {table} '
           f'WHERE {where} ORDER BY {order_by} LIMIT %s')
    rows = query(sql, params)
    shown = sql
    for t in terms:
        shown = shown.replace("%s", repr(f"%{t}%"), 1)
    shown = shown.replace("%s", str(limit), 1)
    shown += "   -- [fallback: word-wise LIKE, FTS index unavailable]"
    return rows, shown


# ===========================================================================
#  ENGINEER TOOLS — full-text search + nearby events
# ===========================================================================
def search_bgl_fulltext(phrase, limit=15):
    """TOOL (engineer): full-text BM25 search of BGL messages.

    Input:  phrase (str), limit (int, default 15)
    Output: ranked log lines (alert, ts, node, severity, message, score).
    Uses SereneDB's inverted index `bgl_idx` and the @@ / ts_phrase operator.
    """
    cols = ['id', 'alert', 'ts', 'node', 'event_time AS "datetime"',
            'severity', 'component', 'message']
    try:
        rows, sql = fts.search(BGL_IDX, "message", phrase, cols, limit)
    except Exception:
        rows, sql = _like_fallback(TABLE, cols, phrase, limit)
    env = _envelope("search_bgl_fulltext",
                    f"BGL ({_count(TABLE):,} lines)",
                    {"phrase": phrase}, sql, rows, limit)
    return env


def get_nearby_events_bgl(ts, window_seconds=120, limit=20):
    """TOOL (engineer): events within +/- window_seconds of a Unix timestamp.

    Input:  ts (unix seconds), window_seconds (int), limit (int)
    Output: chronologically ordered log lines around that moment.
    """
    sql = (f'SELECT id, alert, ts, node, event_time AS "datetime", severity, '
           f'component, message FROM {TABLE} '
           f'WHERE ts > 0 AND ts BETWEEN %s AND %s ORDER BY ts, id LIMIT %s')
    rows = query(sql, (ts - window_seconds, ts + window_seconds, limit))
    return _envelope(
        "get_nearby_events_bgl",
        f"BGL ({_count(TABLE):,} lines)",
        {"ts": ts, "window_seconds": window_seconds},
        sql, rows, limit)


def search_openstack_fulltext(phrase, limit=15):
    """TOOL (engineer): full-text BM25 search of OpenStack messages."""
    if not _table_exists(OPENSTACK_TABLE):
        return _missing_table_env("search_openstack_fulltext", OPENSTACK_TABLE)
    cols = ['id', 'log_time', 'level', 'component', 'request_id',
            'tenant_id', 'latency_ms', 'message']
    try:
        rows, sql = fts.search(OPENSTACK_IDX, "message", phrase, cols, limit)
    except Exception:
        rows, sql = _like_fallback(OPENSTACK_TABLE, cols, phrase, limit)
    return _envelope("search_openstack_fulltext",
                     f"OpenStack ({_count(OPENSTACK_TABLE):,} lines)",
                     {"phrase": phrase}, sql, rows, limit)


# ===========================================================================
#  TEAM LEAD / MANAGER TOOLS — whole-corpus aggregation + ownership + trends
# ===========================================================================
def count_bgl_alerts_by_team(limit=20):
    """TOOL (team lead/manager): whole-corpus BGL alert counts grouped by the
    OWNING TEAM, via the supplied component_owners table.

    Output: team, component, alert_events, total_events, over the entire BGL
    table (not a sample).
    """
    sql = f"""
        SELECT COALESCE(o.team, 'Unmapped') AS team,
               b.component,
               COUNT(*) AS events,
               SUM(CASE WHEN b.alert <> '-' THEN 1 ELSE 0 END) AS alert_events
        FROM {TABLE} b
        LEFT JOIN {OWNERS_TABLE} o
          ON o.dataset = 'BGL' AND o.component = b.component
        GROUP BY team, b.component
        ORDER BY alert_events DESC, events DESC
        LIMIT {limit}
    """
    rows = query(sql)
    return _envelope("count_bgl_alerts_by_team",
                     f"BGL (whole corpus, {_count(TABLE):,} lines)",
                     {"group_by": "team, component"}, sql, rows, limit)


def count_bgl_alert_categories(limit=20):
    """TOOL (team lead): whole-corpus BGL alert-category counts (the 12
    labelled categories; '-' = normal is excluded)."""
    sql = f"""
        SELECT alert AS category, COUNT(*) AS n
        FROM {TABLE}
        WHERE alert <> '-'
        GROUP BY alert
        ORDER BY n DESC
        LIMIT {limit}
    """
    rows = query(sql)
    return _envelope("count_bgl_alert_categories",
                     f"BGL (whole corpus, {_count(TABLE):,} lines)",
                     {"exclude": "alert = '-' (normal)"}, sql, rows, limit)


def bgl_trend_by_day(category=None, limit=400):
    """TOOL (team lead/manager): BGL alert volume per calendar day.

    Input:  category (optional alert category to filter), limit
    Output: date, alert_events per day across the whole BGL corpus (trend).
    """
    where = "ts > 0"
    params = []
    if category:
        where += " AND alert = %s"
        params.append(category)
    else:
        where += " AND alert <> '-'"
    sql = f"""
        SELECT CAST(to_timestamp(ts) AS DATE) AS day,
               COUNT(*) AS alert_events
        FROM {TABLE}
        WHERE {where}
        GROUP BY day
        ORDER BY day
        LIMIT {limit}
    """
    rows = query(sql, params or None)
    return _envelope("bgl_trend_by_day",
                     f"BGL (whole corpus, {_count(TABLE):,} lines)",
                     {"category": category or "any alert"}, sql, rows, limit)


def _missing_table_env(tool, table):
    return {
        "tool": tool, "scope": f"{table} (NOT LOADED)", "filters": {},
        "query": None, "rows": [], "count": 0, "truncated": False,
        "limit": None, "note": f"Table '{table}' is not loaded; skipped.",
    }


def count_openstack_by_component():
    """TOOL (team lead/manager): whole-corpus OpenStack counts grouped by nova
    service, with error rate and the owning team."""
    if not _table_exists(OPENSTACK_TABLE):
        return _missing_table_env("count_openstack_by_component", OPENSTACK_TABLE)
    sql = f"""
        SELECT os.component,
               COALESCE(o.team, 'Unmapped') AS team,
               COUNT(*) AS total,
               SUM(os.is_problem) AS problems,
               ROUND((100.0 * SUM(os.is_problem) / COUNT(*))::NUMERIC, 2) AS problem_pct,
               ROUND(AVG(os.latency_ms)::NUMERIC, 1) AS avg_latency_ms
        FROM {OPENSTACK_TABLE} os
        LEFT JOIN {OWNERS_TABLE} o
          ON o.dataset = 'OpenStack' AND o.component = os.component
        GROUP BY os.component, team
        ORDER BY problems DESC
    """
    rows = query(sql)
    return _envelope("count_openstack_by_component",
                     f"OpenStack (whole corpus, {_count(OPENSTACK_TABLE):,} lines)",
                     {"group_by": "component (nova service)"}, sql, rows, None)


def openstack_latency_stats():
    """TOOL (manager/team lead): request latency distribution per nova service
    over the whole OpenStack corpus (count, avg, p95-ish via max)."""
    if not _table_exists(OPENSTACK_TABLE):
        return _missing_table_env("openstack_latency_stats", OPENSTACK_TABLE)
    sql = f"""
        SELECT component,
               COUNT(latency_ms) AS requests,
               ROUND(AVG(latency_ms)::NUMERIC, 1) AS avg_ms,
               ROUND(MIN(latency_ms)::NUMERIC, 1) AS min_ms,
               ROUND(MAX(latency_ms)::NUMERIC, 1) AS max_ms
        FROM {OPENSTACK_TABLE}
        WHERE latency_ms IS NOT NULL
        GROUP BY component
        ORDER BY avg_ms DESC
    """
    rows = query(sql)
    return _envelope("openstack_latency_stats",
                     f"OpenStack (whole corpus, {_count(OPENSTACK_TABLE):,} lines)",
                     {"metric": "latency_ms"}, sql, rows, None)


def team_ownership():
    """TOOL (any role): return the supplied component -> team ownership table."""
    sql = f"SELECT dataset, component, team, on_call FROM {OWNERS_TABLE} ORDER BY dataset, component"
    rows = query(sql)
    return _envelope("team_ownership", OWNERS_TABLE, {}, sql, rows, None)


# ===========================================================================
#  Self-test (requires a loaded DB)
# ===========================================================================
if __name__ == "__main__":
    print("Corpus scope:", corpus_scope())

    print("\n[search_bgl_fulltext 'kernel panic']")
    r = search_bgl_fulltext("kernel", limit=3)
    print("  query:", r["query"][:120])
    for row in r["rows"][:3]:
        print("   ", {k: row[k] for k in list(row)[:4]})

    print("\n[count_bgl_alert_categories]")
    for row in count_bgl_alert_categories(limit=5)["rows"]:
        print("   ", row)

    print("\n[count_openstack_by_component]")
    for row in count_openstack_by_component()["rows"]:
        print("   ", row)

    print("\n[team_ownership]")
    for row in team_ownership()["rows"][:4]:
        print("   ", row)
