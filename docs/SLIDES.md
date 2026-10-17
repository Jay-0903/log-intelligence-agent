# Slides Outline — Log Intelligence Agent

Suggested 8 slides for a ≤5-minute presentation. Each slide lists the headline,
the key points, and what to show live. Export to your deck tool of choice.

---

## Slide 1 — Title

**Log Intelligence Agent — the right insights for the right people**

- SchubKI National AI Hackathon 2026 · SereneDB challenge
- Base corpus: BGL (search/trends) + OpenStack (aggregation)
- One workflow: question → evidence → recommendation, for 3 roles

---

## Slide 2 — The problem

- Millions of log lines don't fit in a prompt.
- An agent can *explain* a failure, but it needs **focused evidence**, not raw logs.
- Three people ask about the same logs and need **different** evidence and decisions:
  Engineer / Team Lead / Manager.

---

## Slide 3 — The approach

- **The database does the work.** SereneDB searches (BM25 full-text) and
  aggregates (counts, trends, latency) *before* anything reaches the agent.
- **The agent picks parameterized tools** — no open-ended SQL.
- **Every number is checkable** — each tool returns the SQL, filters, scope, row
  count and a truncation flag.

Diagram: `question → [agent picks tool] → SereneDB query → evidence → answer`.

---

## Slide 4 — The tools

| Role | Tools |
|------|-------|
| Engineer | `search_logs_fulltext` (BM25), `get_nearby_events` |
| Team Lead | `alert_categories`, `count_alerts_by_team`, `trend_by_day` |
| Manager | `openstack_by_component`, `latency_stats`, `alert_categories` |
| Any | `corpus_scope`, `team_ownership` |

- Retrieval **and** aggregation. Full-text uses `@@ ts_phrase` + `BM25(...)`.
- Ownership table maps components → teams.

---

## Slide 5 — Engineer (live)

- Question: *"kernel instruction cache parity error"*
- Show: BM25-ranked hits on `KERNEL`, then the ±60s nearby-events window.
- Observed → Hypothesis (symptom, not confirmed cause) → Next step (runbook +
  wider window).

---

## Slide 6 — Team Lead & Manager (live)

- Team Lead: whole-corpus recurring categories + owning teams + OpenStack problem
  rate → route to the owning team, confirm the trend.
- Manager: ranked by measured frequency, each with an owner; **no invented**
  downtime / cost / customer impact.

---

## Slide 7 — Shows its work + MCP

- Each answer prints `[scope: ...]` and `[query: ...]`.
- Facts vs. hypotheses vs. next steps are labelled.
- Exposed over **MCP** — a judge can connect Claude and ask directly.

---

## Slide 8 — What it does / doesn't establish + close

- Counts are **matching log lines**, not de-duplicated incidents.
- Logs don't establish business impact — we don't invent it.
- Runs from a clean checkout: Docker + loader + agent/MCP.
- One line: *question → evidence → recommendation, per role, every number checkable.*
