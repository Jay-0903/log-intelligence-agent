# 5-Minute Demo Script

Goal: show the agent answering **one question per role** against the same base
corpus, with the **query evidence** behind every number. Keep to time — the brief
caps the demo at 5 minutes. Aligns with the 9-slide deck (`docs/slides.pdf`).

Have ready before you start:
- SereneDB running (`docker ps` shows the container, port 7890).
- The **full corpus** loaded (the deck's numbers are the full corpus, not the
  sample):
  ```powershell
  python load_logs.py --server-bgl /data/BGL.log --openstack ./data/openstack
  ```
- A terminal in the repo folder; optionally Claude Desktop connected to the
  `log-intelligence` MCP server.

---

## 0:00–0:30 — Framing (slides 1–3)

> "Millions of log lines don't fit in a prompt. So we don't send logs to the
> agent — we give it **tools**. SereneDB searches and counts; the agent explains
> the evidence and recommends a next step. Same corpus, same tools, three roles."

Show `docker ps` + the load summary (BGL 4,747,963 + OpenStack 207,820, both
indexes `[searchable]`). This establishes the **data scope** up front.

---

## 0:30–2:00 — Engineer: *investigate the alert the team flagged* (slide 5)

Same thread as team-lead/manager: they flag the persistent kernel alerts
(KERNMC 144 days, KERNRTSP 126 days); the engineer drills into the KERNRTSP panic.

```powershell
python agent.py "engineer: rts panic"
```

Point at the screen:
- **BM25 full-text** hit (`message @@ ts_phrase(...)` ranked by `BM25(...)`),
  `method: BM25 full-text`, score 8.382 — the panic on `R27-M0-NA-C:J11-U11`,
  2006-01-03 03:25:05 (id 4746673).
- `top_nodes_for_alert("KERNRTSP")` → nearly all nodes have 1–3 panics
  (whole-fleet, not a few bad chips); outlier `R63-M0-NE-C:J12-U01` (22).
- **Node-scoped `get_nearby_events`** on R27-M0-NA → the verbatim cascade:
  `KERNMC` L2 d-cache parity machine check (03:24:46) → ~19 s register dump →
  `rts panic` (03:25:05).
- **Observed vs. hypothesis vs. next step** — a KERNMC turning into a KERNRTSP
  panic is *likely* a hardware cache fault, *consistent with* the sequence, **not
  a confirmed root cause**. Call out the `[query: ...]` line: every claim is
  backed by a query that ran.

---

## 2:00–3:30 — Team Lead: *what recurs and who owns it* (slide 6)

```powershell
python agent.py "teamlead: what alert patterns recur and which teams own them?"
```

Point at:
- **Whole-corpus** profile of all **41** alert categories, ranked by **spread**
  (distinct days present), not raw count.
- The headline: KERNDTLB is loudest (152,734 lines) but **99.6% on one day
  (2005-06-12)** — a burst. The persistent ones are **KERNMC (144 days)** and
  **KERNRTSP (126 days)**.
- The **ownership join**: components rolled up to owning teams (Kernel Platform,
  Application Runtime).
- OpenStack per-service **error-keyword rate** (ERROR/CRITICAL level or error
  words — **not** the dataset's labelled anomalies).
- Next step: route the persistent categories to their owning team.

---

## 3:30–4:30 — Manager: *what to prioritize and why* (slide 7)

```powershell
python agent.py "manager: what should we prioritize?"
```

Point at:
- A short list **ranked by spread** (days present, still-active first); one-day
  **bursts** (`peak_day_share >= 0.9`, e.g. KERNDTLB) listed as retrospectives,
  not ongoing work. Each item routed to its **owning team** with concrete nodes.
- OpenStack nova-api 2.01% **error-keyword** rate.
- The explicit caveat: **counts of log lines, not confirmed incidents**; no
  invented downtime / cost / customer impact.

---

## 4:30–5:00 — MCP + close (slides 8–9)

> "The same 16 tools are exposed over MCP, so a judge can connect Claude and ask
> these questions directly."

```powershell
python mcp_server.py
```

Show the tool list / a single Claude call if time allows (and the optional
1-billion-row remote-Parquet result, slide 9). Close on the one-line summary:
*question → evidence (search + aggregation) → recommendation, per role, every
number checkable.*

---

## Backup one-liners (if a question comes up)

```powershell
python agent.py "engineer: nova scheduler error no valid host"   # OpenStack path
python tools.py                                                   # tool self-test
python agent.py "teamlead: trend"                                 # mentions trend_by_day/week
```
