"""
Schema definitions and the team-ownership table for the base corpus.

The brief supplies a team-ownership table that maps components to the teams
that own them, tying BGL and OpenStack into one fictional platform org. We
encode a reasonable mapping here (editable) and expose it as a real SereneDB
table `component_owners` so team-lead / manager answers can JOIN on it.

Tables created by the loader:

  bgl_logs        BGL supercomputer logs, full detail (4.7M lines when the
                  full corpus is loaded; 2k with --sample). Columns:
                    id, alert, ts, log_date, node, event_time, node2,
                    system, component, severity, message, raw

  openstack_logs  OpenStack nova logs (207k lines full; sample otherwise).
                  Columns:
                    id, log_time, ts, pid, level, component, request_id,
                    tenant_id, latency_ms, is_problem, message, raw

  component_owners  component -> team mapping (the supplied ownership table).
                  Columns: dataset, component, team, on_call

  logs            OPTIONAL extra: all loghub sample systems in one shape
                  (loaded only with --all-systems). Not part of the base
                  corpus; kept for the multi-system demo.
"""

# ---------------------------------------------------------------------------
# Team-ownership table (component -> owning team).
# BGL components come from the RAS component field (KERNEL, APP, LINKCARD,
# DISCOVERY, MMCS, HARDWARE, ...). OpenStack components are the nova services.
# ---------------------------------------------------------------------------
COMPONENT_OWNERS = [
    # dataset,     component,       team,                 on_call
    ("BGL",        "KERNEL",        "Kernel Platform",    "kernel-oncall"),
    ("BGL",        "APP",           "Application Runtime","apprt-oncall"),
    ("BGL",        "LINKCARD",      "Interconnect",       "net-oncall"),
    ("BGL",        "DISCOVERY",     "Provisioning",       "provision-oncall"),
    ("BGL",        "MMCS",          "Control System",     "ctrl-oncall"),
    ("BGL",        "HARDWARE",      "Hardware Ops",       "hwops-oncall"),
    ("BGL",        "BGLMASTER",     "Control System",     "ctrl-oncall"),
    ("BGL",        "CMCS",          "Control System",     "ctrl-oncall"),
    ("BGL",        "MONITOR",       "Observability",      "obs-oncall"),

    ("OpenStack",  "nova-api",      "API Gateway",        "apigw-oncall"),
    ("OpenStack",  "nova-compute",  "Compute",            "compute-oncall"),
    ("OpenStack",  "nova-scheduler","Scheduler",          "sched-oncall"),
]

OWNERS_TABLE = "component_owners"


def create_owners_table(execute):
    execute(f"DROP TABLE IF EXISTS {OWNERS_TABLE}")
    execute(f"""
        CREATE TABLE {OWNERS_TABLE} (
            dataset   TEXT,
            component TEXT,
            team      TEXT,
            on_call   TEXT
        )
    """)
    for row in COMPONENT_OWNERS:
        execute(
            f"INSERT INTO {OWNERS_TABLE} (dataset, component, team, on_call) "
            "VALUES (%s, %s, %s, %s)", row,
        )


# Default on-call team for a dataset when a specific component is unmapped.
DEFAULT_TEAM = {
    "BGL": "Kernel Platform",
    "OpenStack": "Compute",
}
