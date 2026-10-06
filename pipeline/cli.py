"""`python -m pipeline <command>`"""
from __future__ import annotations

import argparse
import json
import sys

from pipeline.db import ROOT, connect, init_schema

DEFAULT_OUT = ROOT / "web" / "public" / "data"


def _open():
    conn = connect()
    init_schema(conn)
    return conn


def cmd_init_db(args) -> int:
    conn = _open()
    conn.close()
    print("schema ready")
    return 0


def cmd_run(args) -> int:
    from pipeline.providers import PROVIDERS
    from pipeline.runner import run

    conn = _open()
    provider = PROVIDERS[args.provider]
    res = run(conn, provider, args.capability, args.target)
    print(
        f"{res.source}/{res.capability}: {res.artifacts} artifacts ({res.new_artifacts} new), "
        f"{res.records} records, {res.gold_rows} gold rows"
    )
    return 0


def cmd_import_seed(args) -> int:
    args.provider, args.capability, args.target = "manual_seed", None, "all"
    return cmd_run(args)


def cmd_export_snapshot(args) -> int:
    from pipeline.services.snapshot import export_snapshot

    conn = _open()
    manifest = export_snapshot(conn, args.out)
    print(f"snapshot -> {args.out}: {json.dumps(manifest['counts'])}")
    return 0


def cmd_refresh(args) -> int:
    from pipeline.providers import PROVIDERS
    from pipeline.runner import run
    from pipeline.services.snapshot import export_snapshot

    conn = _open()
    for provider in PROVIDERS.values():
        for cap in provider.capabilities:
            res = run(conn, provider, cap)
            print(f"{res.source}/{res.capability}: {res.records} records, {res.gold_rows} gold rows")
    manifest = export_snapshot(conn, args.out)
    print(f"snapshot -> {args.out}: {json.dumps(manifest['counts'])}")
    return 0


def cmd_status(args) -> int:
    conn = _open()
    for table in ("artifacts", "source_rows", "cars", "deals", "requirements", "runs"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:14s} {n}")
    for r in conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 5"):
        print(f"run {r['id']} {r['source']}/{r['capability']} {r['status']} {r['finished_at']}")
    return 0


def cmd_deal_table(args) -> int:
    from model.deal_math import compute, print_markdown
    from pipeline.services.snapshot import load_gold

    conn = _open()
    cars, deals, _ = load_gold(conn)
    print_markdown(compute(deals), cars)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pipeline", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="Create the SQLite schema.").set_defaults(func=cmd_init_db)

    r = sub.add_parser("run", help="Run one provider capability.")
    r.add_argument("provider")
    r.add_argument("--capability")
    r.add_argument("--target", default="all")
    r.set_defaults(func=cmd_run)

    sub.add_parser("import-seed", help="Import data/seed/*.json (the manual_seed provider).").set_defaults(func=cmd_import_seed)

    e = sub.add_parser("export-snapshot", help="Write the static JSON snapshot.")
    e.add_argument("--out", default=str(DEFAULT_OUT))
    e.set_defaults(func=cmd_export_snapshot)

    f = sub.add_parser("refresh", help="Run every provider, then export the snapshot.")
    f.add_argument("--out", default=str(DEFAULT_OUT))
    f.set_defaults(func=cmd_refresh)

    sub.add_parser("status", help="Row counts and recent runs.").set_defaults(func=cmd_status)
    sub.add_parser("deal-table", help="Print the normalised deal comparison as markdown.").set_defaults(func=cmd_deal_table)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
