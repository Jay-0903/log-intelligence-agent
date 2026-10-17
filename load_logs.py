"""
Load the loghub datasets into SereneDB.

Usage:
    python load_logs.py              # uses the ./loghub folder
    python load_logs.py C:\\path\\to\\loghub

Creates two tables (re-running replaces them):

  bgl_logs  BGL supercomputer logs with full detail (alert labels, nodes,
            unix timestamps). Powers the original engineer/team-lead/manager
            answers.

  logs      ALL 16 loghub systems (Android, Apache, BGL, HDFS, HPC, Hadoop,
            HealthApp, Linux, Mac, OpenSSH, OpenStack, Proxifier, Spark,
            Thunderbird, Windows, Zookeeper) in one common shape, read from
            each folder's *_structured.csv:
              system, line_id, log_time, level, component, source,
              content, event_id, event_template, is_problem
"""
import csv
import glob
import os
import re
import sys

from db import TABLE, get_conn

ALL_TABLE = "logs"
BATCH = 1000

# ── Level normalisation: every system spells levels differently ────────────
LEVEL_MAP = {
    "v": "DEBUG", "d": "DEBUG", "debug": "DEBUG", "trace": "DEBUG",
    "i": "INFO", "info": "INFO", "notice": "INFO",
    "w": "WARN", "warn": "WARN", "warning": "WARN",
    "e": "ERROR", "error": "ERROR", "severe": "ERROR",
    "f": "FATAL", "fatal": "FATAL",
}

# Used for systems with no usable level (Linux, Mac, OpenSSH, HPC, ...)
PROBLEM_WORDS = re.compile(
    r"error|fail|fatal|denied|invalid|exception|refused|panic|"
    r"unreachable|timed? ?out|critical|abort|corrupt|break-in",
    re.IGNORECASE,
)

# Column that best identifies "where" the event came from, per dataset
SOURCE_COLS = ("Node", "User", "Location", "Program", "Process", "Pid", "PID")


def normalise_row(system, r):
    level = LEVEL_MAP.get((r.get("Level") or "").strip().lower())
    label = r.get("Label")
    content = r.get("Content", "")

    if label is not None:                      # BGL, Thunderbird: ground truth
        is_problem = label != "-"
    elif level is not None:                    # systems with real levels
        is_problem = level in ("ERROR", "FATAL")
    else:                                      # fall back to keywords
        is_problem = bool(PROBLEM_WORDS.search(content))

    when = " ".join(r[c] for c in ("Month", "Date", "Day", "Time")
                    if r.get(c)).strip()
    source = next((r[c] for c in SOURCE_COLS if r.get(c)), "")

    # "52225:LearnerHandler" / "0:0:0:0:0:0:0:2181:FastLeaderElection"
    # -> "LearnerHandler" / "FastLeaderElection"
    component = r.get("Component", "") or r.get("Program", "")
    if ":" in component and re.fullmatch(r"[A-Za-z_][\w.$]*", component.rsplit(":", 1)[1]):
        component = component.rsplit(":", 1)[1]

    return (
        system,
        int(r["LineId"]) if r.get("LineId", "").isdigit() else 0,
        when,
        level,
        component,
        source,
        content,
        r.get("EventId", ""),
        r.get("EventTemplate", ""),
        1 if is_problem else 0,
    )


def load_all_systems(cur, loghub_dir):
    cur.execute(f"DROP TABLE IF EXISTS {ALL_TABLE}")
    cur.execute(f"""
        CREATE TABLE {ALL_TABLE} (
            id             INTEGER,
            system         TEXT,
            line_id        INTEGER,
            log_time       TEXT,
            level          TEXT,
            component      TEXT,
            source         TEXT,
            content        TEXT,
            event_id       TEXT,
            event_template TEXT,
            is_problem     INTEGER
        )
    """)
    insert = f"""INSERT INTO {ALL_TABLE}
        (id, system, line_id, log_time, level, component, source,
         content, event_id, event_template, is_problem)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""

    files = sorted(glob.glob(os.path.join(loghub_dir, "*", "*_structured.csv")))
    if not files:
        print(f"⚠️  No *_structured.csv files found under {loghub_dir}")
        return

    next_id = 1
    for path in files:
        system = os.path.basename(os.path.dirname(path))
        rows = []
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                rows.append((next_id, *normalise_row(system, r)))
                next_id += 1
        for i in range(0, len(rows), BATCH):
            cur.executemany(insert, rows[i:i + BATCH])
        problems = sum(r[-1] for r in rows)
        print(f"   {system:<12} {len(rows):>5} lines  ({problems} problems)")

    print(f"✅ Loaded {next_id - 1} lines from {len(files)} systems into '{ALL_TABLE}'")


# ── BGL detail table (raw .log format, 10 fields) ───────────────────────────
def parse_bgl_line(raw):
    parts = raw.strip().split()
    if len(parts) < 10:
        return None
    return (
        parts[0],                                    # alert ("-" = normal)
        int(parts[1]) if parts[1].isdigit() else 0,  # unix timestamp
        parts[2], parts[3], parts[4], parts[5],      # date, node, time, node2
        parts[6], parts[7], parts[8],                # system, component, severity
        " ".join(parts[9:]),                         # message
        raw.strip(),
    )


def load_bgl(cur, log_file):
    cur.execute(f"DROP TABLE IF EXISTS {TABLE}")
    cur.execute(f"""
        CREATE TABLE {TABLE} (
            id INTEGER, alert TEXT, ts BIGINT, log_date TEXT, node TEXT,
            event_time TEXT, node2 TEXT, system TEXT, component TEXT,
            severity TEXT, message TEXT, raw TEXT
        )
    """)
    insert = f"""INSERT INTO {TABLE}
        (id, alert, ts, log_date, node, event_time, node2,
         system, component, severity, message, raw)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""

    batch, total = [], 0
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            row = parse_bgl_line(raw)
            if row is None:
                continue
            total += 1
            batch.append((total, *row))
            if len(batch) >= BATCH:
                cur.executemany(insert, batch)
                batch.clear()
    if batch:
        cur.executemany(insert, batch)
    print(f"✅ Loaded {total} BGL lines into '{TABLE}'")


def main():
    loghub_dir = sys.argv[1] if len(sys.argv) > 1 else "loghub"
    if not os.path.isdir(loghub_dir):
        raise SystemExit(
            f"❌ Folder '{loghub_dir}' not found. Get it with:\n"
            "     git clone --depth 1 https://github.com/logpai/loghub")

    with get_conn().cursor() as cur:
        print("Loading all systems...")
        load_all_systems(cur, loghub_dir)

        bgl_file = os.path.join(loghub_dir, "BGL", "BGL_2k.log")
        if os.path.exists(bgl_file):
            load_bgl(cur, bgl_file)
        else:
            print(f"⚠️  {bgl_file} not found — skipped BGL detail table")


if __name__ == "__main__":
    main()
