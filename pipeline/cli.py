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
    extra += f", {res.errors} failed" if res.errors else ""
    extra += f", {res.skipped} not on the site" if getattr(res, "skipped", 0) else ""
    print(f"{res.source}/{res.capability}: {res.artifacts} artifacts ({res.new_artifacts} new), "
          f"{res.records} records, {res.gold_rows} gold rows{extra}")


def _replay(conn) -> None:
    """data/history → DB, in dependency order: catalogue, specs (which make the
    generated cars), then the observations (whose cars must exist)."""
    from pipeline import gold
    from pipeline.history import (import_derivatives, import_history, import_ledger, import_models, import_options, import_resolutions,
                                  import_specs, import_used, import_used_observations)

    print(f"history: {import_models(conn)} catalogue models replayed from data/history")
    print(f"history: {import_specs(conn)} spec rows replayed from data/history")
    print(f"history: {import_derivatives(conn)} derivatives replayed from data/history")
    print(f"history: {import_options(conn)} derivatives' options replayed from data/history")
    print(f"history: {import_history(conn)} observations replayed from data/history")
    print(f"history: {import_resolutions(conn)} broker resolutions replayed from data/history")
    print(f"history: {import_used(conn)} used listings replayed from data/history")
    print(f"history: {import_used_observations(conn)} used asking-price spans replayed from data/history")
    gold.backfill_used_spans(conn)
    print(f"history: {import_ledger(conn)} backfilled pages noted from data/history")


def _write_history(conn) -> None:
    from pipeline import gold
    from pipeline.history import (export_derivatives, export_history, export_ledger, export_models, export_options, export_resolutions,
                                  export_specs, export_used, export_used_observations)

    pruned = gold.prune_auto_cars(conn)
    if pruned:
        print(f"gold: {pruned} generated cars dropped (nothing refers to them)")
    gold.backfill_used_spans(conn)
    conn.commit()
    print(f"history: {export_history(conn)} observations written to data/history")
    print(f"history: {export_specs(conn)} spec rows written to data/history")
    print(f"history: {export_models(conn)} catalogue models written to data/history")
    print(f"history: {export_derivatives(conn)} derivatives written to data/history")
    print(f"history: {export_options(conn)} derivatives' options written to data/history")
    print(f"history: {export_resolutions(conn)} broker resolutions written to data/history")
    print(f"history: {export_used(conn)} used listings written to data/history")
    print(f"history: {export_used_observations(conn)} used asking-price spans written to data/history")
    print(f"history: {export_ledger(conn)} backfilled pages noted in data/history")


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


def cmd_reparse(args) -> int:
    """Parse the stored pages again (no network) and rewrite history + snapshot."""
    from pipeline.providers import PROVIDERS
    from pipeline.runner import reparse
    from pipeline.services.snapshot import export_snapshot

    conn = _open()
    only = set(args.only.split(",")) if args.only else None
    for name, provider in PROVIDERS.items():
        if only and name not in only:
            continue
        for cap in provider.capabilities:
            if cap == "backfill":
                continue
            _print_run(reparse(conn, provider, cap))
    _write_history(conn)
    manifest = export_snapshot(conn, args.out, generated_at=args.generated_at)
    print(f"snapshot -> {args.out}: {json.dumps(manifest['counts'])}")
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
            if cap == "backfill":
                continue  # Wayback backfill is a one-off: `pipeline backfill`
            try:
                _print_run(run(conn, provider, cap))
            except Exception as e:  # noqa: BLE001
                failed.append(f"{name}/{cap}: {e}")
                print(f"{name}/{cap}: FAILED ({e})")
        if name == "manual_seed":
            _replay(conn)
    _write_history(conn)
    manifest = export_snapshot(conn, args.out, generated_at=args.generated_at)
    print(f"snapshot -> {args.out}: {json.dumps(manifest['counts'])}")
    if failed:
        print("providers that failed:", *failed, sep="\n  ")
    return 0


def cmd_backfill(args) -> int:
    """Pull dated copies of each live provider's pages from the Wayback Machine
    and fold them into the sighting history, then rewrite history + snapshot.
    Run `refresh` first so the DB holds the current history to merge into."""
    from pipeline.providers import PROVIDERS
    from pipeline.providers.types import Context
    from pipeline.runner import run
    from pipeline.services.snapshot import export_snapshot

    conn = _open()
    if not conn.execute("SELECT COUNT(*) FROM cars").fetchone()[0]:
        _print_run(run(conn, PROVIDERS["manual_seed"]))
        _replay(conn)
    only = set(args.only.split(",")) if args.only else None
    shard = (0, 1)
    if args.shard:
        i, n = args.shard.split("/")
        shard = (int(i), int(n))
        if not 0 <= shard[0] < shard[1]:
            raise SystemExit(f"--shard {args.shard}: want i/n with 0 <= i < n")
    ctx = Context(root=ROOT, delay_seconds=args.delay, max_targets=args.max_targets,
                  extras={"since": args.since, "every_days": args.every_days, "shard": shard,
                          "budget_seconds": args.budget_seconds})
    for name, provider in PROVIDERS.items():
        if "backfill" not in provider.capabilities or (only and name not in only):
            continue
        try:
            _print_run(run(conn, provider, "backfill", ctx=ctx))
        except Exception as e:  # noqa: BLE001
            print(f"{name}/backfill: FAILED ({e})")
    _write_history(conn)
    manifest = export_snapshot(conn, args.out, generated_at=args.generated_at)
    print(f"snapshot -> {args.out}: {json.dumps(manifest['counts'])}")
    return 0


def cmd_export_history(args) -> int:
    from pipeline.history import export_history, export_ledger
    conn = _open()
    if args.file:
        n = export_history(conn, args.file, source=args.source)
        print(f"history: {n} observations written to {args.file}")
        if args.ledger_file:
            print(f"history: {export_ledger(conn, args.ledger_file)} backfilled pages written to {args.ledger_file}")
    else:
        _write_history(conn)
    return 0


def cmd_import_history(args) -> int:
    from pipeline.history import import_history, import_ledger
    conn = _open()
    if args.file:
        n = import_history(conn, args.file, replace_source=args.replace_source)
        print(f"history: {n} observations replayed from {args.file}")
    if args.ledger_file:
        print(f"history: {import_ledger(conn, args.ledger_file)} backfilled pages noted from {args.ledger_file}")
    if not args.file and not args.ledger_file:
        _replay(conn)
    return 0


def cmd_status(args) -> int:
    conn = _open()
    for table in ("artifacts", "source_rows", "models", "cars", "trim_map", "offer_observations", "specs", "used_listings", "requirements", "runs"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:19s} {n}")
    n_auto = conn.execute("SELECT COUNT(*) FROM cars WHERE json_extract(payload, '$.auto') = 1").fetchone()[0]
    print(f"{'  of which generated':19s} {n_auto}")
    for r in conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 12"):
        print(f"run {r['id']} {r['source']}/{r['capability']} {r['status']} {r['finished_at']} "
              f"records={r['records']} unmapped={r['unmapped']} errors={r['errors']}")
    return 0


def cmd_models(args) -> int:
    """The catalogue: every electric model known, with what we have for it."""
    conn = _open()
    rows = conn.execute(
        """SELECT m.slug, m.make_name, m.model_name, m.has_deals, m.has_specs,
             (SELECT COUNT(*) FROM specs s WHERE json_extract(s.payload, '$.model_slug') = m.model
                AND (json_extract(s.payload, '$.make_slug') = m.make OR lower(s.make) = lower(COALESCE(m.make_name, m.make)))) AS derivatives,
             (SELECT COUNT(*) FROM cars c WHERE json_extract(c.payload, '$.model_slug') = m.model
                AND (json_extract(c.payload, '$.make_slug') = m.make OR lower(c.make) = lower(COALESCE(m.make_name, m.make)))) AS cars
           FROM models m WHERE electric=1 ORDER BY slug"""
    ).fetchall()
    print(f"{'model':40s} deals specs derivs cars")
    for r in rows:
        name = f"{r['make_name'] or r['slug'].split('/')[0]} {r['model_name'] or r['slug'].split('/')[1]}"
        print(f"{name:40s} {'yes' if r['has_deals'] else '-':5s} {'yes' if r['has_specs'] else '-':5s} {r['derivatives']:6d} {r['cars']:4d}")
    print(f"{len(rows)} electric models")
    return 0


def cmd_trims(args) -> int:
    from pipeline.services.snapshot import unmapped_trims

    rows = unmapped_trims(_open())
    if not rows:
        print("no unmapped trims")
        return 0
    print("Unmapped trims (add to data/seed/trim_map.json with the right car_id):")
    for r in rows:
        why = f" [{r['status']}: {(r.get('evidence') or {}).get('reason', '')}]" if r["status"] == "conflict" else ""
        print(f'  {{ "source": "{r["source"]}", "source_key": "{r["source_key"]}", "car_id": "..." }}'
              f'   # {r["label"] or ""}  first seen {r["first_seen_at"][:10]}{why}')
    return 1


def cmd_deal_table(args) -> int:
    from model.deal_math import compute, print_markdown
    from pipeline.services.snapshot import latest_offers, load_cars, load_requirements

    conn = _open()
    print_markdown(compute(latest_offers(conn), load_requirements(conn).get("quoting_basis")), load_cars(conn))
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

    rp = sub.add_parser("reparse", help="Re-run the parsers over the stored pages (no network), e.g. after a parser or matcher fix.")
    rp.add_argument("--only", help="Comma-separated provider names.")
    rp.add_argument("--out", default=str(DEFAULT_OUT))
    rp.add_argument("--generated-at")
    rp.set_defaults(func=cmd_reparse)

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

    b = sub.add_parser("backfill", help="Fold Wayback Machine copies of the live providers' pages into the sighting history.")
    b.add_argument("--since", default="2025-01-01", help="Earliest capture date to use (YYYY-MM-DD).")
    b.add_argument("--every-days", type=int, default=7, help="At most one capture per this many days per page.")
    b.add_argument("--only", help="Comma-separated provider names.")
    b.add_argument("--max-targets", type=int, help="Stop after this many captures per provider (for a trial run).")
    b.add_argument("--delay", type=float, default=3.0, help="Seconds between requests to the same host.")
    b.add_argument("--shard", help="i/n: only every n-th page (the i-th of them), to split one provider across jobs.")
    b.add_argument("--budget-seconds", type=float, help="Take on no new page after this long; the ledger resumes there next run.")
    b.add_argument("--out", default=str(DEFAULT_OUT))
    b.add_argument("--generated-at")
    b.set_defaults(func=cmd_backfill)

    eh = sub.add_parser("export-history", help="Write offer observations to data/history/observations.jsonl.")
    eh.add_argument("--file", help="Write here instead of data/history/observations.jsonl.")
    eh.add_argument("--source", help="Only this provider's observations.")
    eh.add_argument("--ledger-file", help="Also write the backfill ledger here (with --file).")
    eh.set_defaults(func=cmd_export_history)
    ih = sub.add_parser("import-history", help="Replay data/history/observations.jsonl into the DB.")
    ih.add_argument("--file", help="Read this file instead of data/history/observations.jsonl.")
    ih.add_argument("--replace-source", help="Drop this provider's existing rows first; the file is then its whole history.")
    ih.add_argument("--ledger-file", help="Fold this backfill ledger in (pages already done are skipped by the next backfill).")
    ih.set_defaults(func=cmd_import_history)

    sub.add_parser("status", help="Row counts and recent runs.").set_defaults(func=cmd_status)
    sub.add_parser("models", help="The catalogue of electric models and what has been scraped for each.").set_defaults(func=cmd_models)
    sub.add_parser("trims", help="List source trims that are not mapped to a car (exit 1 if any).").set_defaults(func=cmd_trims)
    sub.add_parser("deal-table", help="Print the normalised offer comparison as markdown.").set_defaults(func=cmd_deal_table)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
