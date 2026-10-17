import re
from collections import Counter, defaultdict
from datetime import datetime

# ── Load the log file once ──────────────────────────────────────────────────
LOG_FILE = r"loghub\BGL\BGL_2k.log"

logs = []  # list of dicts, one per line

with open(LOG_FILE, "r", encoding="utf-8") as f:
    for raw in f:
        parts = raw.strip().split()
        if len(parts) < 9:
            continue
        logs.append({
            "alert":     parts[0],
            "timestamp": int(parts[1]) if parts[1].isdigit() else 0,
            "date":      parts[2],
            "node":      parts[3],
            "datetime":  parts[4],
            "node2":     parts[5],
            "system":    parts[6],
            "severity":  parts[7],
            "message":   " ".join(parts[8:]),
            "raw":       raw.strip()
        })

print(f"Loaded {len(logs)} log entries.")


# ── TOOL 1: Engineer — search logs by keyword ───────────────────────────────
def search_logs(keyword, limit=20):
    """Find log lines containing a keyword. Returns matching entries."""
    keyword_lower = keyword.lower()
    results = [l for l in logs if keyword_lower in l["message"].lower()
               or keyword_lower in l["node"].lower()]
    return results[:limit]


# ── TOOL 2: Engineer — get nearby events around a timestamp ─────────────────
def get_nearby_events(timestamp, window_seconds=300, limit=20):
    """
    Get log events within ±window_seconds of a given Unix timestamp.
    Useful for understanding context around an error.
    """
    nearby = [l for l in logs
              if abs(l["timestamp"] - timestamp) <= window_seconds
              and l["timestamp"] > 0]
    nearby.sort(key=lambda x: x["timestamp"])
    return nearby[:limit]


# ── TOOL 3: Team Lead — count by severity ───────────────────────────────────
def count_by_severity():
    """Count log entries grouped by severity level."""
    counts = Counter(l["severity"] for l in logs)
    return dict(counts.most_common())


# ── TOOL 4: Team Lead — count alerts by type ────────────────────────────────
def count_alerts():
    """Count alert types (non-normal entries are incidents)."""
    counts = Counter(l["alert"] for l in logs)
    return dict(counts.most_common())


# ── TOOL 5: Team Lead — top failing nodes ───────────────────────────────────
def top_failing_nodes(limit=10):
    """Return nodes with the most non-normal alert entries."""
    failing = [l["node"] for l in logs if l["alert"] != "-"]
    counts = Counter(failing)
    return dict(counts.most_common(limit))


# ── TOOL 6: Manager — risk summary ──────────────────────────────────────────
def risk_summary():
    """
    High-level summary for a manager:
    - Total events, % anomalies, top risk nodes, recommended actions.
    """
    total = len(logs)
    anomalies = [l for l in logs if l["alert"] != "-"]
    pct = round(len(anomalies) / total * 100, 1) if total else 0

    top_nodes = top_failing_nodes(5)
    alert_types = count_alerts()
    alert_types.pop("-", None)  # remove normal entries

    summary = {
        "total_events": total,
        "anomaly_count": len(anomalies),
        "anomaly_percent": pct,
        "top_alert_types": alert_types,
        "top_risk_nodes": top_nodes,
        "recommended_actions": []
    }

    # Simple rule-based recommendations
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
        worst = list(top_nodes.keys())[0]
        summary["recommended_actions"].append(
            f"📍 Node {worst} has the most failures — prioritize inspection.")

    return summary


# ── Quick test — run each tool and print results ─────────────────────────────
if __name__ == "__main__":
    print("\n=== TOOL 1: Search for 'error' ===")
    results = search_logs("error", limit=5)
    for r in results:
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
    summary = risk_summary()
    print(f"  Total: {summary['total_events']}")
    print(f"  Anomalies: {summary['anomaly_count']} ({summary['anomaly_percent']}%)")
    print(f"  Top alert types: {summary['top_alert_types']}")
    print(f"  Top risk nodes: {summary['top_risk_nodes']}")
    print(f"\n  Recommended actions:")
    for action in summary['recommended_actions']:
        print(f"    {action}")