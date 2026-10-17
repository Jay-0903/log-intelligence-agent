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
    """Create the shared text-search dictionary once (idempotent-ish).

    Returns True on success. Never raises: if the DDL is rejected (e.g. this
    SereneDB build spells it differently), we warn and let callers fall back
    to LIKE search instead of crashing the loader.
    """
    try:
        execute(
            f"CREATE TEXT SEARCH DICTIONARY {DICTIONARY} "
            "AS split_text(case := 'lower') "
            "WITH (frequency, position, offset)"
        )
        return True
    except Exception as e:
        if "exist" in str(e).lower():      # already created on a re-run
            return True
        print(f"[warn] full-text dictionary not created ({e}); "
              "search will fall back to LIKE.")
        return False


def create_inverted_index(index_name, table, key_col, text_cols):
    """Create (or replace) an inverted index over the given text columns.

    text_cols: list of column names to index for full-text search; each is
    registered against the `english` dictionary. Returns True on success;
    warns and returns False instead of raising.
    """
    cols = ", ".join(f"{c} {DICTIONARY}" for c in text_cols)
    try:
        execute(f"DROP INDEX IF EXISTS {index_name}")
        execute(
            f"CREATE INDEX {index_name} ON {table} "
            f"USING inverted({key_col}, {cols})"
        )
        return True
    except Exception as e:
        print(f"[warn] inverted index '{index_name}' on {table} not created "
              f"({e}); search will fall back to LIKE.")
        return False


def refresh(table):
    """Make newly indexed rows searchable. Warns instead of raising."""
    try:
        execute(f"VACUUM (REFRESH_TABLE) {table}")
        return True
    except Exception as e:
        print(f"[warn] VACUUM (REFRESH_TABLE) {table} failed ({e}).")
        return False


def fts_available(index_name):
    """Return True if a BM25 query against the index works."""
    try:
        query(f"SELECT BM25({index_name}.tableoid) AS s "
              f"FROM {index_name} LIMIT 1")
        return True
    except Exception:
        return False


import re as _re


_MAX_TERMS = 12


def _terms(phrase):
    """Split a free-text query into individual search terms (words).

    Capped at _MAX_TERMS to keep the generated OR query bounded.
    """
    words = [w for w in _re.findall(r"[A-Za-z0-9_.\-]+", phrase) if len(w) > 1]
    return words[:_MAX_TERMS]


def search(index_name, text_col, phrase, select_cols, limit=20, mode="any",
           extra_where="", extra_params=None):
    """Run a BM25 full-text search against an inverted index.

    `mode`:
      "any"    -> match ANY of the words (OR of per-term ts_phrase); this is
                  normal keyword search and what the engineer wants. BM25 still
                  ranks rows that match more / rarer terms higher.
      "phrase" -> match the exact phrase (single ts_phrase, strict adjacency).

    `extra_where` / `extra_params`: an optional additional predicate (already
    prefixed with ' AND '), e.g. a time-range filter. The full-text match group
    is parenthesised first so OR/AND precedence stays correct.

    Returns (rows, sql). A `score` column (BM25) is added and rows are ranked
    by it descending.

    Why not always ts_phrase on the whole string? ts_phrase requires the words
    to appear adjacently in order, so "kernel instruction cache parity error"
    matches nothing when the log says "instruction cache parity error ...".
    Per-term OR matching finds the relevant lines and BM25 ranks them.
    """
    cols = ", ".join(select_cols)
    bm25 = f"ROUND(BM25({index_name}.tableoid)::NUMERIC, 3) AS score"
    extra_params = list(extra_params or [])

    if mode == "phrase":
        match_grp = f"{text_col} @@ ts_phrase(%s)"
        match_params = [phrase]
    else:
        terms = _terms(phrase) or [phrase]
        match_grp = " OR ".join(f"{text_col} @@ ts_phrase(%s)" for _ in terms)
        match_params = list(terms)

    # Parenthesise the OR group so an AND time filter binds correctly.
    where = f"({match_grp}){extra_where}"
    params = match_params + extra_params + [limit]

    sql = (f"SELECT {cols}, {bm25} FROM {index_name} "
           f"WHERE {where} ORDER BY score DESC LIMIT %s")
    rows = query(sql, params)

    shown = sql
    for v in params:
        shown = shown.replace("%s", repr(v) if isinstance(v, str) else str(v), 1)
    return rows, shown
