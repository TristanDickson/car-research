"""Gold writers: what each source said, upserted from parsed records dated by when
the page was fetched. Nothing here decides which car a record is (pipeline/build.py
does that afterwards, over every record at once) and nothing here creates a car.

Every upsert tolerates being fed out of order (a legacy history file and a fresh
fetch can arrive either way round): first seen is the minimum, last seen the
maximum, and the row's content is the one with the latest last-seen."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from pipeline.providers.types import ParsedRecord

PRICE_FIELDS = (
    "vehicle_price", "monthly_payment", "apr", "gfv", "customer_deposit",
    "manufacturer_contribution", "num_payments", "term_months", "initial_rental",
    "monthly_rental", "num_rentals", "fees_gbp", "annual_mileage",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dump(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def fingerprint(row: dict) -> str:
    return hashlib.sha1(_dump({k: row.get(k) for k in PRICE_FIELDS}).encode()).hexdigest()[:16]


def spec_fingerprint(row: dict) -> str:
    return hashlib.sha1(_dump({k: row.get(k) for k in ("features", "flags", "numbers", "rrp", "trim", "variant")}).encode()).hexdigest()[:16]


_MODEL_NOISE = {"electric", "electrified", "hatchback", "estate", "saloon", "suv", "mpv", "coupe", "ev", "e-tech", "hatch",
                "5dr", "4dr", "sportback", "fastback", "gran", "tourer", "touring", "shooting", "brake", "cabrio", "convertible"}


def _model_norm(s: str | None) -> str:
    words = [w.lstrip("0") or "0" if w.isdigit() else w   # 'Ora 03' is 'Ora 3'
             for w in (s or "").lower().replace("-", " ").split() if w not in _MODEL_NOISE]
    return " ".join(words)


def model_agrees(wanted: str | None, car: dict) -> bool:
    """'Kona Electric' / 'Kona', 'Ioniq 3 Hatchback' / 'Ioniq 3', 'PV5' / 'PV5
    Passenger' agree; 'Ioniq 3' / 'Ioniq 5' do not."""
    a = _model_norm(wanted)
    if not a:
        return True
    for b in (_model_norm(car.get("model")), _model_norm((car.get("model_slug") or "").replace("-", " "))):
        if b and (a == b or a.startswith(b + " ") or b.startswith(a + " ")):
            return True
    return False


def _latest(table: str, col: str) -> str:
    """Take the incoming value only when the incoming row is at least as recent."""
    return f"{col}=CASE WHEN excluded.last_seen_at >= {table}.last_seen_at THEN excluded.{col} ELSE {table}.{col} END"


def _span(table: str) -> str:
    return (f"first_seen_at=MIN({table}.first_seen_at, excluded.first_seen_at), "
            f"last_seen_at=MAX({table}.last_seen_at, excluded.last_seen_at)")


def upsert_model(conn: sqlite3.Connection, r: dict, source: str, artifact_id: int | None, run_id: int | None, now: str,
                 first_seen_at: str | None = None, last_seen_at: str | None = None) -> None:
    conn.execute(
        f"""INSERT INTO models (slug, make, model, make_name, model_name, electric, has_deals, has_specs, source, payload,
              first_seen_at, last_seen_at, artifact_id, run_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(slug) DO UPDATE SET
              make_name=COALESCE(excluded.make_name, models.make_name), model_name=COALESCE(excluded.model_name, models.model_name),
              electric=COALESCE(excluded.electric, models.electric), has_deals=COALESCE(excluded.has_deals, models.has_deals),
              has_specs=COALESCE(excluded.has_specs, models.has_specs), {_latest('models', 'source')}, {_latest('models', 'payload')},
              {_span('models')}, artifact_id=excluded.artifact_id, run_id=excluded.run_id""",
        (r["slug"], r["make"], r["model"], r.get("make_name"), r.get("model_name"), r.get("electric"), r.get("has_deals"),
         r.get("has_specs"), source, _dump(r), first_seen_at or now, last_seen_at or now, artifact_id, run_id),
    )


def upsert_spec(conn: sqlite3.Connection, r: dict, source: str, artifact_id: int | None, run_id: int | None, now: str,
                first_seen_at: str | None = None, last_seen_at: str | None = None, changed_at: str | None = None) -> None:
    """One source variant's latest state; `changed_at` moves when its equipment or
    numbers change. car_id is left empty: the build sets it once every record is in."""
    r = {k: v for k, v in r.items() if k != "car_id"}
    first, last = first_seen_at or now, last_seen_at or now
    latest = ", ".join(_latest("specs", c) for c in ("source", "make", "model", "trim", "variant", "cap_id", "version_date",
                                                      "payload", "fingerprint"))
    conn.execute(
        f"""INSERT INTO specs (spec_key, source, make, model, trim, variant, cap_id, version_date, car_id, image_url,
              fingerprint, payload, first_seen_at, last_seen_at, changed_at, artifact_id, run_id)
            VALUES (?,?,?,?,?,?,?,?,NULL,?,?,?,?,?,?,?,?)
            ON CONFLICT(spec_key) DO UPDATE SET
              changed_at=CASE WHEN excluded.last_seen_at < specs.last_seen_at THEN specs.changed_at
                              WHEN specs.fingerprint IS NOT excluded.fingerprint THEN excluded.changed_at
                              ELSE specs.changed_at END,
              {latest},
              image_url=CASE WHEN excluded.last_seen_at >= specs.last_seen_at THEN COALESCE(excluded.image_url, specs.image_url)
                             ELSE COALESCE(specs.image_url, excluded.image_url) END,
              {_span('specs')}, artifact_id=excluded.artifact_id, run_id=excluded.run_id""",
        (r["spec_key"], source, r.get("make"), r.get("model"), r.get("trim"), r.get("variant"), r.get("cap_id"),
         r.get("version_date"), r.get("image_url"), spec_fingerprint(r), _dump(r), first, last, changed_at or last,
         artifact_id, run_id),
    )


def upsert_derivative(conn: sqlite3.Connection, r: dict, source: str, artifact_id: int | None, run_id: int | None, now: str,
                      first_seen_at: str | None = None, last_seen_at: str | None = None) -> None:
    """A row of the registry: every derivative by CAP name, with its brackets."""
    latest = ", ".join(_latest("derivatives", c) for c in ("make_slug", "model_slug", "name", "trim", "engine", "payload"))
    conn.execute(
        f"""INSERT INTO derivatives (cap_id, make_slug, model_slug, name, trim, engine, rrp, version_date, payload,
              first_seen_at, last_seen_at, artifact_id, run_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(cap_id) DO UPDATE SET {latest},
              rrp=CASE WHEN excluded.last_seen_at >= derivatives.last_seen_at THEN COALESCE(excluded.rrp, derivatives.rrp)
                       ELSE COALESCE(derivatives.rrp, excluded.rrp) END,
              version_date=CASE WHEN excluded.last_seen_at >= derivatives.last_seen_at THEN COALESCE(excluded.version_date, derivatives.version_date)
                                ELSE COALESCE(derivatives.version_date, excluded.version_date) END,
              {_span('derivatives')}, artifact_id=excluded.artifact_id, run_id=excluded.run_id""",
        (r["cap_id"], r["make_slug"], r["model_slug"], r["name"], r.get("trim"), r.get("engine"), r.get("rrp"), r.get("version_date"),
         _dump(r), first_seen_at or now, last_seen_at or now, artifact_id, run_id),
    )


def upsert_options(conn: sqlite3.Connection, r: dict, artifact_id: int | None, run_id: int | None, now: str,
                   first_seen_at: str | None = None, last_seen_at: str | None = None) -> None:
    conn.execute(
        f"""INSERT INTO options (cap_id, payload, first_seen_at, last_seen_at, artifact_id, run_id) VALUES (?,?,?,?,?,?)
            ON CONFLICT(cap_id) DO UPDATE SET {_latest('options', 'payload')}, {_span('options')},
              artifact_id=excluded.artifact_id, run_id=excluded.run_id""",
        (r["cap_id"], _dump(r), first_seen_at or now, last_seen_at or now, artifact_id, run_id),
    )


def upsert_configuration(conn: sqlite3.Connection, r: dict, artifact_id: int | None, run_id: int | None, now: str,
                         first_seen_at: str | None = None, last_seen_at: str | None = None) -> None:
    latest = ", ".join(_latest("configurations", c) for c in ("make_slug", "model_slug", "trim", "battery_kwh", "price", "payload"))
    conn.execute(
        f"""INSERT INTO configurations (fsc, make_slug, model_slug, trim, battery_kwh, price, payload, first_seen_at, last_seen_at,
              artifact_id, run_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(fsc) DO UPDATE SET {latest}, {_span('configurations')},
              artifact_id=excluded.artifact_id, run_id=excluded.run_id""",
        (r["fsc"], r["make_slug"], r["model_slug"], r.get("trim"), r.get("battery_kwh"), r.get("price"), _dump(r),
         first_seen_at or now, last_seen_at or now, artifact_id, run_id),
    )


def upsert_used_listing(conn: sqlite3.Connection, r: dict, source: str, artifact_id: int | None, run_id: int | None, now: str,
                        first_seen_at: str | None = None, last_seen_at: str | None = None, present: int = 1) -> None:
    """A used listing's latest state. car_id is left empty: the build sets it."""
    r = {k: v for k, v in r.items() if k != "car_id"}
    latest = ", ".join(_latest("used_listings", c) for c in ("price_gbp", "mileage", "present", "payload", "make", "make_slug",
                                                              "model", "model_slug", "year"))
    conn.execute(
        f"""INSERT INTO used_listings (listing_key, source, make, make_slug, model, model_slug, car_id, price_gbp, year, mileage,
              present, payload, first_seen_at, last_seen_at, artifact_id, run_id)
            VALUES (?,?,?,?,?,?,NULL,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(listing_key) DO UPDATE SET {latest}, {_span('used_listings')},
              artifact_id=excluded.artifact_id, run_id=excluded.run_id""",
        (r["listing_key"], source, r.get("make"), r.get("make_slug"), r.get("model"), r.get("model_slug"),
         r.get("price_gbp"), r.get("year"), r.get("mileage"), int(present), _dump(r), first_seen_at or now, last_seen_at or now,
         artifact_id, run_id),
    )


def upsert_used_span(conn: sqlite3.Connection, d: dict) -> None:
    """A used asking-price span as the legacy history recorded it."""
    conn.execute(
        """INSERT INTO used_observations (listing_key, source, price_gbp, mileage, observed_at, confirmed_at, present)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(listing_key, observed_at, source) DO UPDATE SET
             confirmed_at=MAX(COALESCE(used_observations.confirmed_at, ''), COALESCE(excluded.confirmed_at, '')),
             price_gbp=excluded.price_gbp, mileage=excluded.mileage, present=excluded.present""",
        (d["listing_key"], d["source"], d.get("price_gbp"), d.get("mileage"), d["observed_at"], d.get("confirmed_at"),
         int(d.get("present", 1))),
    )


def merge_used_sighting(conn: sqlite3.Connection, key: str, source: str, price: float | None, mileage: int | None,
                        present: bool, now: str, run_id: int | None) -> None:
    """The listing's asking price as spans: the same price seen again extends
    the open span; a new price, or the listing going, opens a new one."""
    last = conn.execute(
        "SELECT id, price_gbp, present, observed_at, confirmed_at FROM used_observations WHERE listing_key=? "
        "ORDER BY observed_at DESC, id DESC LIMIT 1", (key,),
    ).fetchone()
    if last and (last["confirmed_at"] or last["observed_at"]) > now:
        return   # a page older than what is held already: the newer state stands
    if last and bool(last["present"]) == present and (not present or last["price_gbp"] == price):
        conn.execute("UPDATE used_observations SET confirmed_at=?, mileage=COALESCE(?, mileage), run_id=COALESCE(?, run_id) WHERE id=?",
                     (now, mileage, run_id, last["id"]))
        return
    if last and last["observed_at"] == now:
        conn.execute("UPDATE used_observations SET price_gbp=?, mileage=?, present=?, confirmed_at=? WHERE id=?",
                     (price, mileage, int(present), now, last["id"]))
        return
    conn.execute(
        "INSERT INTO used_observations (listing_key, source, price_gbp, mileage, observed_at, confirmed_at, present, run_id) VALUES (?,?,?,?,?,?,?,?)",
        (key, source, price, mileage, now, now, int(present), run_id),
    )


def backfill_used_spans(conn: sqlite3.Connection) -> int:
    """A span for every listing that has none yet (stock recorded before spans
    existed): its current price from first to last sighting. Idempotent."""
    rows = conn.execute(
        """SELECT l.listing_key, l.source, l.price_gbp, l.mileage, l.first_seen_at, l.last_seen_at, l.present
             FROM used_listings l WHERE NOT EXISTS (SELECT 1 FROM used_observations o WHERE o.listing_key=l.listing_key)"""
    ).fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO used_observations (listing_key, source, price_gbp, mileage, observed_at, confirmed_at, present) VALUES (?,?,?,?,?,?,1)",
            (r["listing_key"], r["source"], r["price_gbp"], r["mileage"], r["first_seen_at"], r["last_seen_at"]),
        )
        if not r["present"]:
            # Gone since its last sighting; a car seen once gets its closing row a second later.
            gone_at = r["last_seen_at"]
            if gone_at == r["first_seen_at"]:
                gone_at = (datetime.fromisoformat(gone_at) + timedelta(seconds=1)).isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO used_observations (listing_key, source, price_gbp, mileage, observed_at, confirmed_at, present) VALUES (?,?,?,?,?,?,0)",
                (r["listing_key"], r["source"], r["price_gbp"], r["mileage"], gone_at, gone_at),
            )
    return len(rows)


def write(conn: sqlite3.Connection, source: str, records: dict[str, list[tuple[int | None, ParsedRecord]]],
          run_id: int | None, now: str | None = None) -> int:
    """Upsert one fetch's records, dated `now` (when the page was fetched). Offers, the
    owner's cars and decisions are not written here: the build folds offers into spans
    once every record is matched, and reads the owner's files itself."""
    now = now or _now()
    written = 0
    for artifact_id, rec in records.get("model", []):
        upsert_model(conn, rec.row, source, artifact_id, run_id, now)
        written += 1
    for artifact_id, rec in records.get("spec", []):
        upsert_spec(conn, rec.row, source, artifact_id, run_id, now)
        written += 1
    for artifact_id, rec in records.get("derivative", []):
        upsert_derivative(conn, rec.row, source, artifact_id, run_id, now)
        written += 1
    for artifact_id, rec in records.get("options", []):
        upsert_options(conn, rec.row, artifact_id, run_id, now)
        written += 1
    for artifact_id, rec in records.get("configuration", []):
        upsert_configuration(conn, rec.row, artifact_id, run_id, now)
        written += 1

    used_seen: dict[str, set[str]] = {}
    for artifact_id, rec in records.get("used", []):
        r = rec.row
        upsert_used_listing(conn, r, source, artifact_id, run_id, now)
        merge_used_sighting(conn, r["listing_key"], source, r.get("price_gbp"), r.get("mileage"), True, now, run_id)
        used_seen.setdefault(r.get("listing_url") or "", set()).add(r["listing_key"])
        written += 1
    for listing_url, keys in used_seen.items():
        # A listing missing from the page it came from (a model's cards on Carwow,
        # a make's stock on cinch, the whole electric listing on Motorpoint) has
        # been sold or withdrawn; another source's, a page not fetched this run, or
        # a listing seen after this page was fetched, is untouched.
        marks = ",".join("?" * len(keys))
        where = f"""source=? AND COALESCE(json_extract(payload, '$.listing_url'), '')=? AND present=1
                    AND last_seen_at < ? AND listing_key NOT IN ({marks})"""
        params = (source, listing_url, now, *keys)
        gone = conn.execute(f"SELECT listing_key, price_gbp, mileage FROM used_listings WHERE {where}", params).fetchall()
        conn.execute(f"UPDATE used_listings SET present=0 WHERE {where}", params)
        for g in gone:
            merge_used_sighting(conn, g["listing_key"], source, g["price_gbp"], g["mileage"], False, now, run_id)

    for artifact_id, rec in records.get("requirements", []):
        r = rec.row
        conn.execute(
            """INSERT INTO requirements (id, as_of, payload, source, artifact_id, updated_at) VALUES (1,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET as_of=excluded.as_of, payload=excluded.payload, source=excluded.source,
                 artifact_id=excluded.artifact_id, updated_at=excluded.updated_at""",
            (r.get("as_of"), _dump(r), source, artifact_id, now),
        )
        written += 1
    return written
