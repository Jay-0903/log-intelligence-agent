# Slide Speaker Notes (≤5-minute demo)

Build 9 slides from these. Each has the on-slide content (bullets) and what to
SAY (speaker notes). All numbers are from the full-corpus run and are checkable
in the repo. Live-demo commands are in `docs/DEMO.md`.

Timing target: ~30s per slide + ~2 min of live terminal = under 5 minutes.

---

## Slide 1 — Title (0:00–0:20)

**On slide:**
- Log Intelligence Agent — the right insights for the right people
- SereneDB · "Making Sense of Logs" · BGL + OpenStack
- Engineer · Team Lead · Manager

**Say:** "Three people ask about the same logs and need different answers. We
built an agent that gives each of them the right evidence and a next step — with
every number backed by a query that actually ran."

---

## Slide 2 — The problem (0:20–0:45)

**On slide:**
- 4.7M BGL + 207K OpenStack lines — millions of lines don't fit in a prompt
- An agent can explain a failure, but it needs focused evidence, not raw logs
- Engineer / Team Lead / Manager → different evidence, different decisions

**Say:** "We don't send logs to the model. The database searches and counts; the
agent only sees a small relevant slice plus pre-computed summaries."

---

## Slide 3 — The approach (0:45–1:10)

**On slide:**
- Parameterized tools, not open-ended SQL — the agent picks a tool
- SereneDB does the work: BM25 full-text + whole-corpus aggregation
- Every result carries its SQL, filters, scope, row count, truncation flag

**Say:** "11 tools, each with a clear description. The agent chooses; SereneDB
runs it. And every answer shows its work, so a judge can re-check any number."

---

## Slide 4 — The tools (1:10–1:35)

**On slide (table):**
- Engineer: `search_logs_fulltext` (BM25 + time filter), `get_nearby_events`
- Team Lead: `alert_profile`, `count_alerts_by_team`, `trend_by_day`
- Manager: `openstack_by_component`, `alert_profile`, `top_nodes_for_alert`
- Any: `corpus_scope`, `team_ownership`
- Exposed over **MCP** (11 tools) + a CLI

**Say:** "Retrieval and aggregation. Full-text uses SereneDB's inverted index.
The ownership table maps components to teams, so we can say who owns a problem."

---

## Slide 5 — Engineer (LIVE) (1:35–2:35)

**Run:** `python agent.py "engineer: kernel instruction cache parity error"`

**Point at:**
- BM25-ranked hit on component KERNEL, node R02-M1-N0-...
- The ±60s nearby-events window (shows an adjacent L3 EDRAM correction)
- Observed → Hypothesis ("symptom, not confirmed root cause") → Next step

**Say:** "Full-text finds what failed; nearby events show the context. Note it was
*corrected* — a resiliency event, not an outage. We're explicit about what the
logs do and don't prove."

---

## Slide 6 — Team Lead + the key insight (LIVE) (2:35–3:30)

**Run:** `python agent.py "teamlead: what alert patterns recur and which teams own them?"`

**Point at:**
- Spread profile: KERNDTLB = 152,734 lines, on N nodes, over D days
- The trend: **152,182 of 152,734 (99.6%) fell on a single day, 2005-06-12**
- Ownership rollup → Kernel Platform; concrete nodes to inspect first

**Say:** "This is the headline. 'KERNDTLB recurs 152 thousand times' sounds
chronic — but the trend shows it's basically ONE day. That reframes it from 'a
defect' to 'investigate one incident.' That's what the aggregation tools are
for."

---

## Slide 7 — Manager (LIVE) (3:30–4:15)

**Run:** `python agent.py "manager: what should we prioritize?"`

**Point at:**
- Ranked by measured frequency + spread, each routed to its CORRECT owner
  (KERN* → Kernel Platform, APPSEV → Application Runtime)
- OpenStack nova-api 2.01% error rate, avg latency 234 ms
- The explicit note: counts of log lines, NOT confirmed incidents or impact

**Say:** "Prioritized, each with the right owning team and concrete nodes. And we
never invent downtime, cost or customer impact — the brief is strict about that,
and so are we."

---

## Slide 8 — Shows its work + MCP (4:15–4:40)

**On slide:**
- Every answer prints `[scope: ...]` and `[query: ...]`
- Facts vs. hypotheses vs. next steps are labelled
- `python mcp_server.py` → Claude connects and calls the same 11 tools

**Say:** "Same tools over MCP, so judges can connect Claude and ask these
questions directly using our setup instructions."

---

## Slide 9 — Scale + close (4:40–5:00)

**On slide:**
- Optional award: **1,000,000,000 rows of remote OTel Parquet, queried in place,
  zero download**
- `COUNT(*)` 0.1s · `GROUP BY service` 15.5s · `GROUP BY severity` 11.7s
- Honest finding: aggregation scales with no local state; a 1B-row full-text
  index needs more RAM than 6 GiB
- Runs from a clean checkout: Docker → loader → agent/MCP

**Say:** "And it scales — a billion rows of remote Parquet, no ingestion, answered
in seconds. One line of question → evidence → recommendation, per role, every
number checkable. Thank you."

---

## Backup / Q&A one-liners

- Full corpus load time: ~126s total (BGL 4.7M in ~41s via server read_csv).
- Time filters: `search_logs_fulltext(..., start='2005-06-03', end='2005-06-04')`.
- Both datasets used: BGL for search/trends, OpenStack for error-rate/latency.
- Ownership table: defined by us in `schema.py` (none was supplied by organisers).
