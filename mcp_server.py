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

Run (stdio transport, the default for Claude Desktop / Claude Code):
    python mcp_server.py
"""
import json

from mcp.server.fastmcp import FastMCP

import tools

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
def search_logs_fulltext(dataset: str, phrase: str, limit: int = 15) -> str:
    """ENGINEER full-text search. Find the most relevant log lines for a
    phrase using SereneDB's BM25 inverted index.

    Inputs:
      dataset: "bgl" or "openstack"
      phrase:  words/phrase to search for (e.g. "kernel instruction cache parity")
      limit:   max rows to return (default 15; results are ranked, truncation flagged)
    Returns: ranked log lines with a BM25 `score`, plus the SQL and filters used.
    Use this to find WHAT failed before pulling nearby context."""
    if dataset.lower().startswith("open"):
        return _json(tools.search_openstack_fulltext(phrase, limit))
    return _json(tools.search_bgl_fulltext(phrase, limit))


@mcp.tool()
def get_nearby_events(ts: int, window_seconds: int = 120, limit: int = 20) -> str:
    """ENGINEER context window. Given a BGL event's Unix timestamp (`ts` from a
    search hit), return log lines within +/- window_seconds, in time order.
    Use this to see what happened JUST BEFORE and AFTER a failure."""
    return _json(tools.get_nearby_events_bgl(ts, window_seconds, limit))


# ── Team lead ───────────────────────────────────────────────────────────────
@mcp.tool()
def alert_categories(limit: int = 20) -> str:
    """TEAM LEAD recurring patterns. Whole-corpus BGL counts per alert category
    (the 12 labelled categories; normal lines excluded). Shows which problems
    recur and how often across ALL of BGL, not a sample."""
    return _json(tools.count_bgl_alert_categories(limit))


@mcp.tool()
def count_alerts_by_team(limit: int = 20) -> str:
    """TEAM LEAD ownership view. Whole-corpus BGL events grouped by OWNING TEAM
    and component (joined to the ownership table), with alert counts. Use it to
    say which TEAM should investigate first."""
    return _json(tools.count_bgl_alerts_by_team(limit))


@mcp.tool()
def trend_by_day(category: str = "", limit: int = 400) -> str:
    """TEAM LEAD / MANAGER trend. BGL alert volume per calendar day across the
    whole corpus. Pass a `category` to track one alert type over time, or leave
    empty for all alerts. Use it for week-over-week / rising-trend claims."""
    return _json(tools.bgl_trend_by_day(category or None, limit))


# ── Team lead / Manager (OpenStack aggregation) ─────────────────────────────
@mcp.tool()
def openstack_by_component() -> str:
    """TEAM LEAD / MANAGER aggregation. Whole-corpus OpenStack counts per nova
    service (nova-api/compute/scheduler): total lines, problem lines, problem %,
    average latency, and the owning team. The core OpenStack error-rate view."""
    return _json(tools.count_openstack_by_component())


@mcp.tool()
def latency_stats() -> str:
    """MANAGER / TEAM LEAD latency distribution. Per nova service over the whole
    OpenStack corpus: request count, avg/min/max latency (ms). Use measured
    latency only; do not invent downtime or customer impact."""
    return _json(tools.openstack_latency_stats())


if __name__ == "__main__":
    mcp.run()
