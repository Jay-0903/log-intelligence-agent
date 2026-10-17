# 5-Minute Demo Script

Goal: show the agent answering **one question per role** against the same base
corpus, with the **query evidence** behind every number. Keep to time — the
brief caps the demo at 5 minutes.

Have ready before you start:
- SereneDB running (`docker ps` shows the container, port 7890).
- Data loaded (`python load_logs.py --sample --loghub ./loghub` — or the full
  corpus for real numbers).
- A terminal in the repo folder.

---

## 0:00–0:30 — Framing (1 slide)

> "Millions of log lines don't fit in a prompt. So we don't send logs to the
> agent — we give it **tools**. SereneDB searches and counts; the agent explains
> the evidence and recommends a next step. Same corpus, same tools, three roles."

Show `docker ps` + the load summary (BGL + OpenStack line counts, both indexes
`[searchable]`). This establishes the **data scope** up front.

---

## 0:30–2:00 — Engineer: *what failed and what happened around it*

```powershell
python agent.py "engineer: kernel instruction cache parity error"
```

Point at the screen:
- **BM25 full-text** hit (`message @@ ts_phrase(...)`, ranked by `BM25(...)`).
- The **nearby-events** window around the top hit (±60s).
- **Observed vs. hypothesis vs. next step** — "logs show the symptom, not a
  confirmed root cause; next check is the KERNEL runbook + a wider window."
- Call out the `[query: ...]` line: *every claim is backed by a query that ran.*

> Note for judges: on the 2k sample these lines repeat; on the full 4.7M corpus
> the same tool returns varied nodes/timestamps.

---

## 2:00–3:30 — Team Lead: *what recurs and who owns it*

```powershell
python agent.py "teamlead: what alert patterns recur and which teams own them?"
```

Point at:
- **Whole-corpus** alert-category counts (KERNDTLB, KERNSTOR, APPSEV ...) — not a
  sample of retrieved lines.
- The **ownership join**: components rolled up to owning teams (Kernel Platform,
  Application Runtime ...).
- OpenStack per-service **problem rate**.
- Next step: route the top category to its team, confirm the trend first.

---

## 3:30–4:30 — Manager: *what to prioritize and why*

```powershell
python agent.py "manager: what should we prioritize?"
```

Point at:
- A short **ranked** list by measured frequency, each with an **owning team**.
- The explicit caveat: **counts of log lines, not confirmed incidents**; no
  invented downtime / cost / customer impact.

---

## 4:30–5:00 — MCP + close (1 slide)

> "The same tools are exposed over MCP, so a judge can connect Claude and ask
> these questions directly."

```powershell
python mcp_server.py
```

Show the tool list / a single Claude call if time allows. Close on the one-line
summary: *question → evidence (search + aggregation) → recommendation, per role,
every number checkable.*

---

## Backup one-liners (if a question comes up)

```powershell
python agent.py "engineer: nova scheduler error no valid host"   # OpenStack path
python tools.py                                                   # tool self-test
python agent.py "teamlead: trend"                                 # mentions trend_by_day
```
