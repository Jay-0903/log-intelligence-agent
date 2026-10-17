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

Reporting rule (brief requirement): root causes are HYPOTHESES unless the logs
confirm them — phrase cause statements as "likely" / "consistent with", and say
what the logs do not establish. Counts are matching log lines, not confirmed
incidents; never invent downtime, cost or customer impact.

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


def _recurring_key(r):
    """Sort key for 'most recurring' / spread ranking. Higher = more recurring:
    more distinct days, then still-active-at-end-of-data (later last_seen),
    then more nodes, then more lines. Bursts (peak_day_share >= 0.9) are
    de-prioritised so a one-day storm never ranks as 'recurring'."""
    days = r.get("distinct_days") or 0
    last = str(r.get("last_seen") or "")      # ISO date string sorts correctly
    nodes = r.get("distinct_nodes") or 0
    lines = r.get("lines") or 0
    not_burst = 0 if tools._is_burst(r) else 1
    return (not_burst, days, last, nodes, lines)


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
            out += ["", "HYPOTHESIS — the highest-scoring lines are likely "
                    "centred on the component above; the request trace shows "
                    "where in the request's lifecycle it occurred. This is "
                    "consistent with the evidence, not a confirmed cause.",
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
            f"HYPOTHESIS — the symptom is likely centred on component '{comp}' on "
            "the node above; the nearby window shows what co-occurred. This is "
            "consistent with the evidence but NOT a confirmed root cause — "
            "co-occurrence is not causation.",
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

    # Fetch ALL ~12 categories so the "most recurring" (by days) is visible even
    # if it is low by volume (e.g. KERNRTSP: 126 days but only ~4k lines).
    prof = tools.bgl_alert_profile(limit=50)
    by_days = sorted(prof["rows"], key=_recurring_key, reverse=True)
    out.append("OBSERVED — BGL alert categories, whole corpus — ranked by SPREAD "
               "(distinct days present), because one line is not one incident:")
    out += _fmt_rows(by_days,
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
        loudest = max(prof["rows"], key=lambda r: r.get("lines") or 0)
        recurring = by_days[0]                      # most days present
        rec_team = tools.team_for_bgl_alert(recurring["category"])
        nodes = tools.bgl_top_nodes_for_alert(recurring["category"], limit=3)["rows"]
        node_list = ", ".join(n["node"] for n in nodes) or "the affected nodes"
        share = loudest.get("peak_day_share")
        peak = loudest.get("peak_day")
        if share is not None and tools._is_burst(loudest):
            day = f" ({peak})" if peak else ""
            loud_desc = f"{float(share)*100:.1f}% of its lines fall on ONE day{day}"
        elif share is not None:
            loud_desc = f"spans {loudest['distinct_days']} days"
        else:
            loud_desc = f"spans {loudest['distinct_days']} day(s)"
        out += ["",
                f"HYPOTHESIS — the LOUDEST alert '{loudest['category']}' "
                f"({loudest['lines']:,} lines) is misleading: {loud_desc}. The "
                f"alert that actually RECURS is '{recurring['category']}' — "
                f"{recurring['distinct_days']} days "
                f"({recurring['first_seen']}..{recurring['last_seen']}), "
                f"{recurring['distinct_nodes']} nodes — owned by '{rec_team}'.",
                f"NEXT STEP — stand up a work item for '{recurring['category']}' "
                f"with {rec_team}; inspect nodes {node_list} first, and use "
                "trend_by_day to confirm it is still active. Treat the loud "
                "one-day categories as incident retrospectives, not ongoing work."]
    return "\n".join(out)


# ===========================================================================
#  MANAGER
# ===========================================================================
def answer_manager(question):
    """What deserves attention first and why — measured frequency only."""
    out = ["MANAGER — prioritized risks (measured frequency only)", ""]

    # Fetch ALL ~12 BGL alert categories so spread-ranking can surface a chronic
    # alert (e.g. KERNRTSP) that is low by volume but present on many days.
    prof = tools.bgl_alert_profile(limit=50)
    all_rows = prof["rows"]
    scope = tools.corpus_scope()
    bgl_n = scope.get("BGL")
    os_n = scope.get("OpenStack")
    os_txt = f"{os_n} lines" if os_n else "not loaded"
    out.append(f"DATA SCOPE — BGL: {bgl_n} lines; OpenStack: {os_txt} "
               "(whole corpus).")

    # Rank ALL categories by spread (days present; still-active first; bursts
    # de-prioritised), not by volume.
    by_spread = sorted(all_rows, key=_recurring_key, reverse=True)

    out += ["", "OBSERVED — BGL alerts ranked by SPREAD (days present, "
            "still-active first; one-day bursts flagged) — NOT by raw count:"]
    out += _fmt_rows(by_spread,
                     ["category", "lines", "distinct_nodes", "distinct_days",
                      "peak_day_share", "peak_day", "last_seen"],
                     [10, 9, 8, 7, 9, 11, 11])
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

    out += ["", "PRIORITIZED ACTIONS — sustained problems (many days) first, "
            "then OpenStack, then one-day bursts as retrospectives:"]
    # Split by burst-share: a category concentrated on one day (peak_day_share
    # >= 0.9) is a BURST even if a few scattered days exist; the rest are
    # sustained. Sustained already ranked by _recurring_key (still-active first).
    sustained = [r for r in by_spread if not tools._is_burst(r)]
    bursts = [r for r in by_spread if tools._is_burst(r)]
    rank = 1
    for row in sustained[:3]:
        cat = row["category"]
        team = tools.team_for_bgl_alert(cat)
        nodes = tools.bgl_top_nodes_for_alert(cat, limit=3)["rows"]
        node_list = ", ".join(n["node"] for n in nodes) or "affected nodes"
        out.append(
            f"  {rank}. BGL '{cat}' — SUSTAINED: {row['distinct_days']} days "
            f"({row['first_seen']}..{row['last_seen']}), {row['distinct_nodes']} "
            f"nodes, {row['lines']:,} lines. Route to {team}; "
            f"inspect nodes {node_list} first.")
        rank += 1
    if not _unavailable(osc):
        for row in osc["rows"][:1]:
            if row.get("error_lines"):
                out.append(f"  {rank}. OpenStack {row['component']} — "
                           f"{row['error_lines']} error-keyword lines "
                           f"({row['error_pct']}%). Owner: {row['team']}.")
                rank += 1
    for row in bursts[:1]:
        cat = row["category"]
        team = tools.team_for_bgl_alert(cat)
        share = row.get("peak_day_share")
        peak = row.get("peak_day")
        if share is not None:
            day = f" ({peak})" if peak else ""
            pct = f"{float(share)*100:.1f}% on a single day{day}"
        else:
            pct = "concentrated on one day"
        out.append(
            f"  {rank}. BGL '{cat}' — BURST: {row['lines']:,} lines, {pct}. "
            f"Treat as an incident retrospective, not an ongoing problem. "
            f"Owner: {team}.")
        rank += 1
    out.append(f"  {rank}. Monitor only: low-rate OpenStack services and small "
               "BGL components (Interconnect / Control System / Observability).")

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
