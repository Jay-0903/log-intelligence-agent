# Q&A question bank (with the output that motivates each)

Questions to ask SereneDB engineers / organisers / data experts at the Q&A.
Each is anchored to a real result from our run, so it reads as "here's what we
found, here's the informed question" — not a generic query.

Numbers referenced (full corpus, verified):
- KERNDTLB: 152,734 lines, **99.6% on one day (2005-06-12)** — a burst.
- Recurring (by days-present): KERNRTSP 126 days, APPSEV 70 days.
- Kernel Platform owns ~82% of BGL alert lines (284,344 of 348,460).
- OpenStack: nova-api 2,068 problem lines (2.01%), 91% of all OpenStack problems.
- Engineer traced KERNRTSP on R27-M0-NA-C:J11-U11 (2006-01-03): KERNMC cache
  machine-check -> rts panic -> "link severed" on I/O nodes (racks R20-R27).
- Index build: 2.4s over 4.7M rows; remote: 1B rows aggregated in ~12–16s.

---

## For SereneDB engineers (deepest value)

1. **Any-term vs. phrase ranking.** We OR per-term `ts_phrase` and rank by
   `BM25(idx.tableoid)`. The docs also list bare-string `@@ 'a b c'`,
   `has_any_tokens`/`ts_any`, and `::min_match(K)`.
   *Ask:* for short log messages, which gives the most useful BM25 ranking —
   per-term OR, bare-string match, or `::min_match`? Any scorer among the 9 you'd
   recommend over default BM25 for log text?
   *(Output: engineer full-text search returned the right node immediately, so
   this is about optimality, not correctness.)*

2. **The 2.4s index build.** Building the inverted index on `message` across
   4.7M BGL rows took **2.4s**, and docs say `VACUUM (REFRESH_TABLE)` publishes
   writes immediately.
   *Ask:* what makes the build that fast — is it indexing lazily on first query,
   or is 2.4s a genuine full build? Any difference in query latency between a
   freshly-refreshed index and one that's been warm a while?

3. **Remote index memory.** Aggregating 1B rows of remote Parquet was fine
   (~12–16s), but building a BM25 index on `Body` across 1B rows hit
   `OutOfMemory` at 6 GiB.
   *Ask:* what's the practical rule of thumb for index memory vs. row count /
   text size? Does `SET preserve_insertion_order=false` or a lower `threads`
   materially cut peak memory, or do we just need a bigger `memory_limit`?

4. **External-view index freshness.** We `CREATE INDEX` on a view over
   `read_parquet(S3)` and refresh with `REINDEX INDEX`.
   *Ask:* for append-only remote data, is there an incremental reindex, or is it
   always a full snapshot rebuild? What governs `reindex_interval` cost?

5. **Row identity without a PK.** Docs say inverted-index row identity is derived
   automatically.
   *Ask:* how stable is that identity across refreshes / reloads — safe to join
   `nearby_events` on it, or should we always carry our own `id`?

## For organisers / judges (scope & intent)

6. *Ask:* for the worked investigation, is one dataset's deep dive + whole-corpus
   counts on both acceptable, or do you want a single incident spanning both BGL
   and OpenStack? (We did BGL deep-dive + both-corpus counts.)

7. *Ask:* is a rule-based reproducible fallback (`agent.py`) a problem if the
   primary demo is Claude-over-MCP selecting tools live? We built both.

8. *Ask:* for "measured frequency," do you prefer raw line counts, or our
   spread metric (lines × distinct nodes × distinct days)? We rank by spread so a
   one-day burst (KERNDTLB) doesn't outrank a chronic one (KERNRTSP).

## For data / log-analysis experts (sharpen the insight)

9. *Ask:* the KERNDTLB burst is 99.6% on 2005-06-12 across 541 nodes — does that
   pattern (many nodes, one day, all corrected) read as a facility event (power/
   cooling/clock) rather than per-node hardware? How would you confirm from logs
   alone?

10. *Ask:* our engineer hypothesis for the 2006-01-03 KERNRTSP event is a
    hardware cache fault, from the KERNMC (L2 d-cache machine check) → rts panic →
    "link severed" chain in ~20s on one node. Is that sequence strong enough to
    call hardware, or could the panic and the cache MC share an upstream cause?

11. *Ask:* OpenStack `error_match` is level/keyword, not the labelled anomalies.
    If we wanted true anomaly rates, what's the cleanest way to join
    `anomaly_labels.txt` back onto the raw lines we loaded?

## The one that shows the most depth

12. Lead with: *"We found the loudest alert is misleading — 99.6% of KERNDTLB is
    one day, so we rank by spread, not count. Does that match how you'd triage,
    and is there a SereneDB-native way to express 'distinct days a term appears'
    more cheaply than our COUNT(DISTINCT date_trunc(...))?"*
    This shows the insight **and** asks a real engine question in one breath.

---

### How to use these
- Pick 2–3 max for a short Q&A; lead with #12 or #1.
- Always state the output first ("we saw X"), then the question.
- If an engineer gives a better operator/scorer, note it — our FTS is isolated in
  `fts.py`, so it's a one-line change to adopt.
