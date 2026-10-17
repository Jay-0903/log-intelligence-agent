"""
MCP server exposing the log-intelligence tools so an agent (e.g. Claude)
can discover and call them.

Each tool wraps a parameterized SereneDB query (no open-ended SQL). Tool
descriptions explain purpose, inputs and outputs so the agent can pick the
right one for each role:

  Engineer   -> search_logs_fulltext, get_nearby_events
  Team lead  -> count_alerts_by_team, alert_categories, trend_by_day,
                openstack_by_component
  Manager    -> openstack_by_component, latency_stats, alert_categories
  Any role   -> corpus_scope, team_ownership

Every tool returns a JSON envelope with the SQL that ran, the filters, the
data scope, the row count and a `truncated` flag, so every number is
checkable.

REPORTING RULE (applies to every answer):
  Separate observed facts from explanations. Root causes are HYPOTHESES unless
  the logs explicitly confirm them — phrase cause statements as "likely" /
  "consistent with" / "appears to", and state what the logs do not establish.
  Counts are matching log lines, not confirmed incidents.

Run (stdio transport, the default for Claude Desktop / Claude Code):
    python mcp_server.py
"""
import json

from mcp.server.fastmcp import FastMCP

import tools

INSTRUCTIONS = (
    "Tools to search and aggregate BGL/OpenStack logs in SereneDB for three "
    "roles (engineer, team lead, manager). Pick a tool per the role and "
    "question; every result includes the SQL, filters and data scope so numbers "
    "are checkable.\n\n"
    "REPORTING RULE: clearly separate observed facts from explanations. A root "
    "cause is a HYPOTHESIS unless the logs confirm it — phrase cause statements "
    "as 'likely', 'consistent with', or 'appears to', and say what the logs do "
    "NOT establish. Counts are matching log lines, not confirmed incidents; do "
    "not invent downtime, cost or customer impact."
)

try:
    mcp = FastMCP("log-intelligence", instructions=INSTRUCTIONS)
except TypeError:
    # Older FastMCP without an `instructions` kwarg — the per-tool descriptions
    # still carry the reporting rule.
    mcp = FastMCP("log-intelligence")


def _json(env):
    return json.dumps(env, default=str, indent=2)


# ── Shared / scope ──────────────────────────────────────────────────────────
@mcp.tool()
def corpus_scope() -> str:
    """Report how many log lines are loaded for each dataset (BGL, OpenStack).
    Call this first to state the data scope before quoting any numbers."""
    return json.dumps(tools.corpus_scope(), indent=2)


@mcp.tool()
def team_ownership() -> str:
    """Return the supplied component -> team ownership table (dataset,
    component, team, on-call). Use it to say WHICH TEAM owns a problem."""
    return _json(tools.team_ownership())


# ── Engineer ────────────────────────────────────────────────────────────────
@mcp.tool()
def search_logs_fulltext(dataset: str, phrase: str, limit: int = 15,
                         start: str = "", end: str = "") -> str:
    """ENGINEER full-text search with optional time filter. Find the most
    relevant log lines for a phrase using SereneDB's BM25 inverted index.

    Inputs:
      dataset: "bgl" or "openstack"
      phrase:  words/phrase to search for (e.g. "kernel instruction cache parity")
      limit:   max rows to return (default 15; results are ranked, truncation flagged)
      start/end: optional time filter — unix seconds or 'YYYY-MM-DD'[ HH:MM:SS].
                 Restrict the search to events in that window.
    Returns: ranked log lines with a BM25 `score`, plus the SQL, filters and
    period used. Use this to find WHAT failed before pulling nearby context.

    Reporting: these lines are observed facts. Any root cause you infer is a
    HYPOTHESIS unless the logs confirm it — phrase it as 'likely' / 'consistent
    with', and state what the logs do not establish."""
    s = start or None
    e = end or None
    if dataset.lower().startswith("open"):
        return _json(tools.search_openstack_fulltext(phrase, limit, s, e))
    return _json(tools.search_bgl_fulltext(phrase, limit, s, e))


@mcp.tool()
def get_nearby_events(ts: int, window_seconds: int = 120, limit: int = 20,
                      node: str = "") -> str:
    """ENGINEER context window. Given a BGL event's Unix timestamp (`ts` from a
    search hit), return log lines within +/- window_seconds, in time order. Pass
    `node` to restrict to one node so a wide window on a large cluster doesn't
    mix in unrelated nodes. Use this to see what happened JUST BEFORE and AFTER a
    failure.

    Reporting: co-occurrence is not causation. Describe the sequence as observed
    fact; label any cause as a HYPOTHESIS ('likely' / 'consistent with') and note
    what the logs cannot confirm."""
    return _json(tools.get_nearby_events_bgl(ts, window_seconds, limit,
                                             node or None))


@mcp.tool()
def request_trace(request_id: str, limit: int = 50) -> str:
    """ENGINEER request lifecycle. All OpenStack log lines sharing a `request_id`,
    in time order — the concrete follow-up to an OpenStack search hit (pull its
    request_id, then trace the whole request)."""
    return _json(tools.openstack_request_trace(request_id, limit))


# ── Team lead ───────────────────────────────────────────────────────────────
@mcp.tool()
def alert_categories(limit: int = 20, start: str = "", end: str = "") -> str:
    """TEAM LEAD recurring patterns. BGL counts per alert category (the 12
    labelled categories; normal lines excluded). Default scope is the WHOLE
    corpus; pass start/end (unix or 'YYYY-MM-DD') to count over a stated period.
    The scope string states the period used."""
    return _json(tools.count_bgl_alert_categories(limit, start or None, end or None))


@mcp.tool()
def alert_profile(limit: int = 12, start: str = "", end: str = "") -> str:
    """TEAM LEAD / MANAGER spread view. Per BGL alert category: lines,
    distinct_nodes, distinct_days, first_seen, last_seen, peak_day,
    peak_day_lines, and **peak_day_share** (max lines on one day / total).

    Use this instead of raw counts so you report affected scope ('N lines on D
    nodes over K days'), not each line as an incident. IMPORTANT: a category with
    **peak_day_share >= 0.9 is a BURST** — concentrated on a single day (e.g.
    KERNDTLB = 99.6% on 2005-06-12) — so treat it as a one-off incident, not a
    recurring problem, even if it also has a few scattered days.

    Default `limit` is 12 (BGL has 12 alert categories) so you see EVERY category
    and can rank by spread, not just the loudest few. Pass start/end for a
    period."""
    return _json(tools.bgl_alert_profile(limit, start or None, end or None))


@mcp.tool()
def top_nodes_for_alert(category: str, limit: int = 5,
                        start: str = "", end: str = "") -> str:
    """TEAM LEAD / ENGINEER. The nodes with the most lines of a given BGL alert
    category, highest first — so a recommendation can name concrete nodes to
    inspect. Pass start/end to scope to a period."""
    return _json(tools.bgl_top_nodes_for_alert(category, limit,
                                               start or None, end or None))


@mcp.tool()
def count_alerts_by_team(limit: int = 20, start: str = "", end: str = "") -> str:
    """TEAM LEAD ownership view. BGL events grouped by OWNING TEAM and component
    (joined to the ownership table), with alert counts. Default scope is the
    WHOLE corpus; pass start/end to count over a stated period. Use it to say
    which TEAM should investigate first."""
    return _json(tools.count_bgl_alerts_by_team(limit, start or None, end or None))


@mcp.tool()
def trend_by_day(category: str = "", limit: int = 400,
                 start: str = "", end: str = "") -> str:
    """TEAM LEAD / MANAGER trend. BGL alert volume per calendar day. Pass a
    `category` to track one alert type over time, or leave empty for all alerts.
    Default scope is the whole corpus; pass start/end to bound the period."""
    return _json(tools.bgl_trend_by_day(category or None, limit,
                                        start or None, end or None))


@mcp.tool()
def trend_by_week(category: str = "", limit: int = 60,
                  start: str = "", end: str = "") -> str:
    """TEAM LEAD / MANAGER week-over-week trend. BGL alert volume per week
    (date_trunc('week', ...)). Pass a `category` to track one alert type, or
    leave empty for all alerts; start/end bound the period. Use this for the
    brief's week-over-week questions."""
    return _json(tools.bgl_trend_by_week(category or None, limit,
                                         start or None, end or None))


# ── Team lead / Manager (OpenStack aggregation) ─────────────────────────────
@mcp.tool()
def openstack_by_component(start: str = "", end: str = "") -> str:
    """TEAM LEAD / MANAGER aggregation. OpenStack counts per nova service
    (nova-api/compute/scheduler): total lines, problem lines, problem %, average
    latency, and the owning team. Default scope is the WHOLE corpus; pass
    start/end to count over a stated period. The core OpenStack error-rate view."""
    return _json(tools.count_openstack_by_component(start or None, end or None))


@mcp.tool()
def latency_stats() -> str:
    """MANAGER / TEAM LEAD latency distribution. Per nova service over the whole
    OpenStack corpus: request count, avg/min/max latency (ms). Use measured
    latency only; do not invent downtime or customer impact."""
    return _json(tools.openstack_latency_stats())


# ── OPTIONAL: huge datasets (remote OpenTelemetry Parquet, zero-ETL) ─────────
@mcp.tool()
def otel_setup(n_files: int = 1, build_index: bool = False,
               memory_limit: str = "12GB") -> str:
    """OPTIONAL huge-datasets award. Point SereneDB at the first `n_files` remote
    OpenTelemetry Parquet files (1-50; one file ~1 billion rows) WITHOUT
    downloading, as a view. If build_index=true, also build a BM25 index on the
    `Body` text field (memory-heavy at 1B rows; `memory_limit` tunes the session,
    and a failed build is reported, not fatal). Returns view/index status + URLs."""
    import otel
    urls = otel.create_view(n_files)
    out = {"view": otel.OTEL_VIEW, "files": len(urls), "urls": urls}
    if build_index:
        secs = otel.build_index(memory_limit=memory_limit)
        out["index_build_seconds"] = round(secs, 2) if secs is not None else None
        out["index_built"] = secs is not None
    return json.dumps(out, indent=2)


@mcp.tool()
def otel_aggregate(metric: str = "service") -> str:
    """OPTIONAL. Aggregate over the remote OTel view (run otel_setup first).
    metric: "service" (counts per ServiceName), "severity" (counts per
    SeverityText) or "count" (total rows). Returns rows + the query time in
    seconds, so you can report how much data was queried and how long it took."""
    import otel
    if metric == "count":
        n, secs = otel.row_count()
        return json.dumps({"rows_queried": n, "seconds": round(secs, 2)}, indent=2)
    rows, secs = (otel.by_severity() if metric == "severity" else otel.by_service())
    return json.dumps({"rows": rows, "seconds": round(secs, 2)},
                      default=str, indent=2)


@mcp.tool()
def otel_search(phrase: str, limit: int = 20) -> str:
    """OPTIONAL. BM25 full-text search of the remote OTel `Body` field (run
    otel_setup with build_index=true first). Returns ranked hits, the query time
    and the SQL used."""
    import otel
    rows, secs, sql = otel.search_body(phrase, limit)
    return json.dumps({"rows": rows, "seconds": round(secs, 2), "query": sql},
                      default=str, indent=2)


if __name__ == "__main__":
    mcp.run()
