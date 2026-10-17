"""
Log Intelligence Agent — role-aware CLI over the SereneDB tools.

Rule-based (no API key needed) so the workflow is reproducible for judges.
It demonstrates the same thing the MCP server exposes: pick the right tool
for the role, run a parameterized SereneDB query, then explain the evidence
and recommend a next step.

Each answer:
  * states the DATA SCOPE and filters,
  * shows the EVIDENCE (query result),
  * separates OBSERVED FACTS from HYPOTHESES,
  * ends with a role-appropriate NEXT STEP.

Roles differ in which evidence they select, not just answer length:
  Engineer  -> full-text search + nearby events (what/where, drill in)
  Team lead -> recurring categories + per-team counts + trend (what recurs)
  Manager   -> prioritized problems by measured frequency + owning team

Usage:
    python agent.py                      # scripted demo + interactive loop
    python agent.py "engineer: ..."      # one-shot
"""
import sys

import tools


def _fmt_rows(rows, cols, widths):
    out = []
    for r in rows:
        cells = []
        for c, w in zip(cols, widths):
            v = r.get(c)
            v = "" if v is None else str(v)
            cells.append(v[:w].ljust(w))
        out.append("  " + "  ".join(cells))
    return out


def _provenance(env):
    t = " (TRUNCATED — more rows exist)" if env["truncated"] else ""
    return (f"  [scope: {env['scope']} | rows: {env['count']}{t}]\n"
            f"  [query: {env['query']}]")


def _dedupe_by_message(rows):
    """Collapse rows with identical `message` into one, keeping the first
    occurrence and adding an `n` count. Reinforces the brief's point that
    matching lines are not automatically separate incidents (common on the 2k
    sample where lines repeat)."""
    seen = {}
    order = []
    for r in rows:
        key = r.get("message")
        if key not in seen:
            seen[key] = dict(r, n=1)
            order.append(key)
        else:
            seen[key]["n"] += 1
    return [seen[k] for k in order]


def _unavailable(env):
    """True if a tool result refers to a table that is not loaded."""
    return env.get("query") is None and env.get("note")


# ===========================================================================
#  ENGINEER
# ===========================================================================
def answer_engineer(question):
    """What failed, where, and what happened just before/after."""
    q = question.lower()
    dataset = "openstack" if any(w in q for w in
              ("openstack", "nova", "api", "compute", "scheduler", "tenant")) else "bgl"
    # Strip role words to form the search phrase.
    phrase = question
    for lead in ("engineer:",):
        if phrase.lower().startswith(lead):
            phrase = phrase[len(lead):]
    phrase = phrase.strip() or "error"

    out = ["ENGINEER — error investigation", ""]
    if dataset == "openstack":
        env = tools.search_openstack_fulltext(phrase, limit=8)
        if _unavailable(env):
            out.append("OpenStack data is not loaded — "
                       "falling back to BGL search instead.")
            dataset = "bgl"
        else:
            rows = env["rows"]
            out.append(f"OBSERVED — top OpenStack matches for '{phrase}':")
            out += _fmt_rows(rows,
                             ["level", "component", "request_id", "message"],
                             [6, 13, 22, 60])
            out.append(_provenance(env))
            # Follow the request_id of the top hit through its full lifecycle.
            req = next((r.get("request_id") for r in rows if r.get("request_id")),
                       None)
            if req:
                trace = tools.openstack_request_trace(req, limit=15)
                out += ["", f"OBSERVED — full lifecycle of request {req} "
                        f"({trace['count']} lines, time order):"]
                out += _fmt_rows(trace["rows"],
                                 ["log_time", "level", "component", "message"],
                                 [23, 6, 13, 50])
                out.append(_provenance(trace))
            out += ["", "HYPOTHESIS — the highest-scoring lines point at the "
                    "component above; the request trace shows where in the "
                    "request's lifecycle it occurred.",
                    "NEXT STEP — if the trace shows an error mid-request, check "
                    "that component's handler for that request path."]
            return "\n".join(out)

    # BGL: full-text search, then nearby events around the top hit.
    env = tools.search_bgl_fulltext(phrase, limit=8)
    rows = env["rows"]
    distinct = _dedupe_by_message(rows)
    out.append(f"OBSERVED — top BGL matches for '{phrase}' (BM25 ranked, "
               f"identical messages collapsed with an occurrence count 'n'):")
    out += _fmt_rows(distinct, ["n", "severity", "node", "component", "message"],
                     [3, 7, 20, 10, 66])
    out.append(_provenance(env))

    if rows and rows[0].get("ts"):
        ts = rows[0]["ts"]
        hit_node = rows[0].get("node")
        near = tools.get_nearby_events_bgl(ts, window_seconds=60, limit=8,
                                           node=hit_node)
        out += ["", f"OBSERVED — context +/-60s around the top hit on node "
                f"{hit_node} (ts={ts}):"]
        out += _fmt_rows(near["rows"], ["alert", "severity", "node", "message"],
                         [10, 7, 18, 64])
        out.append(_provenance(near))

    top = rows[0] if rows else None
    comp = top.get("component") if top else "?"
    out += ["",
            f"HYPOTHESIS — failure centres on component '{comp}' on the node above; "
            "the nearby window shows what co-occurred. The logs show the symptom, "
            "not a confirmed root cause.",
            f"NEXT STEP — check the owning team's runbook for '{comp}' and widen the "
            "window (get_nearby_events, larger window_seconds) to see if the alert "
            "repeats on the same node."]
    return "\n".join(out)


# ===========================================================================
#  TEAM LEAD
# ===========================================================================
def answer_team_lead(question):
    """Which problems recur, how often, and which teams own them."""
    out = ["TEAM LEAD — recurring patterns & ownership", ""]

    prof = tools.bgl_alert_profile(limit=8)
    out.append("OBSERVED — BGL alert categories, whole corpus — SPREAD not just "
               "raw count (lines / distinct nodes / distinct days / first..last):")
    out += _fmt_rows(prof["rows"],
                     ["category", "lines", "distinct_nodes", "distinct_days",
                      "first_seen", "last_seen"],
                     [10, 9, 8, 7, 11, 11])
    out.append(_provenance(prof))

    teams = tools.count_bgl_alerts_by_team(limit=8)
    out += ["", "OBSERVED — BGL events by owning team / component (alerts first):"]
    out += _fmt_rows(teams["rows"], ["team", "component", "alert_events", "events"],
                     [20, 12, 12, 10])
    out.append(_provenance(teams))

    osc = tools.count_openstack_by_component()
    if _unavailable(osc):
        out += ["", f"OpenStack unavailable — {osc.get('note', 'skipped')}"]
    else:
        out += ["", "OBSERVED — OpenStack error-keyword rate by nova service "
                "(ERROR/CRITICAL level or error words; NOT labelled anomalies):"]
        out += _fmt_rows(osc["rows"],
                         ["component", "team", "total", "error_lines", "error_pct"],
                         [16, 14, 8, 11, 9])
        out.append(_provenance(osc))

    if prof["rows"]:
        top = prof["rows"][0]
        top_cat = top["category"]
        top_team = tools.team_for_bgl_alert(top_cat)
        nodes = tools.bgl_top_nodes_for_alert(top_cat, limit=3)["rows"]
        node_list = ", ".join(n["node"] for n in nodes) or "the affected nodes"
        spread = (f"{top['lines']:,} lines on {top['distinct_nodes']} nodes "
                  f"over {top['distinct_days']} day(s) "
                  f"({top['first_seen']}..{top['last_seen']})")
        out += ["",
                f"HYPOTHESIS — '{top_cat}' is the dominant recurring BGL alert "
                f"({spread}); it maps to the '{top_team}' team. The spread shows "
                "whether this is chronic (many days) or a single incident (one day).",
                f"NEXT STEP — ask {top_team} to inspect nodes {node_list} first "
                f"(the heaviest sources of '{top_cat}'); use trend_by_day on that "
                "category to confirm whether it is rising or a one-off before "
                "committing effort."]
    return "\n".join(out)


# ===========================================================================
#  MANAGER
# ===========================================================================
def answer_manager(question):
    """What deserves attention first and why — measured frequency only."""
    out = ["MANAGER — prioritized risks (measured frequency only)", ""]

    prof = tools.bgl_alert_profile(limit=5)
    scope = tools.corpus_scope()
    bgl_n = scope.get("BGL")
    os_n = scope.get("OpenStack")
    os_txt = f"{os_n} lines" if os_n else "not loaded"
    out.append(f"DATA SCOPE — BGL: {bgl_n} lines; OpenStack: {os_txt} "
               "(whole corpus).")
    out += ["", "OBSERVED — top BGL alerts by SPREAD (lines / nodes / days / "
            "first..last), not raw count alone:"]
    out += _fmt_rows(prof["rows"],
                     ["category", "lines", "distinct_nodes", "distinct_days",
                      "first_seen", "last_seen"],
                     [10, 9, 8, 7, 11, 11])
    out.append(_provenance(prof))

    osc = tools.count_openstack_by_component()
    if _unavailable(osc):
        out += ["", f"OpenStack unavailable — {osc.get('note', 'skipped')} "
                "Prioritization uses BGL only."]
    else:
        out += ["", "OBSERVED — OpenStack services ranked by error-keyword lines "
                "(NOT labelled anomalies):"]
        out += _fmt_rows(osc["rows"],
                         ["component", "team", "error_lines", "error_pct"],
                         [16, 14, 11, 9])
        out.append(_provenance(osc))

    out += ["", "PRIORITIZED ACTIONS — ranked by SPREAD (sustained problems "
            "before one-day bursts), each with concrete nodes:"]
    # Rank by spread: sustained (many days) outrank single-day bursts, then by
    # affected nodes, then by raw lines. This avoids ranking a one-day burst
    # above a chronic multi-day problem purely on raw count.
    def _spread_key(r):
        days = r.get("distinct_days") or 0
        nodes = r.get("distinct_nodes") or 0
        return (days > 1, days, nodes, r.get("lines") or 0)
    ranked = sorted(prof["rows"][:5], key=_spread_key, reverse=True)[:3]
    rank = 1
    for row in ranked:
        cat = row["category"]
        team = tools.team_for_bgl_alert(cat)
        nodes = tools.bgl_top_nodes_for_alert(cat, limit=3)["rows"]
        node_list = ", ".join(n["node"] for n in nodes) or "affected nodes"
        one_day = row["distinct_days"] == 1
        if one_day:
            shape = (f"BURST — concentrated on ONE day ({row['first_seen']}); "
                     "treat as a single incident to investigate, not a chronic defect")
        else:
            shape = (f"SUSTAINED — {row['distinct_days']} days "
                     f"({row['first_seen']}..{row['last_seen']})")
        out.append(
            f"  {rank}. BGL '{cat}' — {row['lines']:,} lines on "
            f"{row['distinct_nodes']} nodes. {shape}. Route to {team}; "
            f"inspect nodes {node_list} first.")
        rank += 1
    if not _unavailable(osc):
        for row in osc["rows"][:2]:
            if row.get("error_lines"):
                out.append(f"  {rank}. OpenStack {row['component']} — "
                           f"{row['error_lines']} error-keyword lines "
                           f"({row['error_pct']}%). Owner: {row['team']}.")
                rank += 1

    out += ["",
            "NOTE — these are counts of matching log lines, not confirmed incidents, "
            "and the logs do not establish financial loss, downtime or customer "
            "impact. BGL alerts use the dataset's labels; OpenStack 'error' here "
            "means ERROR/CRITICAL level or error keywords, NOT the dataset's "
            "labelled anomalies. Priority = spread (days x nodes) + ownership."]
    return "\n".join(out)


# ===========================================================================
#  routing + CLI
# ===========================================================================
def dispatch(role, question):
    role = role.lower()
    if "engineer" in role:
        return answer_engineer(question)
    if "team" in role or "lead" in role:
        return answer_team_lead(question)
    if "manager" in role:
        return answer_manager(question)
    return "Unknown role. Use: engineer / teamlead / manager"


DEMO = [
    ("ENGINEER",  "engineer: kernel instruction cache parity error"),
    ("TEAM LEAD", "teamlead: what alert patterns recur and which teams own them?"),
    ("MANAGER",   "manager: what should we prioritize?"),
]


def run_demo():
    print("=" * 70)
    print("LOG INTELLIGENCE AGENT — SereneDB (BGL + OpenStack base corpus)")
    print("=" * 70)
    for role, q in DEMO:
        print(f"\n{'-'*70}\nROLE: {role}\nQUESTION: {q}\n{'-'*70}")
        print(dispatch(role, q))
    print(f"\n{'='*70}\nINTERACTIVE — 'role: question'  (engineer/teamlead/manager), "
          "or 'quit'\n{'='*70}".replace("{'='*70}", "=" * 70))
    while True:
        try:
            line = input("\n> ").strip()
        except EOFError:
            break
        if line.lower() in ("quit", "exit", "q"):
            break
        if ":" in line:
            role, q = line.split(":", 1)
            print(dispatch(role.strip(), q.strip()))
        else:
            print("Format: role: your question (e.g. 'manager: top risks?')")


if __name__ == "__main__":
    if len(sys.argv) > 1 and ":" in sys.argv[1]:
        role, q = sys.argv[1].split(":", 1)
        print(dispatch(role.strip(), q.strip()))
    else:
        run_demo()
