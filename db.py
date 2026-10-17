"""
SereneDB connection helper.

SereneDB speaks the PostgreSQL wire protocol (port 7890 by default), so we
talk to it with the standard `psycopg` driver. Internally SereneDB runs SQL
through DuckDB and uses its own `iresearch` engine for full-text (BM25),
vector and hybrid search.

Config via environment variables (all optional):
  SERENEDB_HOST      default: localhost
  SERENEDB_PORT      default: 7890
  SERENEDB_USER      default: postgres
  SERENEDB_PASSWORD  default: (none)   # container runs with trust auth
  SERENEDB_DB        default: (driver default / PGDATABASE)

The Docker container MUST be started with trust auth, otherwise clients get
"password authentication failed":

  docker run -d --name serenedb -p 7890:7890 \\
      -e SERENEDB_HOST_AUTH_METHOD=trust serenedb/serenedb
"""
import os

import psycopg
from psycopg.rows import dict_row

# Full-detail BGL table (raw .log format)
TABLE = "bgl_logs"

_conn = None


def _params():
    params = {
        "host": os.getenv("SERENEDB_HOST", "localhost"),
        "user": os.getenv("SERENEDB_USER", "postgres"),
        "port": int(os.getenv("SERENEDB_PORT", "7890")),
        "autocommit": True,
        "row_factory": dict_row,
        # Client-side parameter binding (safe/escaped by psycopg). SereneDB's
        # server-side bind path fails on the multi-param FTS query shape (OR of
        # per-term ts_phrase + time filter) with "Invalid unicode (byte sequence
        # mismatch) detected in value construction" — a single bound param works,
        # literal SQL always works, but the multi-param bound query does not.
        # ClientCursor renders params into the SQL text before sending, which
        # makes full-text search work on the full 4.7M-line corpus.
        "cursor_factory": psycopg.ClientCursor,
        "connect_timeout": 10,
    }
    for key, env in (("password", "SERENEDB_PASSWORD"),
                     ("dbname", "SERENEDB_DB")):
        if os.getenv(env):
            params[key] = os.getenv(env)
    return params


def get_conn():
    """Return a single shared autocommit connection to SereneDB."""
    global _conn
    if _conn is not None and not _conn.closed:
        return _conn

    params = _params()
    try:
        _conn = psycopg.connect(**params)
    except psycopg.OperationalError as e:
        raise SystemExit(
            f"\n[X] Could not connect to SereneDB at "
            f"{params['host']}:{params['port']}.\n"
            "    Is the container running with trust auth?\n"
            "      docker run -d --name serenedb -p 7890:7890 \\\n"
            "          -e SERENEDB_HOST_AUTH_METHOD=trust serenedb/serenedb\n"
            f"    Original error: {e}\n"
        )
    return _conn


def query(sql, params=None):
    """Run a SELECT and return a list of dicts."""
    with get_conn().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def execute(sql, params=None):
    """Run a statement that returns no rows (DDL / INSERT / VACUUM)."""
    with get_conn().cursor() as cur:
        cur.execute(sql, params)


def scalar(sql, params=None):
    """Run a SELECT and return the first column of the first row."""
    rows = query(sql, params)
    if not rows:
        return None
    return next(iter(rows[0].values()))
