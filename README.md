# Log Intelligence Agent

Turns log data into role-appropriate answers for an **Engineer**, a **Team Lead**
and a **Manager**, with all search and aggregation done inside **SereneDB** and an
agent that explains the evidence and recommends a next step.

Built for the SchubKI National AI Hackathon 2026 — *"Making Sense of Logs: The
Right Insights for the Right People."*

Base corpus: **BGL** (search + trends) and **OpenStack** (aggregation). The database
does the searching and counting; the agent only ever sees a small, relevant slice
plus pre-computed summaries — so millions of log lines never have to fit in a prompt.

## The agent, and what was supplied vs. built

- **The real agent is Claude over MCP** — it selects and calls the tools, which is
  what the brief asks for. See a recorded Claude session (one question per role,
  showing the tools it chose) in [`docs/INVESTIGATION.md`](docs/INVESTIGATION.md).
- **`agent.py` is a deterministic, no-API-key fallback** that calls the same tools
  in fixed per-role sequences, so the workflow is reproducible for judges without a
  model. It is a demo harness, not "the agent." (Note: for the team-lead/manager
  roles it runs a fixed report regardless of the exact question wording.)
- **Supplied vs. built:** the organiser Q&A confirmed **no** loader, schema,
  ownership table or hosted instance were supplied — the brief's "what you get" was
  aspirational. So this repo **builds its own**: `load_logs.py` (loader),
  `schema.py` (schema + a self-defined `component_owners` ownership table), and
  SereneDB runs locally in Docker. Point it at a provided instance by setting
  `SERENEDB_HOST`/`SERENEDB_PORT` if one is given.

---

## Why this design

- **Parameterized tools, not open-ended SQL.** The agent chooses from a fixed set
  of described tools and passes parameters. SereneDB runs the query.
- **Full-text search uses SereneDB's BM25 inverted index** (`@@` + `ts_phrase`),
  not substring matching. Multi-word queries match **any** term (OR of per-term
  `ts_phrase`) and are ranked by BM25, so an extra word never zeroes out a hit;
  an exact-phrase mode is also available.
- **Every number is checkable.** Each tool returns the SQL that ran, the filters,
  the data scope, the row count and a `truncated` flag.
- **Facts vs. hypotheses are separated**, and the manager view uses *measured
  frequency only* — no invented downtime, cost or customer impact.

> **SQL verified against the official docs.** We connected the SereneDB docs MCP
> server (`serenedb-docs`) and used `search_docs` / `read_section` to confirm the
> full-text operators, BM25 scoring, inverted-index creation + refresh (rows are
> searchable immediately after `VACUUM (REFRESH_TABLE)`; no primary key needed),
> remote `read_parquet` indexing, and `date_trunc` — all four checks passed. See
> [`docs/DOCS_VERIFICATION.md`](docs/DOCS_VERIFICATION.md) for the sources and the
> native any-term refinements noted there.

---

## Setup (from a clean checkout)

### 1. Start SereneDB (PostgreSQL-compatible, port 7890)

SereneDB speaks the PostgreSQL wire protocol and needs **no credentials by
default**. The `-v serenedb-data:...` volume keeps data across restarts; the
`-v "$PWD/data":/data` mount lets the server read local files in place (used by
the fast bulk load — see step 3).

```sh
docker run -d --name serenedb -p 7890:7890 \
    -v serenedb-data:/var/lib/serenedb \
    -v "$PWD/data":/data \
    -e SERENEDB_HOST_AUTH_METHOD=trust \
    serenedb/serenedb
```

> PowerShell: use `-v "${PWD}\data:/data"`. Trust auth is kept explicitly so the
> container never prompts for a password regardless of image defaults.

Sanity-check the connection (any PostgreSQL client works):

```sh
psql -h localhost -p 7890
```

### 2. Install the Python driver + MCP SDK

```sh
pip install -r requirements.txt
```

### 3. Get the data

**Quick demo (2k samples, loads in seconds):**

```sh
git clone --depth 1 https://github.com/logpai/loghub
python load_logs.py --sample --loghub ./loghub
```

**Full corpus (what the brief scores on):**

```sh
# BGL: 4.7M lines
curl -L -o BGL.zip "https://zenodo.org/records/8196385/files/BGL.zip?download=1"
# OpenStack: 207,820 lines
curl -L -o OpenStack.tar.gz "https://zenodo.org/records/8196385/files/OpenStack.tar.gz?download=1"
```

Unzip/untar into the `./data` folder you mounted into the container, then load:

```sh
# Client-side parse (works anywhere; larger batches for the full corpus):
python load_logs.py --bgl ./data/BGL.log --openstack ./data/openstack-logs

# OR fast server-side bulk load via read_csv (needs ./data mounted). The full
# BGL.log has a few invalid UTF-8 bytes that break the index build, so clean it
# once first (writes ./data/BGL_clean.log), then load the cleaned file:
python load_logs.py --clean-bgl ./data/BGL.log
python load_logs.py --server-bgl /data/BGL_clean.log --openstack ./data/openstack-logs
```

> The `--server-bgl` path streams the file inside SereneDB and parses fields with
> SQL `regexp_extract` — fastest for 4.7M lines (~40 s). **Clean the full BGL.log
> first** (`--clean-bgl`): it has invalid UTF-8 bytes that otherwise fail the
> inverted-index build with "Invalid unicode (byte sequence mismatch)" and make
> search fall back to LIKE. (Do *not* use `read_csv(encoding := 'latin-1')` — it
> makes the server-side read pathologically slow.) The 2k sample needs no
> cleaning. If your build rejects the bulk SQL, the client-side `--bgl` path is
> the proven fallback (parses in Python with `errors="replace"`).

The loader creates `bgl_logs`, `openstack_logs` and the `component_owners`
ownership table, then builds BM25 inverted indexes and runs
`VACUUM (REFRESH_TABLE)` so full-text search works. It prints **row counts and
load time** for each step.

> Windows / PowerShell: paths use backslashes, e.g.
> `python load_logs.py --bgl .\data\BGL\BGL.log --openstack .\data\OpenStack`

**About the ownership table:** the brief references a component → team mapping,
but **no table was supplied by the organisers**, so we define our own in
`schema.py` (`component_owners`) — a reasonable fictional platform org tying BGL
components (KERNEL, APP, LINKCARD, ...) and OpenStack nova services to teams.
Edit `schema.py` to change it.

### 4. Run the workflow

```sh
python agent.py                 # scripted demo for all three roles + interactive loop
python agent.py "manager: what should we prioritize?"
python tools.py                 # tool self-test against the loaded DB
```

### 5. (Recommended) Connect an agent via MCP

```sh
python mcp_server.py            # stdio transport
```

Claude Desktop / Claude Code config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "log-intelligence": {
      "command": "python",
      "args": ["C:\\path\\to\\log-intelligence-agent\\mcp_server.py"],
      "env": { "SERENEDB_HOST": "localhost", "SERENEDB_PORT": "7890" }
    }
  }
}
```

> **Microsoft Store Claude Desktop:** if you installed Claude Desktop from the
> Microsoft Store, the config file is at
> `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`.
> Easiest is to edit it via **Settings → Developer → Edit config**. After any
> change, **fully quit Claude (system tray → Quit)** before reopening — a window
> close alone does not reload the config. (Also restart Claude after reloading
> data into SereneDB, so the MCP server reconnects to the fresh tables.)

> **Use the full path to `python` on Windows.** `"command": "python"` often
> fails to resolve from Claude Desktop. Use the absolute interpreter path, e.g.
> `"command": "C:\\Users\\<you>\\AppData\\Local\\Programs\\Python\\Python314\\python.exe"`.
>
> **Microsoft Store Python:** if you installed Python from the Microsoft Store,
> the real executable is under a `WindowsApps\PythonSoftwareFoundation.Python.*`
> package folder, e.g.
> `C:\\Users\\<you>\\AppData\\Local\\Microsoft\\WindowsApps\\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\\python.exe`
> (the `WindowsApps\\python.exe` *alias* usually does **not** work for MCP). Find
> it with `where.exe python` or
> `python -c "import sys; print(sys.executable)"` and paste that exact path as
> `command`. The server appears **Running** in Claude → Settings → Developer when
> correct (see the checklist below).

Then ask Claude, e.g. *"As an engineer, investigate kernel instruction cache
parity errors in BGL and show nearby events."* It will pick `search_logs_fulltext`
then `get_nearby_events`.

**Verify the MCP connection (quick check):**

1. Restart Claude Desktop / Claude Code after editing the config.
2. Confirm the `log-intelligence` server appears and lists **14 tools**
   (`corpus_scope`, `team_ownership`, `search_logs_fulltext`,
   `get_nearby_events`, `request_trace`, `alert_categories`, `alert_profile`,
   `top_nodes_for_alert`, `count_alerts_by_team`, `trend_by_day`,
   `trend_by_week`, `openstack_by_component`, `latency_stats`, plus the optional
   `otel_*` tools).
3. Ask: *"Call corpus_scope"* — you should get BGL/OpenStack line counts back.
4. Then run one question per role (see `docs/DEMO.md`).

> Requires `mcp>=1.2,<2`. The `fastmcp` API used here was removed in mcp 2.x, so
> the pin in `requirements.txt` matters for a clean install.

---

## The tools

All tools return a JSON envelope: `tool`, `scope`, `filters`, `query` (the SQL that
ran), `rows`, `count`, `truncated`, `limit`.

| Tool | Role | Input | Returns |
|------|------|-------|---------|
| `corpus_scope` | any | – | line counts per dataset (state scope first) |
| `team_ownership` | any | – | the component → team ownership table |
| `search_logs_fulltext` | engineer | `dataset`, `phrase`, `limit`, `start`/`end` (time filter) | BM25-ranked matching log lines with `score` |
| `get_nearby_events` | engineer | `ts` (unix), `window_seconds`, `limit`, `node` | BGL lines around a moment, in time order (optional node filter) |
| `request_trace` | engineer | `request_id`, `limit` | all OpenStack lines for one request, in time order (request lifecycle) |
| `alert_categories` | team lead | `limit`, `start`/`end` (period) | BGL counts per alert category (whole corpus by default) |
| `alert_profile` | team lead / manager | `limit`, `start`/`end` | per category: lines, distinct nodes, distinct days, first/last seen (spread, not raw count) |
| `top_nodes_for_alert` | team lead / engineer | `category`, `limit`, `start`/`end` | nodes with the most lines of a category (names for concrete next steps) |
| `count_alerts_by_team` | team lead | `limit`, `start`/`end` (period) | BGL events grouped by owning team/component |
| `trend_by_day` | team lead / manager | `category`, `limit`, `start`/`end` | BGL alert volume per calendar day (trend) |
| `trend_by_week` | team lead / manager | `category`, `limit`, `start`/`end` | BGL alert volume per week (week-over-week) |
| `openstack_by_component` | team lead / manager | `start`/`end` (period) | OpenStack per-service totals, **error-keyword** rate (not labelled anomalies), avg latency, owning team |
| `latency_stats` | manager / team lead | – | per-service latency distribution: count/avg/min/**p50/p95/p99**/max |

**Retrieval** = `search_logs_fulltext`, `get_nearby_events`.
**Aggregation over the whole corpus** = `alert_categories`, `count_alerts_by_team`,
`trend_by_day`, `openstack_by_component`, `latency_stats`.
**Full-text search** = `search_logs_fulltext` (BM25).

---

## Worked investigation

A full end-to-end investigation against the **full corpus** (BGL 4,747,963 lines
+ OpenStack 207,820 lines) — with the questions, tool calls, executed queries,
real results, per-role answers and limitations — is in
**[`docs/INVESTIGATION.md`](docs/INVESTIGATION.md)**.

Headline finding: the dominant BGL alert `KERNDTLB` (152,734 events) is **not** a
chronic problem — `trend_by_day` shows **152,182 of them (99.6%) fell on a single
day, 2005-06-12.** That reframes it from "a recurring defect" to "investigate one
day's incident," which is the kind of insight the aggregation tools exist to
surface. Each role uses the same corpus differently (see the table at the end of
that doc).

Presentation: **[`docs/slides.pdf`](docs/slides.pdf)** (the deck). Demo script:
[`docs/DEMO.md`](docs/DEMO.md). Slide outline / speaker notes:
[`docs/SLIDES.md`](docs/SLIDES.md), [`docs/SLIDE_NOTES.md`](docs/SLIDE_NOTES.md).

---

## What the data does and does not establish

- Counts are **matching log lines**, not de-duplicated incidents. The brief warns
  against treating matches as separate incidents automatically; we report line counts.
- The logs **do not** establish financial loss, downtime or customer impact; the
  manager view deliberately avoids inventing these.
- Full-text relevance is BM25 over message text; a high score means textual match,
  not confirmed causation.
- OpenStack timestamps are parsed to UTC epoch on a best-effort basis; latency is
  taken from the inline `time:` field where present.

---

## Troubleshooting

- **"Catalog write-write conflict" on load.** Another connection is holding the
  catalog (usually the MCP server inside Claude Desktop, or a previous load).
  Close Claude Desktop (tray → Quit) or `docker restart serenedb`, then re-run
  the loader.
- **Search returns a `fallback_reason` "Invalid unicode (byte sequence
  mismatch)".** The full BGL.log has invalid UTF-8 bytes. Clean it once with
  `python load_logs.py --clean-bgl ./data/BGL.log` and load `BGL_clean.log` via
  `--server-bgl`. Do **not** use `read_csv(encoding := 'latin-1')` (pathologically
  slow).
- **Search falls back to LIKE after a reload.** The MCP server caches one DB
  connection. Restart Claude Desktop so it reconnects to the fresh tables; the
  tools re-check the index per call, so a fresh connection reports the true state.
- **`openstack_logs ... (QUERY ERROR) ... column error_match does not exist`.**
  OpenStack was loaded under an older schema. Reload it:
  `python load_logs.py --openstack ./data/openstack-logs`.

## Configuration

Optional environment variables: `SERENEDB_HOST` (localhost), `SERENEDB_PORT` (7890),
`SERENEDB_USER` (postgres), `SERENEDB_PASSWORD` (none), `SERENEDB_DB`.

## Optional extras (not required for the core score)

- `python load_logs.py --sample --loghub ./loghub --all-systems` also loads every
  loghub sample system into a `logs` table for a multi-system demo.
- **Huge datasets (optional award):** query 50B rows of remote OpenTelemetry
  Parquet in place (zero-ETL) with `read_parquet('<url>')` + a BM25 index on
  `Body`. See **[`docs/HUGE_DATASETS.md`](docs/HUGE_DATASETS.md)** and run
  `python load_logs.py --otel-files 1 --otel-index`. Independent of the core
  BGL/OpenStack workflow; does not change the main score.

## Datasets & citation

Loghub (research-use licence): Zhu et al., *Loghub: A Large Collection of System
Log Datasets for AI-driven Log Analytics*, ISSRE 2023. For BGL also Oliner &
Stearley, DSN 2007.
