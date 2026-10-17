"""
Log tools backed by SereneDB.

Same function names and return shapes as the original file-based version,
so agent.py works unchanged. Load the data first with:  python load_logs.py
"""
from db import TABLE, query

# Columns returned for every log entry, aliased to the keys agent.py expects
LOG_COLS = """alert, ts AS "timestamp", log_date AS "date", node,
              event_time AS "datetime", node2, system, component,
              severity, message, raw"""


def _total():
    return query(f"SELECT COUNT(*) AS n FROM {TABLE}")[0]["n"]


print(f"Connected to SereneDB — {_total()} BGL entries in '{TABLE}', "
      f"{query('SELECT COUNT(*) AS n FROM logs')[0]['n']} entries across all systems in 'logs'.")


# ── TOOL 1: Engineer — search logs by keyword ───────────────────────────────
def search_logs(keyword, limit=20):
    """Find log lines whose message, node or alert contains a keyword."""
    pattern = f"%{keyword.lower()}%"
    return query(
        f"""SELECT {LOG_COLS} FROM {TABLE}
            WHERE LOWER(message) LIKE %s
               OR LOWER(node)    LIKE %s
               OR LOWER(alert)   LIKE %s
            ORDER BY id
            LIMIT %s""",
        (pattern, pattern, pattern, limit),
    )


# ── TOOL 2: Engineer — get nearby events around a timestamp ─────────────────
def get_nearby_events(timestamp, window_seconds=300, limit=20):
    """Get log events within ±window_seconds of a given Unix timestamp."""
    return query(
        f"""SELECT {LOG_COLS} FROM {TABLE}
            WHERE ts > 0 AND ts BETWEEN %s AND %s
            ORDER BY ts, id
            LIMIT %s""",
        (timestamp - window_seconds, timestamp + window_seconds, limit),
    )


# ── TOOL 3: Team Lead — count by severity ───────────────────────────────────
def count_by_severity():
    """Count log entries grouped by severity level."""
    rows = query(f"""SELECT severity, COUNT(*) AS n FROM {TABLE}
                     GROUP BY severity ORDER BY n DESC""")
    return {r["severity"]: r["n"] for r in rows}


# ── TOOL 4: Team Lead — count alerts by type ────────────────────────────────
def count_alerts():
    """Count alert types ('-' = normal; everything else is an incident)."""
    rows = query(f"""SELECT alert, COUNT(*) AS n FROM {TABLE}
                     GROUP BY alert ORDER BY n DESC""")
    return {r["alert"]: r["n"] for r in rows}


# ── TOOL 5: Team Lead — top failing nodes ───────────────────────────────────
def top_failing_nodes(limit=10):
    """Return nodes with the most non-normal alert entries."""
    rows = query(f"""SELECT node, COUNT(*) AS n FROM {TABLE}
                     WHERE alert <> '-'
                     GROUP BY node ORDER BY n DESC, node
                     LIMIT %s""", (limit,))
    return {r["node"]: r["n"] for r in rows}


# ── TOOL 6: Manager — risk summary ──────────────────────────────────────────
def risk_summary():
    """Total events, % anomalies, top risk nodes, recommended actions."""
    total = _total()
    anomaly_count = query(
        f"SELECT COUNT(*) AS n FROM {TABLE} WHERE alert <> '-'")[0]["n"]
    pct = round(anomaly_count / total * 100, 1) if total else 0

    top_nodes = top_failing_nodes(5)
    alert_types = count_alerts()
    alert_types.pop("-", None)

    summary = {
        "total_events": total,
        "anomaly_count": anomaly_count,
        "anomaly_percent": pct,
        "top_alert_types": alert_types,
        "top_risk_nodes": top_nodes,
        "recommended_actions": [],
    }

    if pct > 5:
        summary["recommended_actions"].append(
            f"⚠️  {pct}% of events are anomalies — investigate immediately.")
    if "KERNDTLB" in alert_types:
        summary["recommended_actions"].append(
            "🔴 KERNDTLB alerts detected — kernel TLB errors, possible memory fault.")
    if "KERNTERM" in alert_types:
        summary["recommended_actions"].append(
            "🔴 KERNTERM alerts — kernel terminations, node may need replacement.")
    if top_nodes:
        worst = next(iter(top_nodes))
        summary["recommended_actions"].append(
            f"📍 Node {worst} has the most failures — prioritize inspection.")

    return summary


# ════════════════════════════════════════════════════════════════════════════
#  CROSS-SYSTEM TOOLS — all 16 loghub datasets in the 'logs' table
# ════════════════════════════════════════════════════════════════════════════
ALL_TABLE = "logs"
ALL_COLS = """system, line_id, log_time, level, component, source,
              content, event_id, event_template, is_problem"""


# ── TOOL 7: list systems and their sizes ────────────────────────────────────
def list_systems():
    """Return {system: number_of_lines} for every loaded system."""
    rows = query(f"""SELECT system, COUNT(*) AS n FROM {ALL_TABLE}
                     GROUP BY system ORDER BY system""")
    return {r["system"]: r["n"] for r in rows}


# ── TOOL 8: Team Lead / Manager — health of every system ───────────────────
def problems_by_system():
    """Per system: total lines, problem lines, problem %. Worst first."""
    rows = query(f"""SELECT system,
                            COUNT(*)        AS total,
                            SUM(is_problem) AS problems
                     FROM {ALL_TABLE}
                     GROUP BY system""")
    for r in rows:
        r["problems"] = int(r["problems"] or 0)
        r["pct"] = round(r["problems"] / r["total"] * 100, 1) if r["total"] else 0
    return sorted(rows, key=lambda r: (-r["pct"], r["system"]))


# ── TOOL 9: Engineer — search any system ────────────────────────────────────
def search_all(keyword, system=None, problems_only=False, limit=20):
    """Keyword search across all systems, or within one system."""
    sql = f"""SELECT {ALL_COLS} FROM {ALL_TABLE}
              WHERE (LOWER(content) LIKE %s OR LOWER(component) LIKE %s)"""
    pattern = f"%{keyword.lower()}%"
    params = [pattern, pattern]
    if system:
        sql += " AND system = %s"
        params.append(system)
    if problems_only:
        sql += " AND is_problem = 1"
    sql += " ORDER BY system, line_id LIMIT %s"
    params.append(limit)
    return query(sql, params)


# ── TOOL 10: Team Lead — most frequent event types ──────────────────────────
def top_events(system, problems_only=False, limit=10):
    """Most common event templates (message patterns) in one system."""
    extra = "AND is_problem = 1" if problems_only else ""
    return query(f"""SELECT event_id, event_template, COUNT(*) AS n
                     FROM {ALL_TABLE}
                     WHERE system = %s {extra}
                     GROUP BY event_id, event_template
                     ORDER BY n DESC, event_id
                     LIMIT %s""", (system, limit))


# ── TOOL 11: Any role — one-system overview ─────────────────────────────────
def system_summary(system):
    """Levels, noisiest components and top problem patterns for one system."""
    total = query(f"SELECT COUNT(*) AS n FROM {ALL_TABLE} WHERE system = %s",
                  (system,))[0]["n"]
    problems = query(f"""SELECT COUNT(*) AS n FROM {ALL_TABLE}
                         WHERE system = %s AND is_problem = 1""",
                     (system,))[0]["n"]
    levels = query(f"""SELECT COALESCE(level, 'n/a') AS level, COUNT(*) AS n
                       FROM {ALL_TABLE} WHERE system = %s
                       GROUP BY level ORDER BY n DESC""", (system,))
    components = query(f"""SELECT component, COUNT(*) AS n FROM {ALL_TABLE}
                           WHERE system = %s AND is_problem = 1
                             AND component <> ''
                           GROUP BY component ORDER BY n DESC, component
                           LIMIT 5""", (system,))
    return {
        "system": system,
        "total": total,
        "problems": problems,
        "pct": round(problems / total * 100, 1) if total else 0,
        "levels": {r["level"]: r["n"] for r in levels},
        "problem_components": {r["component"]: r["n"] for r in components},
        "top_problem_events": top_events(system, problems_only=True, limit=5),
    }


# ── Quick test ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n=== TOOL 7: Systems loaded ===")
    print(" ", list_systems())

    print("\n=== TOOL 8: Problems by system ===")
    for r in problems_by_system():
        print(f"  {r['system']:<12} {r['problems']:>5}/{r['total']:<5} {r['pct']:>5}%")

    print("\n=== TOOL 9: Search 'failed password' in OpenSSH ===")
    for r in search_all("failed password", system="OpenSSH", limit=3):
        print(f"  [{r['system']}] {r['content'][:90]}")

    print("\n=== TOOL 11: Hadoop summary ===")
    s = system_summary("Hadoop")
    print(f"  {s['problems']}/{s['total']} problems ({s['pct']}%), levels {s['levels']}")
    for e in s["top_problem_events"][:3]:
        print(f"  {e['n']:>4}x  {e['event_template'][:80]}")

    print("\n=== TOOL 1: Search for 'error' ===")
    for r in search_logs("error", limit=5):
        print(f"  [{r['severity']}] {r['node']} — {r['message'][:80]}")

    print("\n=== TOOL 3: Count by severity ===")
    for k, v in count_by_severity().items():
        print(f"  {k}: {v}")

    print("\n=== TOOL 4: Alert types ===")
    for k, v in count_alerts().items():
        print(f"  {k}: {v}")

    print("\n=== TOOL 5: Top failing nodes ===")
    for k, v in top_failing_nodes().items():
        print(f"  {k}: {v}")

    print("\n=== TOOL 6: Risk summary (Manager view) ===")
    s = risk_summary()
    print(f"  Total: {s['total_events']}")
    print(f"  Anomalies: {s['anomaly_count']} ({s['anomaly_percent']}%)")
    print(f"  Top alert types: {s['top_alert_types']}")
    print(f"  Top risk nodes: {s['top_risk_nodes']}")
    print("\n  Recommended actions:")
    for a in s["recommended_actions"]:
        print(f"    {a}")
