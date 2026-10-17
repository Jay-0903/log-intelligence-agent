"""
Load the base corpus (BGL + OpenStack) into SereneDB, build full-text
inverted indexes, and create the supplied team-ownership table.

USAGE
-----
    # Full corpus (what the brief scores on). Point at the folders holding
    # the raw downloads:
    python load_logs.py --bgl path/to/BGL.log --openstack path/to/openstack/logs

    # Quick demo from the 2k samples shipped in the loghub repo:
    python load_logs.py --sample --loghub ./loghub

    # Optional extra: also load every loghub sample system into `logs`
    python load_logs.py --sample --loghub ./loghub --all-systems

NOTES
-----
* BGL raw line (space-separated): alert ts date node time node2 system
  component severity message...   ('-' in column 0 means a normal line.)
* OpenStack raw line (loghub): the service comes from the file name
  (nova-api / nova-compute / nova-scheduler). Each line is:
      <date> <time> <pid> <LEVEL> <logger> [req-<request_id> <tenant> <user>] <message> ... time: <latency>
* After loading, we create inverted indexes and VACUUM (REFRESH_TABLE) so
  BM25 full-text search works (see fts.py).
"""
import argparse
import csv
import glob
import os
import re
import sys
from datetime import datetime, timezone

from db import TABLE, execute, get_conn, scalar
import fts
import schema

BATCH = 2000
OPENSTACK_TABLE = "openstack_logs"
ALL_TABLE = "logs"


# ===========================================================================
#  BGL
# ===========================================================================
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
    print(f"[ok] Loaded {total:,} BGL lines into '{TABLE}'")
    return total


# ===========================================================================
#  OpenStack
# ===========================================================================
# <date> <time> <pid> <LEVEL> <logger> [<brackets>] <message>
OS_LINE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2}\.\d+)\s+"
    r"(?P<pid>\d+)\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"(?P<logger>\S+)\s*"
    r"(?P<rest>.*)$"
)
OS_REQ = re.compile(r"\[req-(?P<req>[0-9a-f\-]+)\s+(?P<tenant>\S+)\s+(?P<user>\S+)")
OS_LATENCY = re.compile(r"time:\s*([0-9]+\.[0-9]+)")

OS_PROBLEM = re.compile(r"error|fail|exception|trace|refused|timed? ?out|"
                        r"unable|denied|critical", re.IGNORECASE)


def service_from_filename(path):
    name = os.path.basename(path).lower()
    for svc in ("nova-api", "nova-compute", "nova-scheduler",
                "nova-conductor", "nova-scheduler"):
        if svc in name:
            return svc
    # loghub names like "nova-api.log.1.2017-..." or "OpenStack_2k.log"
    m = re.search(r"(nova-[a-z]+)", name)
    return m.group(1) if m else "openstack"


def parse_openstack_line(service, raw):
    m = OS_LINE.match(raw.strip())
    if not m:
        return None
    g = m.groupdict()
    rest = g["rest"]
    req = tenant = None
    rm = OS_REQ.search(rest)
    if rm:
        req = rm.group("req")
        tenant = rm.group("tenant") if rm.group("tenant") != "-" else None
    lat = OS_LATENCY.search(rest)
    latency_ms = round(float(lat.group(1)) * 1000, 1) if lat else None

    level = g["level"].upper()
    # Component: prefer the nova service from the filename; keep logger too.
    component = service
    ts = _os_epoch(g["date"], g["time"])
    msg = rest
    is_problem = 1 if (level in ("ERROR", "CRITICAL") or OS_PROBLEM.search(rest)) else 0
    return (
        f"{g['date']} {g['time']}",   # log_time
        ts,                            # ts (epoch seconds, best effort)
        int(g["pid"]),                 # pid
        level,                         # level
        component,                     # component (nova service)
        req,                           # request_id
        tenant,                        # tenant_id
        latency_ms,                    # latency_ms
        is_problem,
        msg,                           # message
        raw.strip(),                   # raw
    )


def _os_epoch(date, time):
    try:
        dt = datetime.strptime(f"{date} {time[:8]}", "%Y-%m-%d %H:%M:%S")
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        return 0


def load_openstack(cur, log_paths):
    cur.execute(f"DROP TABLE IF EXISTS {OPENSTACK_TABLE}")
    cur.execute(f"""
        CREATE TABLE {OPENSTACK_TABLE} (
            id INTEGER, log_time TEXT, ts BIGINT, pid INTEGER, level TEXT,
            component TEXT, request_id TEXT, tenant_id TEXT,
            latency_ms DOUBLE PRECISION, is_problem INTEGER, message TEXT, raw TEXT
        )
    """)
    insert = f"""INSERT INTO {OPENSTACK_TABLE}
        (id, log_time, ts, pid, level, component, request_id, tenant_id,
         latency_ms, is_problem, message, raw)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""

    batch, total = [], 0
    for path in log_paths:
        service = service_from_filename(path)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                row = parse_openstack_line(service, raw)
                if row is None:
                    continue
                total += 1
                batch.append((total, *row))
                if len(batch) >= BATCH:
                    cur.executemany(insert, batch)
                    batch.clear()
    if batch:
        cur.executemany(insert, batch)
    print(f"[ok] Loaded {total:,} OpenStack lines into '{OPENSTACK_TABLE}'")
    return total


def discover_openstack(path):
    """Return a list of OpenStack .log files given a file or directory."""
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        files = []
        for pat in ("*.log", "*.log.*", "nova-*", "OpenStack*.log"):
            files += glob.glob(os.path.join(path, "**", pat), recursive=True)
        return sorted(set(f for f in files if os.path.isfile(f)))
    return []


# ===========================================================================
#  OPTIONAL: all loghub sample systems (unchanged behaviour, kept as extra)
# ===========================================================================
LEVEL_MAP = {
    "v": "DEBUG", "d": "DEBUG", "debug": "DEBUG", "trace": "DEBUG",
    "i": "INFO", "info": "INFO", "notice": "INFO",
    "w": "WARN", "warn": "WARN", "warning": "WARN",
    "e": "ERROR", "error": "ERROR", "severe": "ERROR",
    "f": "FATAL", "fatal": "FATAL",
}
PROBLEM_WORDS = re.compile(
    r"error|fail|fatal|denied|invalid|exception|refused|panic|"
    r"unreachable|timed? ?out|critical|abort|corrupt|break-in", re.IGNORECASE)
SOURCE_COLS = ("Node", "User", "Location", "Program", "Process", "Pid", "PID")


def normalise_row(system, r):
    level = LEVEL_MAP.get((r.get("Level") or "").strip().lower())
    label = r.get("Label")
    content = r.get("Content", "")
    if label is not None:
        is_problem = label != "-"
    elif level is not None:
        is_problem = level in ("ERROR", "FATAL")
    else:
        is_problem = bool(PROBLEM_WORDS.search(content))
    when = " ".join(r[c] for c in ("Month", "Date", "Day", "Time") if r.get(c)).strip()
    source = next((r[c] for c in SOURCE_COLS if r.get(c)), "")
    component = r.get("Component", "") or r.get("Program", "")
    if ":" in component and re.fullmatch(r"[A-Za-z_][\w.$]*", component.rsplit(":", 1)[1]):
        component = component.rsplit(":", 1)[1]
    return (system, int(r["LineId"]) if r.get("LineId", "").isdigit() else 0,
            when, level, component, source, content, r.get("EventId", ""),
            r.get("EventTemplate", ""), 1 if is_problem else 0)


def load_all_systems(cur, loghub_dir):
    cur.execute(f"DROP TABLE IF EXISTS {ALL_TABLE}")
    cur.execute(f"""
        CREATE TABLE {ALL_TABLE} (
            id INTEGER, system TEXT, line_id INTEGER, log_time TEXT,
            level TEXT, component TEXT, source TEXT, content TEXT,
            event_id TEXT, event_template TEXT, is_problem INTEGER
        )
    """)
    insert = f"""INSERT INTO {ALL_TABLE}
        (id, system, line_id, log_time, level, component, source,
         content, event_id, event_template, is_problem)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    files = sorted(glob.glob(os.path.join(loghub_dir, "*", "*_structured.csv")))
    if not files:
        print(f"[warn] No *_structured.csv under {loghub_dir}; skipped all-systems")
        return 0
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
        print(f"   {system:<12} {len(rows):>6} lines")
    print(f"[ok] Loaded {next_id - 1:,} lines into '{ALL_TABLE}' (optional)")
    return next_id - 1


# ===========================================================================
#  Indexing (full-text)
# ===========================================================================
def build_indexes(loaded_bgl, loaded_os):
    print("\nBuilding full-text indexes (BM25)...")
    fts.ensure_dictionary()
    if loaded_bgl:
        fts.create_inverted_index("bgl_idx", TABLE, "id", ["message"])
        fts.refresh(TABLE)
        ok = fts.fts_available("bgl_idx")
        print(f"   bgl_idx on {TABLE}.message        {'[searchable]' if ok else '[NOT searchable]'}")
    if loaded_os:
        fts.create_inverted_index("openstack_idx", OPENSTACK_TABLE, "id", ["message"])
        fts.refresh(OPENSTACK_TABLE)
        ok = fts.fts_available("openstack_idx")
        print(f"   openstack_idx on {OPENSTACK_TABLE}.message  {'[searchable]' if ok else '[NOT searchable]'}")


# ===========================================================================
#  main
# ===========================================================================
def main():
    ap = argparse.ArgumentParser(description="Load BGL + OpenStack into SereneDB")
    ap.add_argument("--bgl", help="Path to BGL .log file (full corpus)")
    ap.add_argument("--openstack", help="Path to OpenStack .log file or folder")
    ap.add_argument("--loghub", default="loghub",
                    help="loghub repo folder (for --sample / --all-systems)")
    ap.add_argument("--sample", action="store_true",
                    help="Use the 2k samples from the loghub repo")
    ap.add_argument("--all-systems", action="store_true",
                    help="Also load every loghub sample system into `logs` (optional)")
    args = ap.parse_args()

    bgl_path = args.bgl
    os_paths = []

    if args.sample:
        bgl_path = bgl_path or os.path.join(args.loghub, "BGL", "BGL_2k.log")
        os_sample = os.path.join(args.loghub, "OpenStack", "OpenStack_2k.log")
        os_paths = [os_sample] if os.path.exists(os_sample) else []
    else:
        if args.openstack:
            os_paths = discover_openstack(args.openstack)

    if not bgl_path and not os_paths:
        raise SystemExit(
            "Nothing to load. Provide --bgl / --openstack for the full corpus, "
            "or --sample --loghub ./loghub for the 2k demo.")

    loaded_bgl = loaded_os = 0
    with get_conn().cursor() as cur:
        print("Creating team-ownership table (component_owners)...")
        schema.create_owners_table(execute)
        print(f"   {len(schema.COMPONENT_OWNERS)} component->team mappings\n")

        if bgl_path and os.path.exists(bgl_path):
            print(f"Loading BGL from {bgl_path} ...")
            loaded_bgl = load_bgl(cur, bgl_path)
        elif bgl_path:
            print(f"[warn] BGL file not found: {bgl_path}")

        if os_paths:
            print(f"Loading OpenStack from {len(os_paths)} file(s) ...")
            loaded_os = load_openstack(cur, os_paths)
        elif not args.sample:
            print("[warn] No OpenStack files found")

        if args.all_systems:
            print("\nLoading optional all-systems table...")
            load_all_systems(cur, args.loghub)

    build_indexes(loaded_bgl, loaded_os)

    print("\n=== Load summary ===")
    print(f"  BGL ({TABLE}):            {loaded_bgl:,} lines")
    print(f"  OpenStack ({OPENSTACK_TABLE}): {loaded_os:,} lines")
    print(f"  Ownership rows:           {len(schema.COMPONENT_OWNERS)}")
    print("\nDone. Run:  python tools.py   (self-test)   or   python mcp_server.py")


if __name__ == "__main__":
    main()
