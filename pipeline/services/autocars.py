"""Cars generated from the scraped catalogue, for every derivative nobody has
curated by hand.

A hand-curated car (data/seed/cars.json) is the household's own reading of a
trim: which pack the heat pump needs, whether the cabin socket is really there.
For the other ~1,500 EV derivatives on sale the pipeline makes a car record
itself, from the source that knows the derivative best:

  from a Carwow specification row   the full thing: numbers, equipment flags,
                                    RRP, image, model year (derivative version)
  from a Carwow deals row (a stub)  enough to hang a price on: make, model,
                                    trim · engine, RRP, version date. Seen for
                                    derivatives that only an archived deals page
                                    mentions (run-out stock, last year's list).

Ids are carwow-cap:<cap id>, the same key the trim map uses, so a derivative
promoted to a hand-curated car later just maps over it. `auto: true` marks the
record; tri-state fields are 'unknown' when the source does not list the item,
never 'none' (an equipment list that omits the heat pump is not proof there is
none).
"""
from __future__ import annotations

AUTO_NOTE = ("Generated from Carwow's specification page for this derivative. Equipment is listed per trim, "
             "so a derivative-only difference (a no-heat-pump version of the same trim) does not show here.")
STUB_NOTE = ("Generated from a Carwow deals page: only what that page prints (trim, engine, RRP). "
             "The specification page did not list this derivative when last read.")


def _tri(v: str | None) -> str:
    return v if v in ("standard", "option") else "unknown"


def _yes(v: str | None) -> bool | None:
    return True if v in ("standard", "option") else None


def auto_id(cap_id: str) -> str:
    return f"carwow-cap:{cap_id}"


def from_spec(r: dict) -> dict:
    """A car from a carwow_specs row (the parsed record's row dict)."""
    n = r.get("numbers") or {}
    fl = r.get("flags") or {}
    engine = r.get("engine") or ""
    trim = (r.get("trim") or "").strip()
    return {
        "id": auto_id(r["cap_id"]), "auto": True, "source_kind": "spec", "spec_key": r.get("spec_key"),
        "make": r["make"], "model": r["model"], "trim": f"{trim} · {engine}".strip(" ·"),
        "variant": engine, "cap_id": r["cap_id"], "model_slug": r.get("model_slug"), "make_slug": r.get("make_slug"),
        "model_year": int(r["version_date"][:4]) if r.get("version_date") else None,
        "version_date": r.get("version_date"), "fuel": "bev",
        "seats": n.get("seats"), "doors": n.get("doors"), "battery_kwh": n.get("battery_kwh"),
        "wltp_range_mi": n.get("wltp_range_mi"), "power_hp": n.get("power_bhp"), "zero_to_60_s": n.get("zero_to_60_s"),
        "boot_l": n.get("boot_l"), "boot_max_l": n.get("boot_max_l"), "turning_circle_m": n.get("turning_circle_m"),
        "wheelbase_m": n.get("wheelbase_m"), "drive": n.get("drive"),
        "heat_pump": _tri(fl.get("heat_pump")), "internal_v2l": _tri(fl.get("v2l_internal")),
        "external_v2l": _tri(fl.get("v2l_external")),
        "heated_seats": _yes(fl.get("heated_front_seats")), "camera_360": _yes(fl.get("camera_360")),
        "glass_roof": _yes(fl.get("panoramic_roof")), "memory_seats": _yes(fl.get("memory_seats")),
        "list_price_gbp": r.get("rrp"), "grant_gbp": None, "used_from_gbp": n.get("used_from_gbp"),
        "image_url": r.get("image_url"), "notes": AUTO_NOTE, "verification": "scraped",
    }


def from_stub(stub: dict) -> dict:
    """A car from what a deals page prints about a derivative."""
    engine = stub.get("engine") or ""
    trim = (stub.get("trim") or "").strip()
    version = stub.get("version_date")
    return {
        "id": auto_id(stub["cap_id"]), "auto": True, "source_kind": "stub",
        "make": stub["make"], "model": stub["model"], "trim": f"{trim} · {engine}".strip(" ·"),
        "variant": engine, "cap_id": stub["cap_id"], "model_slug": stub.get("model_slug"), "make_slug": stub.get("make_slug"),
        "model_year": int(version[:4]) if version else None, "version_date": version, "fuel": "bev",
        "heat_pump": "unknown", "internal_v2l": "unknown", "external_v2l": "unknown",
        "list_price_gbp": stub.get("rrp"), "grant_gbp": None, "image_url": stub.get("image_url"),
        "notes": STUB_NOTE, "verification": "scraped",
    }
