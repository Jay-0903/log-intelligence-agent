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


print(f"Connected to SereneDB — {_total()} log entries in '{TABLE}'.")


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


# ── Quick test ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
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
