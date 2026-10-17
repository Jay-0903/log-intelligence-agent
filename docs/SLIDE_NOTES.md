# Slide deck — paste-ready copy (≤5-minute demo)

Copy one block per slide into PowerPoint / Google Slides. Each slide has the
**title**, the **on-slide bullets** (keep them terse), the **live action** (what
to show on screen), and **speaker notes** (what to say — ~20–35s each). All
numbers are from the full-corpus run and are checkable in `docs/INVESTIGATION.md`.

Timing: 9 slides, ~30s each + ~90s of live terminal/Claude = under 5 minutes.
Live commands are in `docs/DEMO.md`.

---

## Slide 1 — Title

**Title:** Log Intelligence Agent — the right insights for the right people

**On slide:**
- SchubKI National AI Hackathon 2026 · SereneDB
- BGL (4.7M lines) + OpenStack (207K lines), queried in SereneDB
- One workflow → three roles: Engineer · Team Lead · Manager
- Headline: the loudest alert is misleading — what's loud ≠ what recurs

**Speaker notes:** "Three people ask about the same logs and need different
answers. We built an agent that gives each of them the right evidence and a next
step — and every number is backed by a query that actually ran. Our headline
finding: the single loudest alert in the data is not the real problem."

---

## Slide 2 — The problem

**Title:** Millions of log lines don't fit in a prompt

**On slide:**
- An agent can *explain* a failure, but it needs focused evidence, not raw logs
- Same corpus, three different questions:
  - Engineer: what failed, where, what happened around it?
  - Team Lead: what recurs, how often, who owns it?
  - Manager: what to prioritise, and why?

**Speaker notes:** "You can't paste 4.7 million log lines into a model. So we
don't. The database does the searching and counting; the agent only sees a small,
relevant slice plus pre-computed summaries, and turns that into a role-specific
answer."

---

## Slide 3 — The approach

**Title:** The database does the work; the agent picks tools

**On slide:**
- SereneDB: BM25 full-text search + whole-corpus aggregation
- Agent chooses from **parameterised tools** — no open-ended SQL
- Every result returns its SQL, filters, data scope, row count, truncation flag
- Facts vs. hypotheses kept separate; no invented impact

**Speaker notes:** "The agent selects a tool and passes parameters; SereneDB runs
the query. Every answer shows its work — the exact SQL and the data scope — so a
judge can re-check any number. And we're strict about language: a cause is a
hypothesis unless the logs confirm it."

---

## Slide 4 — The tools (14, over MCP)

**Title:** 14 parameterised tools, exposed over MCP

**On slide:**
| Role | Tools |
|------|-------|
| Engineer | `search_logs_fulltext` (BM25 + time filter), `get_nearby_events`, `request_trace` |
| Team Lead | `alert_profile`, `count_alerts_by_team`, `trend_by_day` / `trend_by_week` |
| Manager | `openstack_by_component`, `latency_stats`, `top_nodes_for_alert` |
| Any | `corpus_scope`, `team_ownership`, `alert_categories` |

- Full-text uses SereneDB's inverted index: `@@ ts_phrase` + `BM25(idx.tableoid)`
- Ownership table maps components → teams

**Speaker notes:** "Retrieval and aggregation. The same tools are exposed over MCP,
so a judge can connect Claude and ask these questions directly using our setup."

---

## Slide 5 — Engineer (live)

**Title:** Engineer — investigate the alert the team flagged (KERNRTSP)

**On slide:**
- Claude chose: `search_logs_fulltext("rts panic")` → `top_nodes_for_alert` → `get_nearby_events`
- Two phases: Jun–Sep 2005 partition-wide bursts (2,048 panics on 06-14 alone) → steady ≤24/week trickle to Jan 2006
- 1–3 panics on nearly every node = whole fleet, not a few bad chips
- Latest panic, `R27-M0-NA-C:J11-U11`, 2006-01-03 (after a quiet hour):
  `KERNMC L2 d-cache parity` → ~19s register dump → `rts panic` → within 1s, `APPSEV "Link has been severed"` on I/O nodes R20–R27 → front-end `172.16.96.116` (130 lines / 130 nodes)
- **Hypothesis** (not fact): one chip's uncorrectable cache error *likely* killed a multi-rack job

**Live action:** run the engineer question in Claude (connected to
`log-intelligence`); point at the tool-call chips and the verbatim KERNMC → rts
panic → "Link has been severed" sequence.

**Speaker notes:** "Full-text finds the panic; nearby-events reconstructs the
~20-second chain on one node. We say *likely* and *consistent with* — the logs
give the sequence, not proof of cause. And we flag our own limit: 333 KERNMNTF
lines that day weren't time-correlated, so we don't tie them in."

---

## Slide 6 — Team Lead (live) — the key insight

**Title:** Team Lead — what's loud ≠ what recurs

**On slide:**
- Loudest by volume: **KERNDTLB, 152,734 lines** — but **99.6% on one day (2005-06-12)** → a burst, not a defect
- Ranked by **spread** (distinct days present), the most persistent problems are:
  - **KERNMC — 144 days** (machine checks; the most persistent of all 41 categories)
  - **KERNRTSP — 126 days**, still active on 2006-01-03, the final day of the data
  - **APPSEV — 70 days**, on 1,024 distinct nodes
- Ownership join: Kernel Platform owns ~82% of BGL alert lines

**Live action:** run the team-lead question; point at the spread table where
KERNRTSP (low volume) rises above KERNDTLB.

**Speaker notes:** "This is the heart of it. 'KERNDTLB happened 152 thousand
times' sounds like the top priority — but 99.6% of it is a single day. So we rank
by spread, not raw count, which surfaces KERNRTSP and APPSEV as the problems that
actually keep recurring."

---

## Slide 7 — Manager (live) — prioritise, honestly

**Title:** Manager — prioritise by spread + ownership, measured frequency only

**On slide:**
- Sustained problems first: **KERNMC + KERNRTSP + KERNMNTF (Kernel Platform)**, then **APPSEV (Application Runtime)**
- Then OpenStack: **nova-api — 2,068 error-keyword lines, 2.01%** (API Gateway)
- KERNDTLB framed as a **one-day retrospective**, not ongoing work
- Honest framing: BGL = labelled alerts; OpenStack = *error-keyword* lines, **not** labelled anomalies — ranked within each dataset, not compared directly

**Live action:** run the manager question; point at the ranked list and the
"measure different things" caveat.

**Speaker notes:** "The manager gets a ranked list, each routed to the correct
owning team, with concrete nodes to inspect. We never invent downtime, cost or
customer impact — only measured frequency and clear ownership."

---

## Slide 8 — Shows its work + runs clean

**Title:** Every number is checkable; runs from a clean checkout

**On slide:**
- Each answer prints `[scope: ...]` and `[query: ...]`; facts vs. hypotheses labelled
- Full-text verified: `message @@ ts_phrase(...)` ranked by `BM25(idx.tableoid)` (not substring)
- SQL verified against the SereneDB docs MCP (FTS, index refresh, read_parquet, date_trunc)
- Setup: Docker SereneDB → loader (BGL+OpenStack in ~2 min) → agent / MCP server

**Speaker notes:** "Nothing is hand-waved — the SQL is in every answer, and we
checked our operators against the official docs. It runs from a clean checkout:
start SereneDB in Docker, load the two datasets, connect Claude."

---

## Slide 9 — Scale + close

**Title:** It scales — and we know its limits

**On slide:**
- Optional award: **1,000,000,000 rows** of remote OpenTelemetry Parquet, queried **in place, zero download** (`read_parquet` over S3)
- `COUNT(*)` 0.1s · `GROUP BY service` ~15s · `GROUP BY severity` ~12s
- Honest limit: aggregation over remote Parquet scales freely; a full-text index on 1B rows needs more RAM than 6 GiB
- **One line:** question → evidence → recommendation, per role, every number checkable

**Speaker notes:** "And it scales — a billion rows of remote Parquet answered in
seconds with no ingestion. We also report where it breaks: indexing a billion-row
text field needs more memory. Question to evidence to recommendation, per role,
every number checkable. Thank you."

---

## Backup slides / Q&A one-liners (optional, keep hidden)

- **Why a rule-based `agent.py`?** It's a deterministic, no-API-key reproduction
  of the same tool calls — the *real* agent is Claude over MCP (shown live).
- **2k sample vs full corpus?** All figures here are the full 4.7M + 207K corpus;
  `--sample` is only for a quick offline demo.
- **Is the OpenStack "2.01%" a real anomaly rate?** No — it's an error-keyword /
  level rate; the labelled anomalies aren't inline in the raw logs, and we say so.
- **Both datasets used?** Yes — BGL for search/trend, OpenStack for
  error-rate/latency; counts reported per dataset, not merged.
