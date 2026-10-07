"""Sightings in, series out: the exporter's side of model/sightings.

Loads every offer observation and used observation as a Sighting, costs them
(as of their own day for history, as of today for what things cost now), and
hands the exporter the series, the residual evidence over time, and the
current best per subject, route and source. No arithmetic lives here.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date

from model.sightings import Sighting, cost_all, current, gone_dates, residual_series, series, source_of


def offer_sightings(conn: sqlite3.Connection, model_of: dict[str, str]) -> list[Sighting]:
    rows = conn.execute(
        "SELECT offer_key, car_id, source, observed_at, confirmed_at, present, finance_type, seller, payload "
        "FROM offer_observations WHERE finance_type IN ('cash', 'pcp', 'pch') ORDER BY offer_key, observed_at"
    ).fetchall()
    out = []
    for r in rows:
        deal = json.loads(r["payload"])
        out.append(Sighting(key=r["offer_key"], route=r["finance_type"], source=source_of(r["source"]),
                            model=model_of.get(r["car_id"], ""), car_id=r["car_id"],
                            seen_from=r["observed_at"][:10], seen_to=(r["confirmed_at"] or r["observed_at"])[:10],
                            present=bool(r["present"]), deal=deal, seller=r["seller"] or deal.get("dealer")))
    return out


def used_sightings(conn: sqlite3.Connection) -> list[Sighting]:
    try:
        rows = conn.execute(
            "SELECT o.listing_key, o.source, l.car_id, l.make_slug, l.model_slug, l.year, o.mileage, o.price_gbp, o.observed_at, "
            "o.confirmed_at, o.present, json_extract(l.payload, '$.vrm') AS vrm, json_extract(l.payload, '$.town') AS town "
            "FROM used_observations o JOIN used_listings l ON l.listing_key = o.listing_key ORDER BY o.listing_key, o.observed_at"
        ).fetchall()
    except sqlite3.OperationalError as e:
        raise RuntimeError(f"used sightings unavailable: {e}") from e
    return [Sighting(key=r["listing_key"], route="used", source=source_of(r["source"]),
                     model=f"{(r['make_slug'] or '').lower()}/{r['model_slug'] or ''}", car_id=r["car_id"],
                     seen_from=r["observed_at"][:10], seen_to=(r["confirmed_at"] or r["observed_at"])[:10],
                     present=bool(r["present"]),
                     deal={"price": r["price_gbp"], "year": r["year"], "mileage": r["mileage"], "vrm": r["vrm"]},
                     seller=r["town"]) for r in rows]


def build(conn: sqlite3.Connection, model_of: dict[str, str], basis: dict, today: date, stale_days: int) -> dict:
    """{'series': [...], 'residuals': [...], 'current': {subject: {route: {source: point}}}}."""
    sightings = offer_sightings(conn, model_of) + used_sightings(conn)
    history = cost_all(sightings, basis)
    now = cost_all(sightings, basis, as_of=today)
    return {"series": series(history, gone_dates(sightings)), "residuals": residual_series([s for s in sightings if s.route == "used"], today),
            "current": current(now, today, stale_days), "sightings": len(sightings), "costed": len(history)}
