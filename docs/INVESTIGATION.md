# Worked Investigation — a recurring pattern in the base corpus

This is one end-to-end investigation of a real recurring pattern in the base
data, run against the **full corpus**: BGL (4,747,963 lines) and OpenStack
(207,820 lines), both loaded into SereneDB. For each role it shows the question,
the tool calls, the **executed query**, the **real result**, the answer, and the
recommended next step — then states what the data does and does not establish.

All numbers below came from queries that actually ran; the SQL is shown so each
can be re-checked. Data scope and filters are stated on every result.

---

## The pattern: a one-day burst of kernel TLB alerts

Across all 4.7M BGL lines the dominant alert category is **KERNDTLB** (kernel
data-TLB errors). The team-lead view surfaces it; the trend tool shows it is not
spread evenly — it is almost entirely **one day**.

---

## Team Lead — *which problems recur, how often, and who owns them?*

**Tool call:** `alert_categories(limit=8)`
**Query:**
```sql
SELECT alert AS category, COUNT(*) AS n
FROM bgl_logs WHERE alert <> '-'
GROUP BY alert ORDER BY n DESC LIMIT 8;
```
**Result** — scope: BGL 4,747,963 lines, whole corpus (truncated at 8):

| category | n |
|----------|------:|
| KERNDTLB | 152,734 |
| KERNSTOR | 63,491 |
| APPSEV | 49,651 |
| KERNMNTF | 31,531 |
| KERNTERM | 23,338 |
| KERNREC | 6,145 |
| APPREAD | 5,983 |
| KERNRTSP | 3,983 |

**Tool call:** `count_alerts_by_team(limit=8)`
**Query:**
```sql
SELECT COALESCE(o.team,'Unmapped') AS team, b.component,
       COUNT(*) AS events,
       SUM(CASE WHEN b.alert <> '-' THEN 1 ELSE 0 END) AS alert_events
FROM bgl_logs b
LEFT JOIN component_owners o ON o.dataset='BGL' AND o.component=b.component
GROUP BY team, b.component ORDER BY alert_events DESC, events DESC LIMIT 8;
```
**Result** — scope: BGL whole corpus:

| team | component | alert_events | events |
|------|-----------|------:|------:|
| Kernel Platform | KERNEL | 284,344 | 4,324,651 |
| Application Runtime | APP | 63,845 | 228,536 |
| Interconnect | LINKCARD | 206 | 1,170 |
| Control System | BGLMASTER | 47 | 145 |
| Observability | MONITOR | 15 | 1,681 |
| Control System | MMCS | 3 | 88,930 |
| Provisioning | DISCOVERY | 0 | 97,172 |
| Hardware Ops | HARDWARE | 0 | 5,148 |

**Observed:** KERNDTLB is the single most frequent alert (152,734). The KERNEL
component — owned by **Kernel Platform** — accounts for 284,344 of all alert
lines, by far the most. APP (Application Runtime) is a distant second (63,845).

**Answer / next step:** Kernel Platform owns the largest share of alerts; have
them review KERNDTLB first. But before committing effort, check whether it is a
steady background rate or a one-off — use the trend tool (below).

---

## The trend — the recurring pattern is really one day

**Tool call:** `bgl_trend_by_day(category="KERNDTLB", limit=20)`
**Query:**
```sql
SELECT CAST(to_timestamp(ts) AS DATE) AS day, COUNT(*) AS alert_events
FROM bgl_logs WHERE ts > 0 AND alert = 'KERNDTLB'
GROUP BY day ORDER BY day LIMIT 20;
```
**Result** — scope: BGL whole corpus:

| day | alert_events |
|-----|------:|
| 2005-06-05 | 477 |
| **2005-06-12** | **152,182** |
| 2005-07-15 | 1 |
| 2005-07-18 | 30 |
| 2005-08-16 | 9 |
| 2005-08-17 | 5 |
| 2005-08-18 | 15 |
| 2005-08-24 | 4 |
| 2005-11-24 | 1 |
| 2005-11-28 | 10 |

**Observed:** of 152,734 KERNDTLB events, **152,182 (99.6%) occurred on a single
day, 2005-06-12.** Every other day is in the single/double/triple digits.

**This is the key insight:** "KERNDTLB recurs 152k times" is misleading on its
own. It is one concentrated burst, not a chronic daily problem. The right
framing for the team is *"a single-day KERNDTLB storm on 2005-06-12,"* which
points at an event (a node/rack incident that day), not an ongoing defect.

---

## Engineer — *what failed, where, and what happened around it?*

**Tool call:** `search_logs_fulltext(dataset="bgl",
phrase="kernel instruction cache parity error")`
**Query:**
```sql
SELECT id, alert, ts, node, event_time AS "datetime", severity, component,
       message, ROUND(BM25(bgl_idx.tableoid)::NUMERIC,3) AS score
FROM bgl_idx
WHERE (message @@ ts_phrase('kernel') OR message @@ ts_phrase('instruction')
       OR message @@ ts_phrase('cache') OR message @@ ts_phrase('parity')
       OR message @@ ts_phrase('error'))
ORDER BY score DESC LIMIT 8;
```
**Result** — scope: BGL whole corpus; top hit on node `R02-M1-N0-C:J12-U11`,
component KERNEL, message *"instruction cache parity error corrected"*
(8 near-identical hits collapsed, occurrence count n=8).

**Tool call:** `get_nearby_events(ts=1119321024, window_seconds=60)`
**Query:**
```sql
SELECT id, alert, ts, node, event_time AS "datetime", severity, component, message
FROM bgl_logs WHERE ts > 0 AND ts BETWEEN %s AND %s ORDER BY ts, id LIMIT %s;
```
**Result** — the window shows the parity-error line alongside
*"224 L3 EDRAM error(s) (dcr 0x0157) detected and corrected"* on a nearby node.

**Observed:** a cache/EDRAM parity error that was **corrected** (severity INFO,
not FATAL), co-occurring with L3 EDRAM corrections on adjacent hardware.

**Hypothesis (not confirmed):** the symptom is localised to KERNEL on that node;
the nearby EDRAM corrections suggest memory-subsystem noise rather than a crash.
The logs show the error was *corrected*, so this is a resiliency event, not an
outage — but the logs alone do not confirm root cause.

**Next step:** widen the window (`get_nearby_events` with a larger
`window_seconds`) to see if the same node repeats; check the Kernel Platform
runbook for corrected cache-parity events.

---

## Manager — *what should we prioritize, and why?*

**Tool calls:** `alert_categories(limit=5)` + `openstack_by_component()`
**OpenStack query:**
```sql
SELECT os.component, COALESCE(o.team,'Unmapped') AS team, COUNT(*) AS total,
       SUM(os.is_problem) AS problems,
       ROUND((100.0*SUM(os.is_problem)/COUNT(*))::NUMERIC,2) AS problem_pct,
       ROUND(AVG(os.latency_ms)::NUMERIC,1) AS avg_latency_ms
FROM openstack_logs os
LEFT JOIN component_owners o ON o.dataset='OpenStack' AND o.component=os.component
GROUP BY os.component, team ORDER BY problems DESC;
```
**OpenStack result** — scope: OpenStack 207,820 lines, whole corpus:

| component | team | total | problems | problem_pct | avg_latency_ms |
|-----------|------|------:|------:|------:|------:|
| nova-api | API Gateway | 102,868 | 2,068 | 2.01% | 234.1 |
| nova-compute | Compute | 104,086 | 204 | 0.20% | — |
| nova-scheduler | Scheduler | 866 | 0 | 0.00% | — |

**Prioritized actions (by measured frequency, each routed to its real owner):**

1. **BGL KERNDTLB — 152,734 events → Kernel Platform.** But note the trend: this
   is one burst on 2005-06-12. Treat as *investigate that day's incident*, not an
   ongoing defect.
2. **BGL KERNSTOR — 63,491 events → Kernel Platform.** Kernel storage errors;
   same owner, worth bundling with #1.
3. **BGL APPSEV — 49,651 events → Application Runtime.** (Correctly routed to the
   application team, not kernel.)
4. **OpenStack nova-api — 2,068 problem lines (2.01%) → API Gateway.** Highest
   error rate of the nova services; avg latency 234 ms.
5. **OpenStack nova-compute — 204 problem lines (0.20%) → Compute.** Low rate.

**What the data does NOT establish:** these are counts of **matching log lines,
not confirmed incidents**, and the logs do not establish financial loss, downtime
or customer impact. nova-scheduler has 0 flagged problems but only 866 lines — a
small sample, so "no problems" there is weak evidence. Priority here means
**measured frequency + clear ownership**, nothing more.

---

## How each role used the SAME corpus differently

| Role | Evidence selected | Decision |
|------|-------------------|----------|
| Engineer | full-text hit + ±60s nearby events on one node | drill into one corrected parity event; widen window |
| Team Lead | whole-corpus category counts + team rollup + trend | route KERNDTLB to Kernel Platform, but confirm it is one day |
| Manager | top categories + OpenStack error rates, each routed to its owner | ranked priorities with correct owners; no invented impact |

Same tools, same data — different questions, different evidence, different
next steps.
