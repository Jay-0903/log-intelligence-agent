"""
SereneDB connection helper.

SereneDB speaks the PostgreSQL wire protocol (port 7890 by default), so we
talk to it with the standard `psycopg` driver.

Config via environment variables (all optional):
  SERENEDB_HOST      default: localhost
  SERENEDB_PORT      default: 7890
  SERENEDB_USER      default: (driver default / PGUSER)
  SERENEDB_PASSWORD  default: (none)
  SERENEDB_DB        default: (driver default / PGDATABASE)
"""
import os

import psycopg
from psycopg.rows import dict_row

TABLE = "bgl_logs"

_conn = None


def get_conn():
    """Return a single shared autocommit connection to SereneDB."""
    global _conn
    if _conn is not None and not _conn.closed:
        return _conn

    params = {
        "host": os.getenv("SERENEDB_HOST", "localhost"),
        "port": int(os.getenv("SERENEDB_PORT", "7890")),
        "autocommit": True,
        "row_factory": dict_row,
        "connect_timeout": 5,
    }
    for key, env in (("user", "SERENEDB_USER"),
                     ("password", "SERENEDB_PASSWORD"),
                     ("dbname", "SERENEDB_DB")):
        if os.getenv(env):
            params[key] = os.getenv(env)

    try:
        _conn = psycopg.connect(**params)
    except psycopg.OperationalError as e:
        raise SystemExit(
            f"\n❌ Could not connect to SereneDB at {params['host']}:{params['port']}.\n"
            "   Is the container running?\n"
            "     docker run -d --name serenedb -p 7890:7890 serenedb/serenedb\n"
            f"   Original error: {e}\n"
        )
    return _conn


def query(sql, params=None):
    """Run a SELECT and return a list of dicts."""
    with get_conn().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()
