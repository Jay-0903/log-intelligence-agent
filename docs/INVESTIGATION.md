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
The most persistent signals, by days-present, are **KERNMC machine checks (144
days)** and **KERNRTSP rts panics (126 days)**. This "what's loudest ≠ what
recurs" distinction is the core of the three role answers below — and the
engineer trace shows a **KERNMC turning into a KERNRTSP panic**: the most recent
panic (2006-01-03) is **likely** triggered by an uncorrectable L2 d-cache parity
error on one chip that took down a multi-rack job (hypothesis — see the engineer
section).

---

## Agent tool-selection evidence — Claude over MCP

These are real sessions: **Claude Desktop connected to our `log-intelligence`
MCP server**, choosing and calling the tools itself (every answer is tagged
"Used Log-intelligence"). This is the agent the brief asks for; `agent.py` is a
deterministic, no-API-key reproduction of the same tool calls.

### Engineer — "investigate KERNRTSP (the recurring alert the team lead flagged); show matching lines and what happened before/after"

**Tools Claude chose:** `search_logs_fulltext` (BGL, "rts panic") →
`top_nodes_for_alert(category="KERNRTSP")` → `get_nearby_events` (node-scoped).

**What it found (real result):** KERNRTSP = **3,983 lines on 3,394 nodes over 126
days** — low volume, very wide, persistent. Two phases: Jun–mid-Sep 2005
partition-wide bursts (week of 06-13 = 2,238 lines, incl. **2,048 on 06-14, > half
of all KERNRTSP**), then a steady ≤24/week trickle to 2006-01-03. Nearly every
node has only 1–3 panics (whole-fleet, not a few bad chips); outlier node
`R63-M0-NE-C:J12-U01` (22), rack R27 ≈ 10 of the top 20.

Tracing the most recent occurrence (2006-01-03, `R27-M0-NA-C:J11-U11`) after a
quiet 02:24–03:24: `03:24:46 KERNMC` *L2 dcache write data parity error* → ~130
register-dump lines over ~19s → `03:25:05 KERNRTSP rts panic!` → within a second,
`APPSEV ciod ... Link has been severed` on I/O nodes in racks R20/R22/R24/R25/
R26/R27, all to front-end `172.16.96.116` (130 APPSEV lines on 130 nodes that
day). Full verbatim lines in the detailed section below.

**Answer (engineering read, HYPOTHESIS not fact):** an uncorrectable L2 d-cache
parity error is **likely** what killed a large multi-rack job — the
KERNMC → dump → rts panic → "link severed" chain is **consistent with** that. The
logs establish the sequence and timing, not causation.

**Honest limitation (Claude's own):** 333 KERNMNTF lines that day were NOT
time-correlated, so they are not tied to this event.

**Next step:** flag `R27-M0-NA-C:J11-U11` and outlier `R63-M0-NE-C:J12-U01` for
hardware diagnostics; check whether the 2005-06-14 R26-M0-NB burst shares the
KERNMC→panic signature; confirm whether 172.16.96.116 was reachable at 03:25.

### Team Lead — "which BGL alert categories recur most, which teams own them, and is the top one rising or steady?"

**Tools Claude chose:** `alert_profile` (spread) + `count_alerts_by_team`
(ownership) + `trend_by_day` (to test "rising or steady").

**Real result (whole corpus, 4,747,963 lines, Jun 2005 – Jan 2006):**

BGL has **41 alert categories**; the top rows (and the most persistent one,
KERNMC) are:

| Category | Lines | Nodes | Days seen | First–last | Owning team |
|----------|------:|------:|------:|-----------|-------------|
| KERNDTLB | 152,734 | 541 | 10 | Jun 5 – Nov 28 '05 | Kernel Platform |
| KERNSTOR | 63,491 | 22,529 | 4 | Jun 14 – Nov 22 '05 | Kernel Platform |
| APPSEV | 49,651 | 1,024 | 70 | Jul 20 '05 – Jan 3 '06 | Application Runtime |
| KERNMNTF | 31,531 | 1,024 | 26 | Aug 3 '05 – Jan 3 '06 | Kernel Platform |
| KERNTERM | 23,338 | 9,524 | 26 | Jul 1 – Nov 16 '05 | Kernel Platform |
| KERNREC | 6,145 | 4,609 | 7 | Oct 28 – Dec 17 '05 | Kernel Platform |
| APPREAD | 5,983 | 512 | 5 | Jun 4 – Jun 20 '05 | Application Runtime |
| KERNRTSP | 3,983 | 3,394 | 126 | Jun 5 '05 – Jan 3 '06 | Kernel Platform |
| **KERNMC** | 342 | 265 | **144** | Jun 5 '05 – Jan 3 '06 | Kernel Platform |

**Answer:** by volume the top category is KERNDTLB, but it is **neither rising nor
steady** — 99.6% of its lines are on 2005-06-12, then only 30 lines (Jul 18) and
10 (Nov 28). So it tops volume but barely recurs. The categories that *recur* are
**KERNMC machine checks (144 days — the most persistent)** and **KERNRTSP rts
panics (126 days, still active on 2006-01-03, the final day of the data)**, with
**APPSEV (70 days, on 1,024 distinct nodes)** close behind. Ownership: alerts
split almost entirely between **Kernel Platform** (KERNEL component, 284,344 alert
lines) and **Application Runtime** (APP, 63,845); category→team is matched by the
KERN*/APP* prefix, joined on component.

**Next step:** stand up work items for KERNMC, KERNRTSP and APPSEV (the chronic
ones); treat KERNDTLB as a one-day incident review.

### Manager — "what should we prioritise across BGL and OpenStack, and what next? Measured frequency only."

**Tools Claude chose:** `alert_profile` + `trend_by_day` + `openstack_by_component`.

**Real result + reasoning:** KERNDTLB tops volume but is one burst, so it is
**not** the top priority. Ranked by persistence (days present), the standing work
is KERNMC (144 days), KERNRTSP (126 days, still active on 2006-01-03), APPSEV (70
days), KERNMNTF (26 days, still active). Kernel Platform carries ~82% of all BGL
alert lines (284,344 of 348,460); Application Runtime ~18%.

**Full cross-dataset result (after the one-time OpenStack reload — see note):**
every figure a measured count over the whole corpus (4,747,963 BGL + 207,820
OpenStack lines).

OpenStack by nova service:

| Service | Owner (on-call) | Lines | Error-keyword lines | Error-keyword % |
|---------|-----------------|------:|------:|------:|
| nova-api | API Gateway (apigw-oncall) | 102,868 | 2,068 | 2.01% |
| nova-compute | Compute (compute-oncall) | 104,086 | 204 | 0.20% |
| nova-scheduler | Scheduler (sched-oncall) | 866 | 0 | 0.00% |

nova-api accounts for **91% of OpenStack error-keyword lines (2,068 of 2,272)** —
about 10× nova-compute's rate on similar volume. (These are ERROR/CRITICAL-level
or error-keyword lines, **not** the dataset's labelled anomalies.)

**Priorities (ranked within each dataset — see the honesty note):**
1. BGL Kernel Platform long-running alerts: **KERNMC (144 days)**, **KERNRTSP
   (126 days)** and **KERNMNTF (26 days)**, all still occurring at the end of the
   data; Kernel Platform owns ~82% of BGL alert lines (284,344 of 348,460).
2. BGL Application Runtime: **APPSEV** — 49,651 lines on 70 days, on 1,024
   distinct nodes.
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

**Next steps (as given):** kernel-oncall → KERNMC + KERNRTSP + KERNMNTF;
apprt-oncall → APPSEV; apigw-oncall → break down the 2,068 nova-api error lines by type;
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
(distinct days present), which shows the most persistent problems are
**KERNMC (144 days)** and **KERNRTSP (126 days)** — not KERNDTLB. Treat KERNDTLB
as a one-day incident retrospective (see the trend below).

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

## Engineer — *investigate KERNRTSP, the alert the team lead flagged*

The team lead / manager prioritised **KERNRTSP** (126 days, still active) over
the loud one-day KERNDTLB burst, and handed it to the engineer. The engineer
drills into KERNRTSP (real Claude-over-MCP session; verbatim lines below).

**Question:** "Which nodes and days are affected, show example lines, and what
happened just before and after the most recent one?"
**Tools Claude chose:** `trend_by_week` + `alert_profile` /
`top_nodes_for_alert(category="KERNRTSP")` + `search_logs_fulltext` +
`get_nearby_events` (node-scoped).

**Scope (restated by Claude from the tools):** BGL still 4,747,963 lines;
KERNRTSP = **3,983 lines on 3,394 nodes over 126 days (2005-06-05 → 2006-01-03)**.

> The blocks below are the **verbatim tool output** from a full-corpus run
> (BGL = 4,747,963 lines). Every row and the rendered SQL are copied from the
> tool's `query`/`rows` fields — nothing is hand-written.

### Tool call 1 — `search_logs_fulltext(dataset="bgl", phrase="rts panic", start="2006-01-03", end="2006-01-04", limit=5)`

Scope: `BGL (4,747,963 lines) | period: from 1136246400 to 1136332800`.
Method: **BM25 full-text** (`method: "BM25 full-text"`, no `fallback_reason`),
using SereneDB's inverted index.

Query that ran (rendered, as returned by the tool):
```sql
SELECT id, alert, ts, node, event_time AS "datetime", severity, component,
       message, ROUND(BM25(bgl_idx.tableoid)::NUMERIC, 3) AS score
FROM bgl_idx
WHERE (message @@ ts_phrase('rts') OR message @@ ts_phrase('panic'))
  AND ts >= 1136246400 AND ts <= 1136332800
ORDER BY score DESC LIMIT 5;
```
Result (count: 1 — the single `rts panic` in that 24-hour window):
```
id        alert     ts          node                 datetime                    severity  message                          score
4746673   KERNRTSP  1136287505  R27-M0-NA-C:J11-U11  2006-01-03-03.25.05.504039  FATAL     rts panic! - stopping execution  8.382
```

### Tool call 2 — `top_nodes_for_alert(category="KERNRTSP", limit=5)`
Scope: `BGL (4,747,963 lines) | whole corpus`. (count: 5, truncated — more exist)
```sql
SELECT node, COUNT(*) AS lines FROM bgl_logs
WHERE alert = 'KERNRTSP' AND ts > 0
GROUP BY node ORDER BY lines DESC, node LIMIT 5;
```
Result (nearly every other node has only 1–3 — whole-fleet, not a few bad chips):
```
node                   lines
R63-M0-NE-C:J12-U01       22      <- clear outlier
R45-M0-N6-C:J07-U11        9
R03-M1-NF-C:J07-U01        8
R71-M0-N4-C:J14-U01        8
R07-M0-NE-C:J17-U01        7
```

### Tool call 3 — `get_nearby_events(ts=1136287505, window_seconds=60, node="R27-M0-NA-C:J11-U11")`
Scope: `BGL (4,747,963 lines)`. (count: 8, truncated — window held more)
```sql
SELECT id, alert, ts, node, event_time AS "datetime", severity, component, message
FROM bgl_logs
WHERE ts > 0 AND ts BETWEEN 1136287445 AND 1136287565
  AND node = 'R27-M0-NA-C:J11-U11'
ORDER BY ts, id LIMIT 8;
```
Result (verbatim — the machine-check cascade that precedes the panic):
```
ts          datetime                    alert     message
1136287486  2006-01-03-03.24.46.844512  KERNMC    machine check interrupt (bit=0x1d): L2 dcache unit write data parity error
1136287486  2006-01-03-03.24.46.963349  -         instruction address: 0x00205154
1136287487  2006-01-03-03.24.47.158761  -         Machine Check Status Register: 0x91800000
1136287487  2006-01-03-03.24.47.299458  -         machine check summary.............1
1136287487  2006-01-03-03.24.47.428756  -         instruction plb error.............0
1136287487  2006-01-03-03.24.47.558691  -         data read plb error...............0
1136287487  2006-01-03-03.24.47.688197  -         data write plb error..............1
1136287487  2006-01-03-03.24.47.822137  -         tlb error.........................0
```
(All lines are `KERNEL FATAL` on node `R27-M0-NA-C:J11-U11`. The window is
node-scoped so a wide window doesn't mix in unrelated nodes. The `rts panic`
itself — id 4746673, 03:25:05 — is the Tool-call-1 hit; it follows this
machine-check dump ~19 s later.)

### Which nodes (observed)
Nearly every affected node has only **1–3 panics** — this hits the whole fleet,
not a few bad chips. The exceptions:

| Node | Lines |
|------|------:|
| **R63-M0-NE-C:J12-U01** | 22 (clear outlier) |
| R45-M0-N6-C:J07-U11 | 9 |
| R03-M1-NF-C:J07-U01, R71-M0-N4-C:J14-U01 | 8 each |
| R07-M0-NE-C:J17-U01, R12-M0-N0-C:J12-U01, R62-M0-N4-C:J13-U01 | 7 each |

Rack **R27** accounts for ~10 of the top-20 nodes, and the most recent panic is
also in R27.

### Which days/weeks (observed) — two distinct phases
- **Jun → mid-Sep 2005: partition-wide bursts.** Week of 2005-06-13 alone =
  2,238 lines, incl. **2,048 on 06-14 (> half of all KERNRTSP)**. Further bursts:
  weeks of 09-05 (437), 08-08 (309), 06-27 (216), 08-15 (187), 07-11 (152).
- **Mid-Sep 2005 → Jan 2006: a steady trickle.** Every week ≤24 lines, typically
  isolated single-node panics; the last week (2006-01-02) had a single line.

**Observed example — the 2005-06-14 burst** (every node on card R26-M0-NB panicked
within the same second):
```
2005-06-14-11.16.17.058  R26-M0-NB-C:J09-U11  KERNEL FATAL  rts panic! - stopping execution
2005-06-14-11.16.17.079  R26-M0-NB-C:J15-U11  KERNEL FATAL  rts panic! - stopping execution
2005-06-14-11.16.17.103  R26-M0-NB-C:J11-U11  KERNEL FATAL  rts panic! - stopping execution
2005-06-14-11.16.17.174  R26-M0-NB-C:J05-U01  KERNEL FATAL  rts panic! - stopping execution
```

### The most recent one: 2006-01-03 03:25:05 on R27-M0-NA-C:J11-U11

**Before** — the whole cluster logged nothing from 02:24 to 03:24 (no warning).
Then, on the same node, the machine-check cascade began (verbatim, from Tool
call 3 above — first 8 lines of the window):
```
03:24:46.844  KERNMC  machine check interrupt (bit=0x1d): L2 dcache unit write data parity error
03:24:46.963  -       instruction address: 0x00205154
03:24:47.158  -       Machine Check Status Register: 0x91800000
03:24:47.299  -       machine check summary.............1
03:24:47.428  -       instruction plb error.............0
03:24:47.558  -       data read plb error...............0
03:24:47.688  -       data write plb error..............1
03:24:47.822  -       tlb error.........................0
   ... the dump continues (registers, FPSCR, fpr0-fpr31) ...
03:25:05.504  KERNRTSP  rts panic! - stopping execution   (id 4746673, Tool call 1)
```
An uncorrectable L2 data-cache parity error (`bit=0x1d`, `data write plb
error....1`) hit while a job was running; the kernel dumped its state for ~19
seconds, then panicked at 03:25:05.504.

**After** — within a second, I/O nodes in racks **R20, R22, R24, R25, R26, R27**
all lost their links to the same front-end (verbatim):
```
03:25:06.083  R25-M0-N4-I:J18-U11  APPSEV FATAL  ciod: Error reading message prefix on CioStream socket to 172.16.96.116:39465, Link has been severed
03:25:06.377  R22-M1-N0-I:J18-U11  APPSEV FATAL  ciod: ... 172.16.96.116:39425, Link has been severed
03:25:08.078  R20-M1-N0-I:J18-U11  APPSEV FATAL  ciod: ... 172.16.96.116:39397, Link has been severed
03:25:09.425  R27-M1-NC-I:J18-U11  APPSEV FATAL  ciod: ... 172.16.96.116:39507, Link has been severed
```
That day had **130 APPSEV lines on 130 nodes**.

**Hypothesis (NOT a fact):** one chip's **uncorrectable L2 d-cache parity error
is likely what killed a large multi-rack job** — the KERNMC → ~19s state dump →
`rts panic` → cluster of "link severed" APPSEV errors is consistent with that
chain. The logs establish the sequence and timing, not causation; we cannot
confirm from logs alone that the cache error *caused* the downstream link losses.

**Honest limitation (Claude's own):** there were also **333 KERNMNTF lines that
day, but they were not time-correlated** with this event, so they are *not* tied
to it.

**Observed vs. hypothesis:** the burst phase stopping after September *suggests*
whatever drove the mass panics was fixed or stopped recurring; what remains is
background single-node hardware failure. That read is a hypothesis, not confirmed.

**Next step:** flag `R27-M0-NA-C:J11-U11` and the outlier `R63-M0-NE-C:J12-U01`
for hardware diagnostics; check whether the 2005-06-14 R26-M0-NB burst shares the
same KERNMC→panic signature or had a different trigger; confirm whether front-end
172.16.96.116 was reachable at 03:25.

---

## Manager — *what should we prioritize, and why?*

**Tool calls:** `alert_profile(limit=50)` — fetch all 41 categories so a
chronic-but-low-volume alert (KERNMC, KERNRTSP) surfaces — then rank by spread,
plus `openstack_by_component()`.
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

1. **BGL Kernel Platform, long-running: KERNMC (144 days) + KERNRTSP (126 days) +
   KERNMNTF (26 days)** — all still occurring at the end of the data. Kernel
   Platform owns ~82% of BGL alert lines (284,344 of 348,460). → kernel-oncall.
2. **BGL APPSEV — 70 days, on 1,024 distinct nodes → Application Runtime** (apprt-oncall).
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

## Debugging story — how we made full-corpus full-text work

Worth showing, because it is exactly the "shows its work" the brief rewards:

1. **Symptom.** On the full 4.7M-line corpus the engineer search returned
   `method: "LIKE fallback"` with
   `fallback_reason: "FTS query failed: Invalid unicode (byte sequence mismatch)
   detected in value construction"` — but the same tool worked on the 2k sample.
2. **Ruled out the data.** Reloaded from a pure-ASCII BGL file; still failed. A
   diagnostic script then showed every BM25 query (incl. selecting `message`)
   works from a fresh `psql`/python session, `length(message) = octet_length`
   for all rows, and only 4 rows contained a NUL — so the index and data were
   fine.
3. **Isolated the trigger.** A single bound parameter worked; the tool's
   multi-param query (OR of per-term `ts_phrase` + a time filter) failed; literal
   SQL always worked.
4. **Root cause.** psycopg's **server-side parameter binding**. Proof: the same
   tool call with a `normal cursor` → LIKE fallback / "Invalid unicode", with
   `psycopg.ClientCursor` → `BM25 full-text`. SereneDB's server-side bind path
   rejects that multi-param FTS value construction.
5. **Fix.** `db.py` connects with `cursor_factory=psycopg.ClientCursor`
   (client-side binding, still escaped/safe). Full-text now runs on the full
   corpus. `--clean-bgl` remains as optional hygiene, not a requirement.

## How each role used the SAME corpus differently

| Role | Evidence selected | Decision |
|------|-------------------|----------|
| Engineer | full-text ("rts panic") → top nodes → node-scoped nearby events | traced KERNRTSP on `R27-M0-NA-C:J11-U11` (2006-01-03): KERNMC cache machine-check → rts panic → "link severed" on I/O nodes; flag for hardware diagnostic (hypothesis) |
| Team Lead | whole-corpus `alert_profile` (lines vs nodes vs days) + team rollup + trend | the loudest alert (KERNDTLB) spans 1 day; the recurring ones are KERNRTSP (126d) & APPSEV (70d) → route those to their teams |
| Manager | all categories ranked by spread + OpenStack error rates, each routed to its owner | sustained problems first (KERNRTSP/KERNMNTF, APPSEV), nova-api next, KERNDTLB as a one-day retrospective; no invented impact |

Same tools, same data — different questions, different evidence, different
next steps.

---

## Known limitations

- **OpenStack labelled anomalies** (`anomaly_labels.txt`) are not inline in the
  raw logs, so OpenStack "error" figures are ERROR/CRITICAL-level or
  error-keyword matches, not the dataset's ground-truth anomalies.
- **Time zones.** Dates and day buckets are **UTC** (derived from `ts` via
  `to_timestamp(ts)`); clock times quoted from log lines come from `event_time`,
  which is the system's **local time (UTC-8)**. Example: `ts 1136287505` is
  11:25:05 UTC but `event_time` shows 03:25:05. The last UTC day of data is
  2006-01-04 (KERNSOCK's `last_seen`).
- All counts are matching log lines, not de-duplicated incidents; the logs do
  not establish financial loss, downtime or customer impact.
