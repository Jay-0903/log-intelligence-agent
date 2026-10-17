from tools import (
    search_logs, get_nearby_events, count_by_severity,
    count_alerts, top_failing_nodes, risk_summary
)

# ── Simple rule-based agent (no API key needed) ──────────────────────────────
# Answers questions for 3 roles: Engineer, Team Lead, Manager

def answer_engineer(question):
    """Engineer wants: what happened, where, show me nearby events."""
    q = question.lower()
    results = []

    if any(word in q for word in ["error", "fail", "fault", "crash", "parity"]):
        keyword = next((w for w in ["error", "fail", "fault", "crash", "parity"] if w in q), "error")
        hits = search_logs(keyword, limit=10)
        if hits:
            results.append(f"Found {len(hits)} log entries matching '{keyword}':\n")
            for h in hits[:5]:
                results.append(f"  [{h['severity']}] {h['datetime']} | Node: {h['node']} | {h['message'][:100]}")
                # Show nearby events for first hit
            results.append(f"\nContext window (±5 min) around first match:")
            nearby = get_nearby_events(hits[0]["timestamp"], window_seconds=300, limit=5)
            for n in nearby:
                marker = ">>>" if n["node"] == hits[0]["node"] else "   "
                results.append(f"  {marker} [{n['alert']}] {n['datetime']} {n['node']} — {n['message'][:80]}")
        else:
            results.append(f"No entries found for '{keyword}'.")

    elif "node" in q or "rack" in q:
        # Extract node ID if mentioned
        words = question.split()
        node_id = next((w for w in words if "R" in w and "-" in w), None)
        if node_id:
            hits = search_logs(node_id, limit=10)
            results.append(f"Events for node {node_id}:")
            for h in hits[:10]:
                results.append(f"  [{h['alert']}] [{h['severity']}] {h['message'][:100]}")
        else:
            top = top_failing_nodes(5)
            results.append("Top failing nodes:")
            for node, count in top.items():
                results.append(f"  {node}: {count} alerts")

    elif "kernel" in q or "tlb" in q or "memory" in q:
        hits = search_logs("KERNDTLB", limit=10) + search_logs("kernel", limit=5)
        results.append(f"Kernel-related events ({len(hits)} found):")
        for h in hits[:8]:
            results.append(f"  [{h['alert']}] {h['node']} — {h['message'][:100]}")

    else:
        # Generic: search by any keyword in question
        for word in question.split():
            if len(word) > 4:
                hits = search_logs(word, limit=5)
                if hits:
                    results.append(f"Events matching '{word}':")
                    for h in hits[:3]:
                        results.append(f"  [{h['severity']}] {h['node']} — {h['message'][:80]}")
                    break
        if not results:
            results.append("Try asking about: errors, a specific node ID, kernel issues, or component failures.")

    return "\n".join(results)


def answer_team_lead(question):
    """Team Lead wants: patterns, counts, trends, recurring issues."""
    q = question.lower()
    results = []

    if "severity" in q or "level" in q or "how many" in q:
        counts = count_by_severity()
        results.append("Event counts by severity level:")
        for sev, count in counts.items():
            bar = "█" * (count // 50)
            results.append(f"  {sev:<12} {count:>5}  {bar}")

    if "alert" in q or "type" in q or "pattern" in q or "recurring" in q:
        counts = count_alerts()
        counts.pop("-", None)
        results.append("\nRecurring alert patterns:")
        for alert, count in counts.items():
            results.append(f"  {alert:<15} {count:>5} occurrences")

    if "node" in q or "component" in q or "which" in q:
        top = top_failing_nodes(10)
        results.append("\nTop failing nodes (most alerts):")
        for node, count in top.items():
            results.append(f"  {node}: {count}")

    if not results:
        # Default: give full pattern overview
        counts = count_by_severity()
        alerts = count_alerts()
        alerts.pop("-", None)
        results.append("System health overview:")
        results.append(f"  Total events: 2000")
        results.append(f"  Severity breakdown: {dict(list(counts.items())[:3])}")
        results.append(f"  Top alert types: {dict(list(alerts.items())[:3])}")
        results.append(f"  Recommendation: Monitor KERNDTLB (60 occurrences) — highest alert count.")

    return "\n".join(results)


def answer_manager(question):
    """Manager wants: risks, priorities, what to do."""
    summary = risk_summary()
    results = []

    results.append("📊 EXECUTIVE RISK SUMMARY")
    results.append(f"  Total log events analyzed: {summary['total_events']:,}")
    results.append(f"  Anomalies detected: {summary['anomaly_count']} ({summary['anomaly_percent']}%)")
    results.append("")
    results.append("🔴 TOP RISKS:")
    alert_types = summary['top_alert_types']
    risk_map = {
        "KERNDTLB": "Kernel TLB errors — memory translation failures, risk of data corruption",
        "KERNSTOR": "Kernel store errors — storage subsystem faults",
        "APPSEV":   "Application severe errors — service disruption possible",
        "KERNMNTF": "Kernel mount failures — filesystem access issues",
        "KERNTERM": "Kernel terminations — nodes crashing, hardware may need replacement",
    }
    for alert, count in list(alert_types.items())[:5]:
        desc = risk_map.get(alert, "System alert")
        results.append(f"  • {alert} ({count}x): {desc}")

    results.append("")
    results.append("📍 NODES REQUIRING IMMEDIATE ATTENTION:")
    for node, count in list(summary['top_risk_nodes'].items())[:3]:
        results.append(f"  • {node} — {count} incidents")

    results.append("")
    results.append("✅ RECOMMENDED ACTIONS:")
    for action in summary['recommended_actions']:
        results.append(f"  {action}")

    return "\n".join(results)


# ── Interactive demo ─────────────────────────────────────────────────────────
def run_demo():
    print("=" * 60)
    print("LOG INTELLIGENCE AGENT — Demo")
    print("=" * 60)

    demo_questions = [
        ("ENGINEER",  "Show me instruction cache parity errors and what happened nearby"),
        ("TEAM LEAD", "What are the recurring alert patterns and severity levels?"),
        ("MANAGER",   "What are the top risks and what should we do?"),
    ]

    for role, question in demo_questions:
        print(f"\n{'─'*60}")
        print(f"ROLE: {role}")
        print(f"QUESTION: {question}")
        print(f"{'─'*60}")

        if role == "ENGINEER":
            answer = answer_engineer(question)
        elif role == "TEAM LEAD":
            answer = answer_team_lead(question)
        else:
            answer = answer_manager(question)

        print(answer)

    print(f"\n{'='*60}")
    print("INTERACTIVE MODE — type your question (or 'quit')")
    print("Start with: engineer / teamlead / manager")
    print("Example: engineer: show errors on node R30")
    print("=" * 60)

    while True:
        user_input = input("\n> ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if ":" in user_input:
            role_part, question = user_input.split(":", 1)
            role_part = role_part.strip().lower()
            question = question.strip()
            if "engineer" in role_part:
                print(answer_engineer(question))
            elif "team" in role_part or "lead" in role_part:
                print(answer_team_lead(question))
            elif "manager" in role_part:
                print(answer_manager(question))
            else:
                print("Unknown role. Use: engineer / teamlead / manager")
        else:
            print("Format: role: your question")
            print("Example: manager: what are the biggest risks?")


if __name__ == "__main__":
    run_demo()