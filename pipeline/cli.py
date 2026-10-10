"""`python -m pipeline <command>`

The nightly job is `nightly`: copy any new committed history into the raw store, build,
scrape every live source into the raw store, build again from scratch, and write the
snapshot. `scrape` and `build` are its two halves.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.db import ROOT, connect, db_path, init_schema

DEFAULT_OUT = ROOT / "web" / "public" / "data"
PARSE_CACHE = ROOT / "data" / "parse-cache.sqlite"
RAW_HELP = "The raw store folder (default: $CAR_RESEARCH_RAW, else ~/car-research-raw)."


def _open():
    conn = connect()
    init_schema(conn)
    return conn


def _store(args):
    from pipeline.raw import RawStore
    return RawStore.open(getattr(args, "raw", None))


def _print_run(res) -> None:
    extra = f", {res.errors} failed" if res.errors else ""
    extra += f", {res.skipped} not on the site" if res.skipped else ""
    print(f"{res.source}/{res.capability}: {res.fetches} fetched ({res.new_bodies} new pages), {res.records} records{extra}", flush=True)


def _build(args, store, out: str | None) -> None:
    from pipeline.build import build
    from pipeline.services.snapshot import export_snapshot

    db = getattr(args, "db", None) or db_path()
    report = build(db, store, cache_path=None if getattr(args, "no_cache", False) else PARSE_CACHE)
    for line in report.lines():
        print(line, flush=True)
    if out:
        manifest = export_snapshot(connect(db), out, generated_at=getattr(args, "generated_at", None))
        print(f"snapshot -> {out}: {json.dumps(manifest['counts'])}", flush=True)


def cmd_build(args) -> int:
    """Raws + legacy history + the owner's files -> a fresh database -> the snapshot."""
    _build(args, _store(args), args.out or None)
    if args.deal_table:
        _deal_table(Path(args.deal_table))
    return 0


def _scrape(args, store) -> list[str]:
    """Every live provider (or --only), in registry order, into the raw store."""
    from pipeline.providers import PROVIDERS
    from pipeline.providers.types import Context
    from pipeline.runner import run

    if not db_path().exists():
        print("no build database yet: building one to discover from", flush=True)
        _build(args, store, None)
    conn = _open()
    only = set(args.only.split(",")) if args.only else None
    ctx = Context(root=ROOT, extras={"raw_store": store})
    failed = []
    for name, provider in PROVIDERS.items():
        if not provider.live or (only and name not in only):
            continue
        for cap in provider.capabilities:
            if cap == "backfill":
                continue  # the Wayback backfill is run by hand: `pipeline backfill`
            try:
                _print_run(run(store, conn, provider, cap, ctx=ctx))
            except Exception as e:  # noqa: BLE001
                failed.append(f"{name}/{cap}: {e}")
                print(f"{name}/{cap}: FAILED ({e})", flush=True)
    conn.close()
    return failed


def cmd_scrape(args) -> int:
    failed = _scrape(args, _store(args))
    if failed:
        print("providers that failed:", *failed, sep="\n  ")
    return 0


def cmd_nightly(args) -> int:
    """The night's work: new committed history into the raw store, scrape, build from scratch, snapshot, deal table."""
    from pipeline.legacy import migrate

    store = _store(args)
    res = migrate(store)
    print(f"legacy: {res['added']} new history versions copied into the raw store", flush=True)
    failed = _scrape(args, store)
    _build(args, store, args.out)
    if args.deal_table:
        _deal_table(Path(args.deal_table))
    if failed:
        print("providers that failed:", *failed, sep="\n  ")
    return 0


def cmd_backfill(args) -> int:
    """Fetch dated copies of each live provider's pages from the Wayback Machine into the raw store.
    Run `build` afterwards to fold them into the price history."""
    from pipeline.providers import PROVIDERS
    from pipeline.providers.types import Context
    from pipeline.runner import run

    store = _store(args)
    if not db_path().exists():
        _build(args, store, None)
    conn = _open()
    only = set(args.only.split(",")) if args.only else None
    shard = (0, 1)
    if args.shard:
        i, n = args.shard.split("/")
        shard = (int(i), int(n))
        if not 0 <= shard[0] < shard[1]:
            raise SystemExit(f"--shard {args.shard}: want i/n with 0 <= i < n")
    ctx = Context(root=ROOT, delay_seconds=args.delay, max_targets=args.max_targets,
                  extras={"since": args.since, "every_days": args.every_days, "shard": shard,
                          "budget_seconds": args.budget_seconds, "raw_store": store})
    for name, provider in PROVIDERS.items():
        if "backfill" not in provider.capabilities or (only and name not in only):
            continue
        try:
            _print_run(run(store, conn, provider, "backfill", ctx=ctx))
        except Exception as e:  # noqa: BLE001
            print(f"{name}/backfill: FAILED ({e})")
    conn.commit()
    return 0


def cmd_raw_migrate(args) -> int:
    """Copy every committed version of data/history into the raw store (source 'legacy')."""
    from pipeline.legacy import migrate

    store = _store(args)
    res = migrate(store)
    print(f"raw store {store.root}: {res['added']} history versions added, {res['already_there']} already there")
    return 0


def cmd_raw_status(args) -> int:
    from collections import Counter

    store = _store(args)
    entries = list(store.entries())
    bodies = list((store.root / "bodies").rglob("*.gz"))
    print(f"raw store {store.root}")
    print(f"  {len(entries)} fetches, {len(bodies)} distinct bodies, {sum(p.stat().st_size for p in bodies) / 1e6:.1f} MB on disk")
    by = Counter((e["origin"], e["source"]) for e in entries)
    for (origin, source), n in sorted(by.items()):
        mine = [e for e in entries if e["source"] == source and e["origin"] == origin]
        days = sorted(e["fetched_at"][:10] for e in mine)
        failed = sum(1 for e in mine if e.get("status") != 200)
        print(f"  {origin:8s} {source:22s} {n:6d} fetches  {days[0]} .. {days[-1]}" + (f"  ({failed} failed)" if failed else ""))
    return 0


def cmd_status(args) -> int:
    conn = _open()
    for table in ("models", "cars", "trim_map", "offer_observations", "specs", "derivatives", "used_listings", "requirements", "runs"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:19s} {n}")
    n_auto = conn.execute("SELECT COUNT(*) FROM cars WHERE json_extract(payload, '$.auto') = 1").fetchone()[0]
    print(f"{'  of which not yours':19s} {n_auto}")
    for r in conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 12"):
        print(f"run {r['source']}/{r['capability']} {r['status']} {r['finished_at']} "
              f"fetches={r['artifacts']} records={r['records']} errors={r['errors']}")
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
              f'   # {r["label"] or ""}  first seen {(r["first_seen_at"] or "")[:10]}{why}')
    return 1


def _deal_table(path: Path | None = None) -> None:
    from model.deal_math import compute, print_markdown
    from pipeline.services.snapshot import latest_offers, load_cars, load_requirements

    conn = _open()
    if path is None:
        print_markdown(compute(latest_offers(conn), load_requirements(conn).get("quoting_basis")), load_cars(conn))
        return
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_markdown(compute(latest_offers(conn), load_requirements(conn).get("quoting_basis")), load_cars(conn))
    path.write_text(buf.getvalue(), encoding="utf-8", newline="\n")


def cmd_deal_table(args) -> int:
    _deal_table()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pipeline", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def build_args(sp, out_default=str(DEFAULT_OUT)):
        sp.add_argument("--raw", help=RAW_HELP)
        sp.add_argument("--db", help="Where to write the database (default: $CAR_RESEARCH_DB, else data/car-research.sqlite).")
        sp.add_argument("--out", default=out_default, help="Snapshot folder; '' to skip the snapshot.")
        sp.add_argument("--generated-at", help="Pin the snapshot timestamp.")
        sp.add_argument("--no-cache", action="store_true", help="Parse every page again, ignoring the parse cache.")

    bd = sub.add_parser("build", help="Build the database from scratch (raws, legacy history, the owner's files) and write the snapshot.")
    build_args(bd)
    bd.add_argument("--deal-table", default="", help="Also write the markdown deal table here.")
    bd.set_defaults(func=cmd_build)

    sc = sub.add_parser("scrape", help="Fetch every live source into the raw store.")
    sc.add_argument("--raw", help=RAW_HELP)
    sc.add_argument("--only", help="Comma-separated provider names.")
    sc.set_defaults(func=cmd_scrape)

    ni = sub.add_parser("nightly", help="New committed history into the raw store, scrape, build from scratch, snapshot.")
    build_args(ni)
    ni.add_argument("--only", help="Comma-separated provider names to scrape.")
    ni.add_argument("--deal-table", default=str(ROOT / "docs" / "deal-comparison.md"), help="Write the markdown deal table here ('' to skip).")
    ni.set_defaults(func=cmd_nightly)

    b = sub.add_parser("backfill", help="Fetch Wayback Machine copies of the live providers' pages into the raw store.")
    b.add_argument("--raw", help=RAW_HELP)
    b.add_argument("--since", default="2025-01-01", help="Earliest capture date to use (YYYY-MM-DD).")
    b.add_argument("--every-days", type=int, default=7, help="At most one capture per this many days per page.")
    b.add_argument("--only", help="Comma-separated provider names.")
    b.add_argument("--max-targets", type=int, help="Stop after this many captures per provider (for a trial run).")
    b.add_argument("--delay", type=float, default=3.0, help="Seconds between requests to the same host.")
    b.add_argument("--shard", help="i/n: only every n-th page (the i-th of them), to split one provider across runs.")
    b.add_argument("--budget-seconds", type=float, help="Take on no new page after this long; the ledger resumes there next run.")
    b.set_defaults(func=cmd_backfill)

    rm = sub.add_parser("raw-migrate", help="Copy every committed version of data/history into the raw store as source 'legacy'.")
    rm.add_argument("--raw", help=RAW_HELP)
    rm.set_defaults(func=cmd_raw_migrate)
    rs = sub.add_parser("raw-status", help="What the raw store holds, by source.")
    rs.add_argument("--raw", help=RAW_HELP)
    rs.set_defaults(func=cmd_raw_status)

    sub.add_parser("status", help="Row counts and recent runs (from the last build).").set_defaults(func=cmd_status)
    sub.add_parser("models", help="The catalogue of electric models and what has been scraped for each.").set_defaults(func=cmd_models)
    sub.add_parser("trims", help="List source trims that are not matched to a car (exit 1 if any).").set_defaults(func=cmd_trims)
    sub.add_parser("deal-table", help="Print the normalised offer comparison as markdown.").set_defaults(func=cmd_deal_table)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
