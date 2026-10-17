"""
Full-text search layer for SereneDB (BM25, iresearch engine).

Everything that depends on SereneDB's exact full-text syntax lives here, so
it is trivial to adjust in one place. Based on serenedb.com/docs/quick-start:

    CREATE TEXT SEARCH DICTIONARY english AS split_text(case := 'lower')
        WITH (frequency, position, offset);

    CREATE INDEX movies_idx ON movies
        USING inverted(id, title english, overview english);

    VACUUM (REFRESH_TABLE) movies;        -- makes the index searchable

    SELECT title, ROUND(BM25(movies_idx.tableoid)::NUMERIC, 3) AS score
    FROM movies_idx                       -- query the INDEX, not the table
    WHERE overview @@ ts_phrase('falls in love')
    ORDER BY score DESC;

Key points encoded below:
  * operator is `@@`
  * phrase query function is `ts_phrase('...')`
  * ranking is `BM25(<index>.tableoid)`
  * you SELECT ... FROM <index_name>, not the table name
"""
from db import execute, query

DICTIONARY = "english"


def ensure_dictionary():
    """Create the shared text-search dictionary once (idempotent-ish)."""
    try:
        execute(
            f"CREATE TEXT SEARCH DICTIONARY {DICTIONARY} "
            "AS split_text(case := 'lower') "
            "WITH (frequency, position, offset)"
        )
    except Exception as e:
        # Already exists on a re-run -> fine.
        if "exist" not in str(e).lower():
            raise


def create_inverted_index(index_name, table, key_col, text_cols):
    """Create (or replace) an inverted index over the given text columns.

    text_cols: list of column names to index for full-text search; each is
    registered against the `english` dictionary.
    """
    cols = ", ".join(f"{c} {DICTIONARY}" for c in text_cols)
    execute(f"DROP INDEX IF EXISTS {index_name}")
    execute(
        f"CREATE INDEX {index_name} ON {table} "
        f"USING inverted({key_col}, {cols})"
    )


def refresh(table):
    """Make newly indexed rows searchable."""
    execute(f"VACUUM (REFRESH_TABLE) {table}")


def fts_available(index_name):
    """Return True if a BM25 query against the index works."""
    try:
        query(f"SELECT BM25({index_name}.tableoid) AS s "
              f"FROM {index_name} LIMIT 1")
        return True
    except Exception:
        return False


def search(index_name, text_col, phrase, select_cols, limit=20):
    """Run a BM25 full-text phrase search against an inverted index.

    Returns (rows, sql). `select_cols` is a list of columns to return
    (they must exist on the indexed table/index). Results are ranked by BM25
    score descending; a `score` column is added.
    """
    cols = ", ".join(select_cols)
    sql = (
        f"SELECT {cols}, "
        f"ROUND(BM25({index_name}.tableoid)::NUMERIC, 3) AS score "
        f"FROM {index_name} "
        f"WHERE {text_col} @@ ts_phrase(%s) "
        f"ORDER BY score DESC "
        f"LIMIT %s"
    )
    rows = query(sql, (phrase, limit))
    # Echo the bound SQL for provenance (safe: literals are simple).
    shown = sql.replace("%s", repr(phrase), 1).replace("%s", str(limit), 1)
    return rows, shown
