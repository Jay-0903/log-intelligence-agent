# Worked Investigation — a recurring pattern in the base corpus

This is one end-to-end investigation of a real recurring pattern in the base
data, run against the **full corpus**: BGL (4,747,963 lines) and OpenStack
(207,820 lines), both loaded into SereneDB. For each role it shows the question,
the tool calls, the **executed query**, the **real result**, the answer, and the
recommended next step — then states what the data does and does not establish.

All numbers below came from queries that actually ran; the SQL is shown so each
can be re-checked. Data scope and filters are stated on every result.

## Headline finding

**KERNDTLB is the loudest BGL alert (152,734 lines) but not a recurring problem:
152,182 of those lines (99.6%) fell on a SINGLE day, 2005-06-12.** It is a burst
— one incident — not a chronic defect. The tools that make this visible are
`alert_profile` (lines vs. distinct nodes vs. distinct days) and `trend_by_day`.
The genuinely recurring problems, by days-present, are **KERNRTSP (126 days)**
and **APPSEV (70 days)**. This "what's loudest ≠ what recurs" distinction is the
core of the three role answers below.

---

## Agent tool-selection evidence — Claude over MCP

These are real sessions: **Claude Desktop connected to our `log-intelligence`
MCP server**, choosing and calling the tools itself (every answer is tagged
"Used Log-intelligence"). This is the agent the brief asks for; `agent.py` is a
deterministic, no-API-key reproduction of the same tool calls.

### Engineer — "investigate kernel instruction cache parity errors; show matching lines and what happened before/after"

**Tools Claude chose:** `search_logs_fulltext` (BGL) → `get_nearby_events`
(node-scoped, multiple windows).

**What it found (real result):** every "instruction cache parity error corrected"
line was on **one node, `R63-M0-N3-C:J02-U11`**, logged at INFO, labelled
non-alert (hardware corrected each one). It identified **two separate nightly
bursts**:

| Burst | Window | Pattern |
|-------|--------|---------|
| 1 | before 2005-11-04 23:58 → 2005-11-05 03:39:15 | steady, ~1–3 min apart, ≥3.7 hours |
| 2 | 2005-11-06 05:06:22 → ≥06:32:26 | same cadence; nothing on the node in the 30 min before |

**How it reasoned (from the evidence, not invented):**
- On the node: nothing but parity corrections in each window — no DDR errors, no
  machine checks, no FATAL lines, no job/app failures around the bursts.
- Across the cluster: ±2 min / ±5 min / ±1 h windows returned only this node's
  lines → rules out a shared midplane/power event.
- Dismissed unrelated noise: December "ddr error(s) ... corrected" on other nodes
  (R45, R65, R30, …) are separate memory errors weeks later, not connected.

**Answer (engineering read):** a persistent/degrading soft fault in the L1
instruction cache of one compute chip (J02-U11 on node card N3, midplane R63-M0).
Hardware parity corrects each error, so nothing *failed* — but it recurs every
few minutes for hours on two nights, which is typical of a **marginal part**, not
random cosmic-ray upsets.

**Next step:** flag `R63-M0-N3-C:J02-U11` for a diagnostic run or replacement
before the correction rate worsens or becomes uncorrectable.

**What the data does NOT establish:** no confirmed root cause or hardware RMA —
"marginal part" is a hypothesis consistent with the cadence; the logs show
corrected symptoms only.

### Team Lead — "which BGL alert categories recur most, which teams own them, and is the top one rising or steady?"

**Tools Claude chose:** `alert_profile` (spread) + `count_alerts_by_team`
(ownership) + `trend_by_day` (to test "rising or steady").

**Real result (whole corpus, 4,747,963 lines, Jun 2005 – Jan 2006):**

| Category | Lines | Nodes | Days seen | First–last | Owning team |
|----------|------:|------:|------:|-----------|-------------|
| KERNDTLB | 152,734 | 541 | 10 | Jun 5 – Nov 28 '05 | Kernel Platform |
| KERNSTOR | 63,491 | 22,529 | 4 | Jun 14 – Nov 22 '05 | Kernel Platform |
| APPSEV | 49,651 | 1,024 | 70 | Jul 20 '05 – Jan 3 '06 | Application Runtime |
| KERNMNTF | 31,531 | 1,024 | 26 | Aug 3 '05 – Jan 3 '06 | Kernel Platform |
| KERNTERM | 23,338 | 9,524 | 26 | Jul 1 – Nov 16 '05 | Kernel Platform |
| KERNREC | 6,145 | 4,609 | 7 | Oct 28 – Dec 17 '05 | Kernel Platform |
| APPREAD | 5,983 | 512 | 5 | Jun 4 – Jun 20 '05 | Application Runtime |
| KERNRTSP | 3,983 | 3,394 | **126** | Jun 5 '05 – Jan 3 '06 | Kernel Platform |

**Answer:** by volume the top category is KERNDTLB, but it is **neither rising nor
steady** — 99.6% of its lines are on 2005-06-12, then only 30 lines (Jul 18) and
10 (Nov 28). So it tops volume but barely recurs. The categories that *recur* are
**KERNRTSP (126 days, still firing on the last day of data)** and **APPSEV (70
days, across all 1,024 app nodes)**. Ownership: alerts split almost entirely
between **Kernel Platform** (KERNEL component, 284,344 alert lines) and
**Application Runtime** (APP, 63,845); category→team is matched by the KERN*/APP*
prefix, joined on component.

**Next step:** stand up work items for KERNRTSP and APPSEV (the chronic ones);
treat KERNDTLB as a one-day incident review.

### Manager — "what should we prioritise across BGL and OpenStack, and what next? Measured frequency only."

**Tools Claude chose:** `alert_profile` + `trend_by_day` + `openstack_by_component`.

**Real result + reasoning:** KERNDTLB tops volume but is one burst, so it is
**not** the top priority. Ranked by persistence (days present), the standing work
is KERNRTSP (126 days, still active), APPSEV (70 days), KERNMNTF (26 days, still
active). Kernel Platform carries ~82% of all BGL alert lines (284,344 of
348,460); Application Runtime ~18%.

**Full cross-dataset result (after the one-time OpenStack reload — see note):**
every figure a measured count over the whole corpus (4,747,963 BGL + 207,820
OpenStack lines).

OpenStack by nova service:

| Service | Owner (on-call) | Lines | Problem lines | Problem % |
|---------|-----------------|------:|------:|------:|
| nova-api | API Gateway (apigw-oncall) | 102,868 | 2,068 | 2.01% |
| nova-compute | Compute (compute-oncall) | 104,086 | 204 | 0.20% |
| nova-scheduler | Scheduler (sched-oncall) | 866 | 0 | 0.00% |

nova-api accounts for **91% of OpenStack problem lines (2,068 of 2,272)** — about
10× nova-compute's rate on similar volume.

**Priorities (ranked within each dataset — see the honesty note):**
1. BGL Kernel Platform long-running alerts: **KERNRTSP (126 days)** and
   **KERNMNTF (26 days)**, both still occurring at the end of the data; Kernel
   Platform owns ~82% of BGL alert lines (284,344 of 348,460).
2. BGL Application Runtime: **APPSEV** — 49,651 lines on 70 days, all 1,024 nodes.
3. OpenStack API Gateway: **nova-api errors** — 2,068 lines, 2.01%; the clear
   OpenStack priority (though far smaller absolute count than the BGL categories).
4. **Look back at the bursts but don't treat them as active:** KERNDTLB 99.6% on
   one day (2005-06-12); KERNSTOR on only 4 days.
5. Monitor only: nova-compute (0.20%), nova-scheduler (0), and the small BGL
   Interconnect / Control System / Observability components (271 alert lines).

**Cross-dataset honesty (Claude's own framing):** "The two datasets measure
different things — labelled alert lines in BGL, error-matched lines in OpenStack
— so I'm ranking within each dataset and treating raw counts as a rough guide to
scale, not a direct comparison." Exactly the distinction the `error_match`
naming was built to support.

**Next steps (as given):** kernel-oncall → KERNRTSP + KERNMNTF; apprt-oncall →
APPSEV; apigw-oncall → break down the 2,068 nova-api problem lines by error type;
Kernel Platform → short retrospective on the 2005-06-12 KERNDTLB burst; re-run
the view per period to confirm the patterns hold (BGL via `trend_by_day`,
OpenStack via the start/end dates).

**What the data does NOT establish:** counts are matching log lines, not
confirmed incidents; no financial loss / downtime / customer impact; OpenStack
"problem" means ERROR/CRITICAL level or error keywords (`error_match`), not the
dataset's labelled anomalies.

> **Note (resolved):** an earlier run showed OpenStack as "unavailable" — the
> tools queried `error_match` (renamed from `is_problem` in PR #4) while the
> loaded table still used the old schema, so the SELECT failed. The tools now
> surface the real SQL error and hint to reload; after one reload
> (`python load_logs.py --openstack ./data/OpenStack`) the full cross-dataset
> manager view above works, as shown.

---

## The pattern (worked below with executed SQL): a one-day burst of kernel TLB alerts

The sections below show the exact SQL and results behind the headline, for
re-checking. Across all 4.7M BGL lines the dominant alert category is **KERNDTLB**
(kernel data-TLB errors); the trend tool shows it is almost entirely **one day**.

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

**Observed:** KERNDTLB is the single loudest alert by volume (152,734 lines), and
the KERNEL component — owned by **Kernel Platform** — accounts for 284,344 of all
alert lines. But volume is not the same as recurrence (next section).

**Answer / next step:** do **not** start with the loudest alert. Rank by spread
(distinct days present), which shows the genuinely recurring problems are
**KERNRTSP (126 days)** and **APPSEV (70 days)** — not KERNDTLB. Treat KERNDTLB as
a one-day incident retrospective (see the trend below).

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

## Engineer

The engineer investigation is the real Claude-over-MCP session recorded at the
top of this doc ("Agent tool-selection evidence → Engineer"): a full-text search
for the parity error, then node-scoped `get_nearby_events`, which localised it to
one node (`R63-M0-N3-C:J02-U11`) across two nightly bursts and ruled out a
cluster-wide cause. That is the engineer thread; the team-lead/manager sections
below use aggregation over the whole corpus to find the burst-vs-chronic pattern.

---

## Manager — *what should we prioritize, and why?*

**Tool calls:** `alert_profile(limit=50)` — fetch ALL ~12 categories so a
chronic-but-low-volume alert surfaces — then rank by spread, plus
`openstack_by_component()`.
**OpenStack query:**
```sql
SELECT os.component, COALESCE(o.team,'Unmapped') AS team, COUNT(*) AS total,
       SUM(os.error_match) AS error_lines,
       ROUND((100.0*SUM(os.error_match)/COUNT(*))::NUMERIC,2) AS error_pct,
       ROUND(AVG(os.latency_ms)::NUMERIC,1) AS avg_latency_ms
FROM openstack_logs os
LEFT JOIN component_owners o ON o.dataset='OpenStack' AND o.component=os.component
GROUP BY os.component, team ORDER BY error_lines DESC;
```
**OpenStack result** — scope: OpenStack 207,820 lines, whole corpus:

| component | team | total | error_lines | error_pct | avg_latency_ms |
|-----------|------|------:|------:|------:|------:|
| nova-api | API Gateway | 102,868 | 2,068 | 2.01% | 234.1 |
| nova-compute | Compute | 104,086 | 204 | 0.20% | — |
| nova-scheduler | Scheduler | 866 | 0 | 0.00% | — |

> `error_lines`/`error_pct` count lines whose LEVEL is ERROR/CRITICAL or whose
> text matches error keywords — **not** the dataset's labelled anomalies
> (`anomaly_labels.txt` is not inline in the raw logs). Reported as an
> error-keyword rate.

**Prioritized actions — sustained problems (many days) first, then OpenStack,
then one-day bursts as retrospectives** (matches the recorded Claude session):

1. **BGL Kernel Platform, long-running: KERNRTSP (126 days) + KERNMNTF (26
   days)** — both still occurring at the end of the data. Kernel Platform owns
   ~82% of BGL alert lines (284,344 of 348,460). → kernel-oncall.
2. **BGL APPSEV — 70 days, all 1,024 app nodes → Application Runtime** (apprt-oncall).
3. **OpenStack nova-api — 2,068 error-keyword lines (2.01%) → API Gateway** — the
   clear OpenStack priority (far smaller absolute count than the BGL categories).
4. **Look back at the bursts, but don't treat them as active:** KERNDTLB is
   152,734 lines but **99.6% on one day (2005-06-12)**, and KERNSTOR appears on
   only 4 days. Run a retrospective, not a standing work item. → Kernel Platform.
5. **Monitor only:** nova-compute (0.20%), nova-scheduler (0 of 866), and the
   small BGL Interconnect / Control System / Observability components.

**Cross-dataset honesty:** the two datasets measure different things — labelled
alert lines in BGL, error-keyword lines in OpenStack — so we rank within each
dataset and treat raw counts as a rough guide to scale, not a direct comparison.

**What the data does NOT establish:** counts of **matching log lines, not
confirmed incidents**; no financial loss, downtime or customer impact. OpenStack
"errors" are keyword/level matches, not labelled anomalies. nova-scheduler shows
0 but only 866 lines — weak evidence. Priority = **spread (days x nodes) + clear
ownership**.

---

## How each role used the SAME corpus differently

| Role | Evidence selected | Decision |
|------|-------------------|----------|
| Engineer | full-text hit → node-scoped nearby events | localised corrected parity errors to node `R63-M0-N3-C:J02-U11` over two nightly bursts; flag that part for diagnostics |
| Team Lead | whole-corpus `alert_profile` (lines vs nodes vs days) + team rollup + trend | the loudest alert (KERNDTLB) spans 1 day; the recurring ones are KERNRTSP (126d) & APPSEV (70d) → route those to their teams |
| Manager | all categories ranked by spread + OpenStack error rates, each routed to its owner | sustained problems first (KERNRTSP/KERNMNTF, APPSEV), nova-api next, KERNDTLB as a one-day retrospective; no invented impact |

Same tools, same data — different questions, different evidence, different
next steps.
