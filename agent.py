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
        out.append(f"OBSERVED — top OpenStack matches for '{phrase}':")
        out += _fmt_rows(env["rows"],
                         ["level", "component", "message"], [6, 14, 80])
        out.append(_provenance(env))
        out += ["", "HYPOTHESIS — the highest-scoring lines point at the component above.",
                "NEXT STEP — pull the request_id from a hit and grep nearby lines for "
                "the same request to see the full request lifecycle."]
        return "\n".join(out)

    # BGL: full-text search, then nearby events around the top hit.
    env = tools.search_bgl_fulltext(phrase, limit=8)
    rows = env["rows"]
    out.append(f"OBSERVED — top BGL matches for '{phrase}' (BM25 ranked):")
    out += _fmt_rows(rows, ["severity", "node", "component", "message"],
                     [7, 20, 10, 70])
    out.append(_provenance(env))

    if rows and rows[0].get("ts"):
        ts = rows[0]["ts"]
        near = tools.get_nearby_events_bgl(ts, window_seconds=60, limit=8)
        out += ["", f"OBSERVED — context +/-60s around the top hit (ts={ts}):"]
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

    cats = tools.count_bgl_alert_categories(limit=8)
    out.append("OBSERVED — BGL alert categories, whole corpus (most frequent first):")
    out += _fmt_rows(cats["rows"], ["category", "n"], [16, 10])
    out.append(_provenance(cats))

    teams = tools.count_bgl_alerts_by_team(limit=8)
    out += ["", "OBSERVED — BGL events by owning team / component (alerts first):"]
    out += _fmt_rows(teams["rows"], ["team", "component", "alert_events", "events"],
                     [20, 12, 12, 10])
    out.append(_provenance(teams))

    osc = tools.count_openstack_by_component()
    out += ["", "OBSERVED — OpenStack problem rate by nova service, whole corpus:"]
    out += _fmt_rows(osc["rows"],
                     ["component", "team", "total", "problems", "problem_pct"],
                     [16, 14, 8, 9, 11])
    out.append(_provenance(osc))

    top_cat = cats["rows"][0]["category"] if cats["rows"] else "the top category"
    top_team = teams["rows"][0]["team"] if teams["rows"] else "the top team"
    out += ["",
            f"HYPOTHESIS — '{top_cat}' is the dominant recurring BGL alert; it maps to "
            f"the '{top_team}' team.",
            f"NEXT STEP — ask {top_team} to review '{top_cat}' first; use trend_by_day "
            f"on that category to confirm whether it is rising or steady before "
            "committing effort."]
    return "\n".join(out)


# ===========================================================================
#  MANAGER
# ===========================================================================
def answer_manager(question):
    """What deserves attention first and why — measured frequency only."""
    out = ["MANAGER — prioritized risks (measured frequency only)", ""]

    cats = tools.count_bgl_alert_categories(limit=5)
    scope = tools.corpus_scope()
    out.append(f"DATA SCOPE — BGL: {scope.get('BGL')} lines; "
               f"OpenStack: {scope.get('OpenStack')} lines (whole corpus).")
    out += ["", "OBSERVED — most frequent BGL alert categories:"]
    out += _fmt_rows(cats["rows"], ["category", "n"], [16, 10])
    out.append(_provenance(cats))

    osc = tools.count_openstack_by_component()
    out += ["", "OBSERVED — OpenStack services ranked by problem count:"]
    out += _fmt_rows(osc["rows"],
                     ["component", "team", "problems", "problem_pct"],
                     [16, 14, 9, 11])
    out.append(_provenance(osc))

    out += ["", "PRIORITIZED ACTIONS (by measured frequency, highest first):"]
    rank = 1
    for row in cats["rows"][:3]:
        teams = tools.count_bgl_alerts_by_team(limit=50)["rows"]
        team = next((t["team"] for t in teams
                     if t.get("alert_events")), "the owning team")
        out.append(f"  {rank}. BGL '{row['category']}' — {row['n']} events. "
                   f"Route to {team}.")
        rank += 1
    for row in osc["rows"][:2]:
        if row.get("problems"):
            out.append(f"  {rank}. OpenStack {row['component']} — {row['problems']} "
                       f"problem lines ({row['problem_pct']}%). Owner: {row['team']}.")
            rank += 1

    out += ["",
            "NOTE — these are counts of matching log lines, not confirmed incidents, "
            "and the logs do not establish financial loss, downtime or customer "
            "impact. Priority here means measured frequency and clear ownership."]
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
