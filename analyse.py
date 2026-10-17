"""
Quick offline look at a BGL .log file (no database needed).

Useful for the "hours 0-6, inspect the data" step before loading into
SereneDB. Field layout matches load_logs.parse_bgl_line:

  alert ts date node time node2 system component severity message...

Usage:
    python analyse.py                      # defaults to loghub/BGL/BGL_2k.log
    python analyse.py path/to/BGL.log
"""
import os
import sys
from collections import Counter

log_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    "loghub", "BGL", "BGL_2k.log")

if not os.path.exists(log_file):
    raise SystemExit(f"File not found: {log_file}\n"
                     "Pass a path, e.g. python analyse.py C:\\data\\BGL\\BGL.log")

alerts, severities, components, messages = [], [], [], []
with open(log_file, "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        parts = line.strip().split()
        if len(parts) < 10:
            continue
        alerts.append(parts[0])        # alert label ('-' = normal)
        components.append(parts[7])    # component (KERNEL, APP, ...)
        severities.append(parts[8])    # severity (INFO/FATAL/...)
        messages.append(" ".join(parts[9:]))

print(f"Total parsed log lines: {len(alerts):,}")
print(f"Normal (alert '-'):     {alerts.count('-'):,}")
print(f"Labelled alerts:        {len(alerts) - alerts.count('-'):,}")

print("\nAlert categories (top 12):")
for k, v in Counter(a for a in alerts if a != "-").most_common(12):
    print(f"  {k:<12} {v}")

print("\nSeverity levels:")
for k, v in Counter(severities).most_common():
    print(f"  {k:<10} {v}")

print("\nTop components:")
for k, v in Counter(components).most_common(10):
    print(f"  {k:<12} {v}")

print("\nSample FATAL messages:")
shown = 0
for s, m in zip(severities, messages):
    if s == "FATAL":
        print(f"  {m[:100]}")
        shown += 1
        if shown >= 8:
            break
