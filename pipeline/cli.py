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


def _print_run(res) -> None:
    extra = f", {res.unmapped} UNMAPPED (run `python -m pipeline trims`)" if res.unmapped else ""
    print(f"{res.source}/{res.capability}: {res.artifacts} artifacts ({res.new_artifacts} new), "
          f"{res.records} records, {res.gold_rows} gold rows{extra}")


def cmd_init_db(args) -> int:
    _open().close()
    print("schema ready")
    return 0


def cmd_run(args) -> int:
    from pipeline.providers import PROVIDERS
    from pipeline.runner import run

    conn = _open()
    _print_run(run(conn, PROVIDERS[args.provider], args.capability, args.target))
    return 0


def cmd_import_seed(args) -> int:
    args.provider, args.capability, args.target = "manual_seed", None, "all"
    return cmd_run(args)


def cmd_export_snapshot(args) -> int:
    from pipeline.services.snapshot import export_snapshot

    manifest = export_snapshot(_open(), args.out, generated_at=args.generated_at)
    print(f"snapshot -> {args.out}: {json.dumps(manifest['counts'])}")
    return 0


def cmd_refresh(args) -> int:
    """seed → replay history → (file + live providers) → write history → snapshot.

    A failing provider is reported and skipped; the snapshot is still written from
    whatever succeeded plus the replayed history."""
    from pipeline.history import export_history, import_history
    from pipeline.providers import PROVIDERS
    from pipeline.runner import run
    from pipeline.services.snapshot import export_snapshot

    conn = _open()
    only = set(args.only.split(",")) if args.only else None
    failed = []
    for name, provider in PROVIDERS.items():
        if only and name not in only:
            continue
        if args.offline and provider.live:
            continue
        for cap in provider.capabilities:
            try:
                _print_run(run(conn, provider, cap))
            except Exception as e:  # noqa: BLE001
                failed.append(f"{name}/{cap}: {e}")
                print(f"{name}/{cap}: FAILED ({e})")
        if name == "manual_seed":
            n = import_history(conn)
            print(f"history: {n} observations replayed from data/history")
    n = export_history(conn)
    print(f"history: {n} observations written to data/history")
    manifest = export_snapshot(conn, args.out, generated_at=args.generated_at)
    print(f"snapshot -> {args.out}: {json.dumps(manifest['counts'])}")
    if failed:
        print("providers that failed:", *failed, sep="\n  ")
    return 0


def cmd_export_history(args) -> int:
    from pipeline.history import export_history
    print(f"history: {export_history(_open())} observations written")
    return 0


def cmd_import_history(args) -> int:
    from pipeline.history import import_history
    print(f"history: {import_history(_open())} observations replayed")
    return 0


def cmd_status(args) -> int:
    conn = _open()
    for table in ("artifacts", "source_rows", "cars", "trim_map", "offer_observations", "requirements", "runs"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:19s} {n}")
    for r in conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 5"):
        print(f"run {r['id']} {r['source']}/{r['capability']} {r['status']} {r['finished_at']} "
              f"records={r['records']} unmapped={r['unmapped']} errors={r['errors']}")
    return 0


def cmd_trims(args) -> int:
    from pipeline.services.snapshot import unmapped_trims

    rows = unmapped_trims(_open())
    if not rows:
        print("no unmapped trims")
        return 0
    print("Unmapped trims (add to data/seed/trim_map.json with the right car_id):")
    for r in rows:
        print(f'  {{ "source": "{r["source"]}", "source_key": "{r["source_key"]}", "car_id": "..." }}'
              f'   # {r["label"] or ""}  first seen {r["first_seen_at"][:10]}')
    return 1


def cmd_deal_table(args) -> int:
    from model.deal_math import compute, print_markdown
    from pipeline.services.snapshot import latest_offers, load_cars

    conn = _open()
    print_markdown(compute(latest_offers(conn)), load_cars(conn))
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
    e.add_argument("--generated-at", help="Pin the snapshot timestamp (CI uses the committed one to diff deterministically).")
    e.set_defaults(func=cmd_export_snapshot)

    f = sub.add_parser("refresh", help="Run every provider in order, then export the snapshot.")
    f.add_argument("--out", default=str(DEFAULT_OUT))
    f.add_argument("--generated-at", help="Pin the snapshot timestamp (CI uses the committed one to diff deterministically).")
    f.add_argument("--offline", action="store_true", help="Skip live providers; replay data/history only.")
    f.add_argument("--only", help="Comma-separated provider names to run (manual_seed always recommended first).")
    f.set_defaults(func=cmd_refresh)

    sub.add_parser("export-history", help="Write offer observations to data/history/observations.jsonl.").set_defaults(func=cmd_export_history)
    sub.add_parser("import-history", help="Replay data/history/observations.jsonl into the DB.").set_defaults(func=cmd_import_history)

    sub.add_parser("status", help="Row counts and recent runs.").set_defaults(func=cmd_status)
    sub.add_parser("trims", help="List source trims that are not mapped to a car (exit 1 if any).").set_defaults(func=cmd_trims)
    sub.add_parser("deal-table", help="Print the normalised offer comparison as markdown.").set_defaults(func=cmd_deal_table)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
