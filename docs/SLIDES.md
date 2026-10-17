# Slides Outline — Log Intelligence Agent

Suggested 9 slides for a ≤5-minute presentation. Each slide lists the headline,
the key points, and what to show live. Export to your deck tool of choice.

> **Ready to paste:** `docs/SLIDE_NOTES.md` has complete, copy-ready slide copy
> (title + bullets + live action + speaker notes) with the real full-corpus
> numbers — assemble the deck from that; this file is the shorter outline.

---

## Slide 1 — Title

**Log Intelligence Agent — the right insights for the right people**

- SchubKI National AI Hackathon 2026 · SereneDB challenge
- Base corpus: BGL (search/trends) + OpenStack (aggregation)
- One workflow: question → evidence → recommendation, for 3 roles
- **Headline:** the loudest BGL alert (KERNDTLB, 152,734 lines) is **not**
  recurring — **99.6% fell on one day (2005-06-12)**. What's loud ≠ what recurs.

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

## Slide 5 — Engineer (live, same thread: investigate the alert the team lead flagged)

- Team lead/manager prioritised **KERNRTSP** (126 days) → engineer investigates it.
- Claude chose `search_logs_fulltext("rts panic")` → `top_nodes_for_alert` →
  `get_nearby_events` (node-scoped).
- Two phases: Jun–Sep 2005 partition-wide bursts (2,048 panics on 06-14 alone =
  >half of KERNRTSP) → steady ≤24/week trickle to Jan 2006. 1–3 panics on nearly
  every node = whole-fleet, not a few bad chips.
- Latest occurrence `R27-M0-NA-C:J11-U11` (2006-01-03), after a quiet hour:
  `KERNMC L2 dcache parity error` → ~19s register dump → `rts panic` → within 1s,
  `APPSEV ciod ... Link has been severed` on I/O nodes (R20–R27) to front-end
  172.16.96.116 (130 APPSEV lines / 130 nodes that day).
- **Hypothesis** (not fact): one chip's uncorrectable cache error **likely** took
  down a multi-rack job — **consistent with** the chain. Honest caveat: 333
  KERNMNTF lines that day weren't time-correlated, so not tied in.

---

## Slide 6 — Team Lead & Manager (live)

- Team Lead: whole-corpus counts show KERNDTLB leads (152,734), but
  **`trend_by_day` reveals 99.6% fell on one day (2005-06-12)** — the real
  insight. Route to Kernel Platform, but as a one-day incident, not a defect.
  The *actually* recurring alerts are **KERNRTSP (126 days)** and **APPSEV (70
  days)** — Claude reasoned this from `alert_profile` + `trend_by_day`.
- Manager: ranked by **persistence** (days present), each routed to its correct
  owner (KERN* → Kernel Platform, APP* → Application Runtime). **No invented**
  downtime / cost / customer impact; when OpenStack was unavailable it said so
  rather than guessing.

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
