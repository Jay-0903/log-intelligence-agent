# Log Intelligence Agent

Turns log data into role-appropriate answers for an **Engineer**, a **Team Lead**
and a **Manager**, with all search and aggregation done inside **SereneDB** and an
agent that explains the evidence and recommends a next step.

Built for the SchubKI National AI Hackathon 2026 — *"Making Sense of Logs: The
Right Insights for the Right People."*

Base corpus: **BGL** (search + trends) and **OpenStack** (aggregation). The database
does the searching and counting; the agent only ever sees a small, relevant slice
plus pre-computed summaries — so millions of log lines never have to fit in a prompt.

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

---

## Setup (from a clean checkout)

### 1. Start SereneDB (PostgreSQL-compatible, port 7890)

**Trust auth is required**, or clients get "password authentication failed":

```sh
docker run -d --name serenedb -p 7890:7890 \
    -e SERENEDB_HOST_AUTH_METHOD=trust serenedb/serenedb
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
# unzip / untar, then:
python load_logs.py --bgl path/to/BGL.log --openstack path/to/openstack/logfolder
```

The loader creates `bgl_logs`, `openstack_logs` and the supplied
`component_owners` ownership table, then builds BM25 inverted indexes and runs
`VACUUM (REFRESH_TABLE)` so full-text search works.

> Windows / PowerShell: paths use backslashes, e.g.
> `python load_logs.py --bgl C:\data\BGL\BGL.log --openstack C:\data\OpenStack`

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

Then ask Claude, e.g. *"As an engineer, investigate kernel instruction cache
parity errors in BGL and show nearby events."* It will pick `search_logs_fulltext`
then `get_nearby_events`.

---

## The tools

All tools return a JSON envelope: `tool`, `scope`, `filters`, `query` (the SQL that
ran), `rows`, `count`, `truncated`, `limit`.

| Tool | Role | Input | Returns |
|------|------|-------|---------|
| `corpus_scope` | any | – | line counts per dataset (state scope first) |
| `team_ownership` | any | – | the component → team ownership table |
| `search_logs_fulltext` | engineer | `dataset` (`bgl`/`openstack`), `phrase`, `limit` | BM25-ranked matching log lines with `score` |
| `get_nearby_events` | engineer | `ts` (unix), `window_seconds`, `limit` | BGL lines around a moment, in time order |
| `alert_categories` | team lead | `limit` | whole-corpus BGL counts per alert category |
| `count_alerts_by_team` | team lead | `limit` | whole-corpus BGL events grouped by owning team/component |
| `trend_by_day` | team lead / manager | `category`, `limit` | BGL alert volume per calendar day (trend) |
| `openstack_by_component` | team lead / manager | – | whole-corpus OpenStack per-service totals, problem %, avg latency, owning team |
| `latency_stats` | manager / team lead | – | per-service request latency count/avg/min/max |

**Retrieval** = `search_logs_fulltext`, `get_nearby_events`.
**Aggregation over the whole corpus** = `alert_categories`, `count_alerts_by_team`,
`trend_by_day`, `openstack_by_component`, `latency_stats`.
**Full-text search** = `search_logs_fulltext` (BM25).

---

## Worked investigation

*(Run `python agent.py` to reproduce; fill the numbers from your loaded corpus.)*

**Issue:** recurring kernel memory-translation alerts in BGL.

1. **Engineer** asks: *"kernel instruction cache parity error"*.
   - `search_logs_fulltext(dataset="bgl", phrase="kernel instruction cache parity error")`
     → top BM25 hits on component `KERNEL`, severity `FATAL`.
   - `get_nearby_events(ts=<hit ts>, window_seconds=60)` → shows what co-occurred on the same node.
   - **Observed:** the fatal line and its neighbours. **Hypothesis:** symptom localised to `KERNEL` on that node; not a confirmed root cause. **Next step:** widen the window, check the owning team's runbook.

2. **Team lead** asks: *"what alert patterns recur and who owns them?"*.
   - `alert_categories()` → whole-corpus counts per category (e.g. `KERNDTLB` leads).
   - `count_alerts_by_team()` → maps the leading category to the **Kernel Platform** team.
   - `trend_by_day(category="KERNDTLB")` → whether it is rising or steady.
   - **Next step:** route the top category to its owning team, confirm the trend first.

3. **Manager** asks: *"what should we prioritize?"*.
   - `alert_categories()` + `openstack_by_component()` → the few highest-frequency problems with their owning teams.
   - **Output:** a short ranked list by measured frequency, each with an owner and a next action — and an explicit note that these are log-line counts, **not** confirmed incidents or business impact.

Each role selects *different evidence* and ends with a *different action*, not just a
different length.

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

## Configuration

Optional environment variables: `SERENEDB_HOST` (localhost), `SERENEDB_PORT` (7890),
`SERENEDB_USER` (postgres), `SERENEDB_PASSWORD` (none), `SERENEDB_DB`.

## Optional extras (not required for the core score)

- `python load_logs.py --sample --loghub ./loghub --all-systems` also loads every
  loghub sample system into a `logs` table for a multi-system demo.
- Remote Parquet at scale: SereneDB can query S3 Parquet in place with
  `read_parquet('<url>')` (see the OpenTelemetry dataset in the brief) — a natural
  next step for the "Huge Datasets" award.

## Datasets & citation

Loghub (research-use licence): Zhu et al., *Loghub: A Large Collection of System
Log Datasets for AI-driven Log Analytics*, ISSRE 2023. For BGL also Oliner &
Stearley, DSN 2007.
