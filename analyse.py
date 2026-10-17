import re
from collections import Counter

log_file = r"loghub\BGL\BGL_2k.log"

alerts = []
severities = []
components = []
messages = []

with open(log_file, "r", encoding="utf-8") as f:
    for line in f:
        parts = line.strip().split()
        if len(parts) < 9:
            continue

        alert = parts[0]  # - or alert type
        node = parts[2]  # node ID
        severity = parts[7]  # INFO, FATAL, WARNING etc
        message = " ".join(parts[8:])
        component = parts[5] + " " + parts[6]  # e.g. RAS KERNEL

        alerts.append(alert)
        severities.append(severity)
        components.append(component)
        messages.append(message)

print(f"Total log lines: {len(alerts)}")
print(f"\nAlert types (top 10):")
for k, v in Counter(alerts).most_common(10):
    print(f"  {k}: {v}")

print(f"\nSeverity levels:")
for k, v in Counter(severities).most_common():
    print(f"  {k}: {v}")

print(f"\nTop components:")
for k, v in Counter(components).most_common(10):
    print(f"  {k}: {v}")

print(f"\nSample FATAL messages:")
for i, (a, s, m) in enumerate(zip(alerts, severities, messages)):
    if s == "FATAL":
        print(f"  [{a}] {m[:100]}")
    if i > 500:
        break