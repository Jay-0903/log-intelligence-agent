import re

from tools import (
    search_logs, get_nearby_events, count_by_severity,
    count_alerts, top_failing_nodes, risk_summary,
    problems_by_system, search_all, top_events, system_summary,
)

# ── Multi-system support ─────────────────────────────────────────────────────
# Words in a question that point at one of the 16 loghub systems
SYSTEM_ALIASES = {
    "android": "Android", "apache": "Apache", "hdfs": "HDFS", "hpc": "HPC",
    "hadoop": "Hadoop", "healthapp": "HealthApp", "health app": "HealthApp",
    "linux": "Linux", "mac": "Mac", "macos": "Mac", "openssh": "OpenSSH",
    "ssh": "OpenSSH", "openstack": "OpenStack", "nova": "OpenStack",
    "proxifier": "Proxifier", "proxy": "Proxifier", "spark": "Spark",
    "thunderbird": "Thunderbird", "windows": "Windows",
    "zookeeper": "Zookeeper", "bgl": "BGL",
}
CROSS_SYSTEM = ("all systems", "which system", "every system", "each system",
                "compare", "across", "overall", "systems")
STOPWORDS = {"show", "me", "the", "what", "which", "are", "is", "in", "on",
             "for", "any", "all", "of", "and", "or", "a", "an", "logs", "log",
             "events", "entries", "there", "happened", "find", "list", "give",
             "most", "common", "about", "with", "from", "did", "does", "do",
             "how", "many", "system", "errors?", "should", "we", "top"}


def detect_system(question):
    q = question.lower()
    for alias in sorted(SYSTEM_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", q):
            return SYSTEM_ALIASES[alias]
    return None


def _keywords(question, system):
    aliases = {a for a, s in SYSTEM_ALIASES.items() if s == system}
    words = [w for w in re.findall(r"[a-z0-9_.-]+", question.lower())
             if len(w) > 2 and w not in STOPWORDS and w not in aliases]
    phrases = [" ".join(words[i:i + 2]) for i in range(len(words) - 1)]
    return phrases + words


def answer_multi(role, question):
    """Answer questions about the 16 loghub systems.
    Returns None when the question is about BGL only (handled below)."""
    q = question.lower()
    system = detect_system(question)
    out = []

    # ── Questions comparing systems ──
    if system is None and any(w in q for w in CROSS_SYSTEM):
        rows = problems_by_system()
        out.append("System health across all loghub datasets (worst first):")
        for r in rows:
            bar = "█" * int(r["pct"] // 2)
            out.append(f"  {r['system']:<12} {r['problems']:>5}/{r['total']:<5}"
                       f" {r['pct']:>5}%  {bar}")
        if role == "manager":
            worst = [r["system"] for r in rows[:3]]
            out.append("")
            out.append(f"✅ RECOMMENDATION: focus first on {', '.join(worst)} — "
                       "they have the highest share of problem events.")
        return "\n".join(out)

    if system is None or system == "BGL":
        return None  # fall through to the detailed BGL answers

    # ── Questions about one system ──
    if role == "engineer":
        hits, used = [], None
        for kw in _keywords(question, system):
            hits = search_all(kw, system=system, limit=8)
            if hits:
                used = kw
                break
        if not hits:
            hits = search_all("", system=system, problems_only=True, limit=8)
            used = "problem events"
        out.append(f"{system} — entries matching '{used}' ({len(hits)} shown):")
        for h in hits:
            flag = "⚠️ " if h["is_problem"] else "   "
            out.append(f"  {flag}[{h['level'] or '-'}] {h['log_time']} "
                       f"{h['component']} — {h['content'][:90]}")
        return "\n".join(out)

    s = system_summary(system)
    out.append(f"{system}: {s['problems']} problem events out of {s['total']} "
               f"({s['pct']}%)")

    if role in ("teamlead", "team lead"):
        out.append(f"  Levels: {s['levels']}")
        out.append("\n  Most common event patterns:")
        for e in top_events(system, limit=8):
            out.append(f"    {e['n']:>4}x  {e['event_template'][:85]}")
        if s["problem_components"]:
            out.append("\n  Components producing problems:")
            for c, n in s["problem_components"].items():
                out.append(f"    {c}: {n}")
        return "\n".join(out)

    # manager
    out.append("")
    out.append("🔴 TOP PROBLEM PATTERNS:")
    for e in s["top_problem_events"]:
        out.append(f"  • {e['n']}x  {e['event_template'][:85]}")
    out.append("")
    if s["pct"] > 10:
        out.append(f"⚠️  {s['pct']}% of {system} events are problems — needs attention.")
    elif s["problems"]:
        out.append(f"🟡 {s['pct']}% problem rate — monitor, not urgent.")
    else:
        out.append("🟢 No problem events detected.")
    if s["problem_components"]:
        worst = next(iter(s["problem_components"]))
        out.append(f"📍 Start with component '{worst}' — the main source of problems.")
    return "\n".join(out)


# ── Simple rule-based agent (no API key needed) ──────────────────────────────
# Answers questions for 3 roles: Engineer, Team Lead, Manager

def answer_engineer(question):
    """Engineer wants: what happened, where, show me nearby events."""
    multi = answer_multi("engineer", question)
    if multi:
        return multi

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
    multi = answer_multi("teamlead", question)
    if multi:
        return multi

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
    multi = answer_multi("manager", question)
    if multi:
        return multi

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
        ("ENGINEER",  "Show me failed password attempts in ssh"),
        ("TEAM LEAD", "What are the most common events in Hadoop?"),
        ("MANAGER",   "Which systems should we worry about across all systems?"),
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
    print("         teamlead: what happens most in zookeeper?")
    print("         manager: compare all systems")
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