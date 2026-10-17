"""
Load the BGL log file into SereneDB.

Usage:
    python load_logs.py                      # uses loghub/BGL/BGL_2k.log
    python load_logs.py path/to/BGL.log      # any BGL-format file

Run this once after starting SereneDB (re-running replaces the table).

BGL line format (10 fields):
  Label  Timestamp  Date  Node  Time  NodeRepeat  Type  Component  Level  Content...
  -  1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.675872 R02-M1-N0-C:J12-U11 RAS KERNEL INFO instruction cache parity error corrected
"""
import os
import sys

from db import TABLE, get_conn

DEFAULT_LOG = os.path.join("loghub", "BGL", "BGL_2k.log")
BATCH = 1000


def parse_line(raw):
    parts = raw.strip().split()
    if len(parts) < 10:
        return None
    return (
        parts[0],                                   # alert  ("-" = normal)
        int(parts[1]) if parts[1].isdigit() else 0,  # unix timestamp
        parts[2],                                   # date
        parts[3],                                   # node
        parts[4],                                   # event_time
        parts[5],                                   # node2
        parts[6],                                   # system    (RAS)
        parts[7],                                   # component (KERNEL, APP, ...)
        parts[8],                                   # severity  (INFO, FATAL, ...)
        " ".join(parts[9:]),                        # message
        raw.strip(),                                # raw line
    )


def main():
    log_file = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG
    conn = get_conn()

    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {TABLE}")
        cur.execute(f"""
            CREATE TABLE {TABLE} (
                id         INTEGER,
                alert      TEXT,
                ts         BIGINT,
                log_date   TEXT,
                node       TEXT,
                event_time TEXT,
                node2      TEXT,
                system     TEXT,
                component  TEXT,
                severity   TEXT,
                message    TEXT,
                raw        TEXT
            )
        """)

        insert = f"""INSERT INTO {TABLE}
            (id, alert, ts, log_date, node, event_time, node2,
             system, component, severity, message, raw)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""

        batch, total, skipped = [], 0, 0
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                row = parse_line(raw)
                if row is None:
                    skipped += 1
                    continue
                total += 1
                batch.append((total, *row))
                if len(batch) >= BATCH:
                    cur.executemany(insert, batch)
                    batch.clear()
        if batch:
            cur.executemany(insert, batch)

    print(f"✅ Loaded {total} log lines into SereneDB table '{TABLE}'"
          f" (skipped {skipped} malformed).")


if __name__ == "__main__":
    main()
