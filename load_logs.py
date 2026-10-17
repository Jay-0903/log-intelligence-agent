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
import time
from datetime import datetime, timezone

from db import TABLE, execute, get_conn, query, scalar
import fts
import schema

BATCH = 2000
BULK_BATCH = 20000          # larger batches for the full corpus
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


def load_bgl_bulk(mount_path):
    """Fast full-corpus BGL load using SereneDB's server-side file reader.

    The organiser Q&A: mount a folder into the container
    (-v "$PWD/data":/data) and read it in place with read_csv('/data/...').
    `mount_path` is the path AS SEEN BY THE SERVER (e.g. '/data/BGL.log').

    BGL raw lines are space-separated with a free-text message tail, so we:
      1. read each line as one column (a delimiter that never appears),
      2. parse the 9 fixed fields + message tail in SQL with regexp_extract.
    Only the parsed table and its index live locally.

    encoding := 'latin-1': the FULL BGL.log contains invalid UTF-8 bytes (the 2k
    sample does not). Without this, the inverted index build later fails with
    "Invalid unicode (byte sequence mismatch)" and search silently falls back to
    LIKE. latin-1 maps every byte 1:1 so no byte sequence is rejected. (SereneDB
    read_csv supports encoding = utf-8 | utf-16 | latin-1.)
    """
    execute(f"DROP TABLE IF EXISTS {TABLE}")
    execute(f"""
        CREATE TABLE {TABLE} AS
        WITH raw AS (
            SELECT line, row_number() OVER () AS id
            FROM read_csv(%s, delim := e'\\x01', header := false,
                          encoding := 'latin-1',
                          columns := {{'line': 'VARCHAR'}})
        )
        SELECT
            id,
            regexp_extract(line, '^(\\S+)', 1)                       AS alert,
            TRY_CAST(regexp_extract(line, '^\\S+\\s+(\\d+)', 1) AS BIGINT) AS ts,
            regexp_extract(line, '^(?:\\S+\\s+){{2}}(\\S+)', 1)        AS log_date,
            regexp_extract(line, '^(?:\\S+\\s+){{3}}(\\S+)', 1)        AS node,
            regexp_extract(line, '^(?:\\S+\\s+){{4}}(\\S+)', 1)        AS event_time,
            regexp_extract(line, '^(?:\\S+\\s+){{5}}(\\S+)', 1)        AS node2,
            regexp_extract(line, '^(?:\\S+\\s+){{6}}(\\S+)', 1)        AS system,
            regexp_extract(line, '^(?:\\S+\\s+){{7}}(\\S+)', 1)        AS component,
            regexp_extract(line, '^(?:\\S+\\s+){{8}}(\\S+)', 1)        AS severity,
            regexp_extract(line, '^(?:\\S+\\s+){{9}}(.*)$', 1)         AS message,
            line                                                     AS raw
        FROM raw
    """, (mount_path,))
    n = int(scalar(f"SELECT COUNT(*) AS n FROM {TABLE}") or 0)
    print(f"[ok] Bulk-loaded {n:,} BGL lines into '{TABLE}' via read_csv({mount_path})")
    return n


# ===========================================================================
#  OpenStack
# ===========================================================================
# loghub OpenStack line (the sample has a leading logfile token):
#   nova-compute.log.1.2017-05-16_13:55:31 2017-05-16 00:00:00.008 25746 INFO
#   nova.virt.libvirt.imagecache [req-...] <message>
# The leading "<svc>.log...." token is optional (raw per-service files omit it).
OS_LINE = re.compile(
    r"^(?:(?P<logfile>\S+\.log\S*)\s+)?"      # optional "nova-xxx.log.N...."
    r"(?P<date>\d{4}-\d{2}-\d{2})\s+"
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
    # Prefer the service named inline in the 2k combined sample.
    if g.get("logfile"):
        lm = re.search(r"(nova-[a-z]+)", g["logfile"].lower())
        if lm:
            service = lm.group(1)
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
    # NOTE: this flags lines whose LEVEL is ERROR/CRITICAL or whose text matches
    # error keywords. It is NOT the dataset's labelled anomaly ground truth
    # (anomaly_labels.txt), which is not inline in the raw logs. Named
    # `error_match` so downstream numbers are honest about what they measure.
    error_match = 1 if (level in ("ERROR", "CRITICAL") or OS_PROBLEM.search(rest)) else 0
    return (
        f"{g['date']} {g['time']}",   # log_time
        ts,                            # ts (epoch seconds, best effort)
        int(g["pid"]),                 # pid
        level,                         # level
        component,                     # component (nova service)
        req,                           # request_id
        tenant,                        # tenant_id
        latency_ms,                    # latency_ms
        error_match,                   # error_match (keyword/level, not labelled)
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
            latency_ms DOUBLE PRECISION, error_match INTEGER, message TEXT, raw TEXT
        )
    """)
    insert = f"""INSERT INTO {OPENSTACK_TABLE}
        (id, log_time, ts, pid, level, component, request_id, tenant_id,
         latency_ms, error_match, message, raw)
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
        ok, err = fts.fts_available("bgl_idx")
        print(f"   bgl_idx on {TABLE}.message        "
              f"{'[searchable]' if ok else '[NOT searchable: ' + str(err) + ']'}")
    if loaded_os:
        fts.create_inverted_index("openstack_idx", OPENSTACK_TABLE, "id", ["message"])
        fts.refresh(OPENSTACK_TABLE)
        ok, err = fts.fts_available("openstack_idx")
        print(f"   openstack_idx on {OPENSTACK_TABLE}.message  "
              f"{'[searchable]' if ok else '[NOT searchable: ' + str(err) + ']'}")


# ===========================================================================
#  main
# ===========================================================================
def main():
    global BATCH
    ap = argparse.ArgumentParser(description="Load BGL + OpenStack into SereneDB")
    ap.add_argument("--bgl", help="Path to BGL .log file (full corpus)")
    ap.add_argument("--openstack", help="Path to OpenStack .log file or folder")
    ap.add_argument("--loghub", default="loghub",
                    help="loghub repo folder (for --sample / --all-systems)")
    ap.add_argument("--sample", action="store_true",
                    help="Use the 2k samples from the loghub repo")
    ap.add_argument("--all-systems", action="store_true",
                    help="Also load every loghub sample system into `logs` (optional)")
    ap.add_argument("--server-bgl",
                    help="Server-side path to BGL.log for the fast bulk load via "
                         "read_csv, e.g. /data/BGL.log (needs the folder mounted "
                         'into the container: -v "$PWD/data":/data). Fastest for '
                         "the full 4.7M-line corpus.")
    ap.add_argument("--otel-files", type=int, metavar="N",
                    help="OPTIONAL huge-datasets award: create a view over the "
                         "first N remote OpenTelemetry Parquet files (1-50; one "
                         "file ~1B rows) and run a timed demo. No download.")
    ap.add_argument("--otel-index", action="store_true",
                    help="With --otel-files: also build a BM25 index on Body and "
                         "run a full-text query (reports query times).")
    args = ap.parse_args()

    # --- OPTIONAL huge-datasets path (independent of BGL/OpenStack core) ---
    if args.otel_files:
        import otel
        otel.demo(n_files=args.otel_files, do_index=args.otel_index)
        return

    bgl_path = args.bgl
    os_paths = []

    if args.sample:
        bgl_path = bgl_path or os.path.join(args.loghub, "BGL", "BGL_2k.log")
        os_sample = os.path.join(args.loghub, "OpenStack", "OpenStack_2k.log")
        os_paths = [os_sample] if os.path.exists(os_sample) else []
    else:
        BATCH = BULK_BATCH   # bigger batches for the full corpus
        if args.openstack:
            os_paths = discover_openstack(args.openstack)

    if not bgl_path and not os_paths and not args.server_bgl:
        raise SystemExit(
            "Nothing to load. Provide --bgl / --openstack (or --server-bgl) for "
            "the full corpus, or --sample --loghub ./loghub for the 2k demo.")

    t0 = time.perf_counter()
    loaded_bgl = loaded_os = 0

    print("Creating team-ownership table (component_owners)...")
    schema.create_owners_table(execute)
    print(f"   {len(schema.COMPONENT_OWNERS)} component->team mappings\n")

    # --- BGL ---
    tb = time.perf_counter()
    if args.server_bgl:
        print(f"Bulk-loading BGL via server read_csv({args.server_bgl}) ...")
        loaded_bgl = load_bgl_bulk(args.server_bgl)
    elif bgl_path and os.path.exists(bgl_path):
        print(f"Loading BGL from {bgl_path} ...")
        with get_conn().cursor() as cur:
            loaded_bgl = load_bgl(cur, bgl_path)
    elif bgl_path:
        print(f"[warn] BGL file not found: {bgl_path}")
    bgl_secs = time.perf_counter() - tb

    # --- OpenStack ---
    to = time.perf_counter()
    if os_paths:
        print(f"Loading OpenStack from {len(os_paths)} file(s) ...")
        with get_conn().cursor() as cur:
            loaded_os = load_openstack(cur, os_paths)
    elif not args.sample:
        print("[warn] No OpenStack files found")
    os_secs = time.perf_counter() - to

    if args.all_systems:
        print("\nLoading optional all-systems table...")
        with get_conn().cursor() as cur:
            load_all_systems(cur, args.loghub)

    ti = time.perf_counter()
    build_indexes(loaded_bgl, loaded_os)
    idx_secs = time.perf_counter() - ti
    total_secs = time.perf_counter() - t0

    print("\n=== Load summary ===")
    print(f"  BGL ({TABLE}):            {loaded_bgl:,} lines   ({bgl_secs:.1f}s)")
    print(f"  OpenStack ({OPENSTACK_TABLE}): {loaded_os:,} lines   ({os_secs:.1f}s)")
    print(f"  Ownership rows:           {len(schema.COMPONENT_OWNERS)}")
    print(f"  Index build:              {idx_secs:.1f}s")
    print(f"  TOTAL load time:          {total_secs:.1f}s")
    print("\nDone. Run:  python tools.py   (self-test)   or   python mcp_server.py")


if __name__ == "__main__":
    main()
