"""Second pass: the counts specific design choices rest on."""
import sqlite3, json, collections, re, sys
sys.path.insert(0, "C:/Users/Tristan/car-research")
from pipeline.services.facts import model_of, _battery_fit
from pipeline.services import match, resolve

con = sqlite3.connect("file:C:/Users/Tristan/car-research-nightly/data/car-research.sqlite?mode=ro", uri=True)
con.row_factory = sqlite3.Row
PUB = "C:/Users/Tristan/AppData/Local/Temp/claude/c--Users-Tristan-car-research/51d7059d-bf41-4af8-8848-833f98166772/scratchpad/pubdata/"
cars_pub = json.load(open(PUB + "cars.json", encoding="utf-8"))
cars_by_id = {c["id"]: c for c in cars_pub}
catalogue = [dict(r) for r in con.execute("select slug, make, model, make_name, model_name from models where electric=1")]
KW = re.compile(r"(\d+)\s*kw(?!h)", re.I); KWH = re.compile(r"(\d+(?:\.\d+)?)\s*kwh", re.I); BR = re.compile(r"\[([^\]]+)\]")
def sec(t): print("\n" + "=" * 8 + " " + t)

ev = [json.loads(r["payload"]) for r in con.execute("select payload from specs where source='evdb'")]
pages = {str(p.get("evdb_id") or p["spec_key"].split(":", 1)[1]): p for p in (json.loads(r["payload"]) for r in con.execute("select payload from specs where source='evdb_cars'"))}
by_model = collections.defaultdict(list); unfiled = []
for v in ev:
    m = model_of(v.get("make") or "", v.get("model") or "", catalogue)
    (by_model[m["slug"]] if m else unfiled).append(v)
ev_by_url = {v.get("source_url"): v for v in ev}

sec("1. Unfiled EV Database cards: by make, and how many on sale")
c = collections.Counter(v.get("make") for v in unfiled)
print("unfiled:", len(unfiled), " on sale:", sum(1 for v in unfiled if (v['numbers'] or {}).get('on_sale') is True))
print(c.most_common(20))
print("examples on sale:", [(v.get("make"), v.get("model")) for v in unfiled if (v['numbers'] or {}).get('on_sale') is True][:20])

sec("2. Cars with no EV Database variant: why")
why = collections.Counter()
for c_ in cars_pub:
    if c_.get("evdb_url"):
        continue
    vs = by_model.get(c_.get("model_key"), [])
    if not vs:
        why["model has no variant filed"] += 1
    elif not c_.get("battery_kwh"):
        why["car has no battery (stub)"] += 1
    else:
        fits = [v for v in vs if _battery_fit(c_["battery_kwh"], (v["numbers"] or {}).get("battery_usable_kwh")) is not None]
        why["battery fits no variant" if not fits else "fits but not picked"] += 1
print(why)
models_no_variant = collections.Counter(c_.get("model_key") for c_ in cars_pub if not c_.get("evdb_url") and not by_model.get(c_.get("model_key")))
print("models (with cars) that have no variant filed:", len(models_no_variant), models_no_variant.most_common(15))

sec("3. Same-kWh variants of one model with overlapping years: what separates them")
def yrs(v):
    n = v["numbers"] or {}
    a = n.get("year_from") or 0
    b = int(str(n["on_sale_until"])[:4]) if n.get("on_sale_until") else 9999
    return a, b
pairs = 0; sep = collections.Counter(); ex = []
for slug, vs in by_model.items():
    for i in range(len(vs)):
        for j in range(i + 1, len(vs)):
            a, b = vs[i], vs[j]
            na, nb = a["numbers"] or {}, b["numbers"] or {}
            if round(na.get("battery_usable_kwh") or 0) != round(nb.get("battery_usable_kwh") or 0):
                continue
            (a0, a1), (b0, b1) = yrs(a), yrs(b)
            if a1 < b0 or b1 < a0:
                continue
            pairs += 1
            pa, pb = pages.get(a["spec_key"].split(":")[1], {}).get("numbers") or {}, pages.get(b["spec_key"].split(":")[1], {}).get("numbers") or {}
            how = []
            if na.get("seats") != nb.get("seats"): how.append("seats")
            if pa.get("power_kw") and pb.get("power_kw") and abs(pa["power_kw"] - pb["power_kw"]) > 5: how.append("kW (car page)")
            if na.get("zero_to_62_s") and nb.get("zero_to_62_s") and abs(na["zero_to_62_s"] - nb["zero_to_62_s"]) > 0.4: how.append("0-62")
            if pa.get("drive") and pb.get("drive") and pa["drive"] != pb["drive"]: how.append("drive (car page)")
            wa, wb = set(re.findall(r"[a-z0-9+]+", (a.get("model") or "").lower())), set(re.findall(r"[a-z0-9+]+", (b.get("model") or "").lower()))
            if wa != wb: how.append("name words")
            sep[tuple(how) or ("nothing",)] += 1
            if not how or how == ["name words"]:
                if len(ex) < 20: ex.append((slug, a.get("model"), b.get("model"), na.get("zero_to_62_s"), nb.get("zero_to_62_s"), na.get("real_range_mi"), nb.get("real_range_mi")))
print("same-usable-kWh pairs with overlapping years:", pairs)
for k, n in sep.most_common(): print("   ", k, n)
print("pairs separated by nothing or only the name:")
for e in ex: print("   ", e)

sec("4. Carwow vs EV Database on the cars already linked and covered: 0-62 and power")
agree = collections.Counter(); off = []
for c_ in cars_pub:
    v = ev_by_url.get(c_.get("evdb_url") or "")
    if not v: continue
    n = v["numbers"] or {}
    pg = (pages.get(v["spec_key"].split(":")[1], {}) or {}).get("numbers") or {}
    cz = c_.get("zero_to_62_s") or c_.get("zero_to_60_s")
    # carwow's own number for this derivative, not the resolved one (which may be evdb's): read the spec row
    row = con.execute("select json_extract(payload,'$.numbers.zero_to_60_s') z, json_extract(payload,'$.numbers.power_bhp') hp from specs where spec_key=?", (f"carwow-cap:{c_.get('cap_id')}",)).fetchone()
    if not row: continue
    z, hp = row["z"], row["hp"]
    if z and n.get("zero_to_62_s"):
        d = abs(float(z) - float(n["zero_to_62_s"]))
        agree["0-62 within 0.4 s"] += d <= 0.4; agree["0-62 off by > 0.4 s"] += d > 0.4
        if d > 1.0 and len(off) < 15: off.append((c_["id"], c_.get("make"), c_.get("model"), c_.get("trim"), "carwow", z, "evdb", n["zero_to_62_s"], v.get("model")))
    if hp and pg.get("power_kw"):
        d = abs(float(hp) * 0.7457 - float(pg["power_kw"]))
        agree["kW within 5"] += d <= 5; agree["kW off by > 5"] += d > 5
print(agree)
for o in off: print("   ", o)

sec("5. LeaseLoco conflicts: would an exact bracket-set match against the registry names settle them?")
derivs = {str(r["cap_id"]): dict(r) for r in con.execute("select cap_id, name, rrp, version_date from derivatives")}
def bset(name):
    return frozenset(resolve.name_key(b).strip() for b in BR.findall(name or "") if not resolve.SEATS_RE.match(b.strip()))
out = collections.Counter(); ex = []
for r in con.execute("select source, label, evidence from trim_map where status='conflict'"):
    e = json.loads(r["evidence"] or "{}")
    twins = [t.split(":", 1)[1] for t in e.get("twins") or []]
    mine = bset(r["label"])
    hits = [t for t in twins if t in derivs and bset(derivs[t]["name"]) == mine]
    if not twins: out["no twins listed"] += 1
    elif len(hits) == 1: out["exactly one twin with the same brackets"] += 1
    elif len(hits) > 1:
        out["several twins with the same brackets"] += 1
        if len(ex) < 8: ex.append((r["label"], [(t, derivs[t]["name"], derivs[t]["rrp"], derivs[t]["version_date"]) for t in hits]))
    else:
        out["no twin has the same brackets"] += 1
        if len(ex) < 16: ex.append((r["label"], [(t, derivs[t]["name"]) for t in twins if t in derivs][:5]))
print(out)
for x in ex: print("   ", x)

sec("6. Used listings: text drive/trim words against the matched car (the STOP list)")
ul = [dict(r, p=json.loads(r["payload"])) for r in con.execute("select listing_key, source, year, car_id, payload from used_listings where car_id is not null")]
bad = collections.Counter(); ex = []
DRIVE = {"awd": "Four wheel drive", "4wd": "Four wheel drive", "rwd": "Rear wheel drive", "fwd": "Front wheel drive", "2wd": None, "quattro": "Four wheel drive", "4motion": "Four wheel drive", "xdrive": "Four wheel drive", "dual": "Four wheel drive"}
for l in ul:
    c_ = cars_by_id.get(l["car_id"]);  t = (l["p"].get("derivative") or "").lower()
    if not c_: continue
    words = set(re.findall(r"[a-z0-9]+", t))
    said = {DRIVE[w] for w in words if w in DRIVE and DRIVE[w]}
    if said and c_.get("drive") and c_["drive"] not in said:
        bad["drive in text differs from the car's"] += 1
        if len(ex) < 10: ex.append((l["source"], l["p"].get("derivative"), l["year"], "->", c_["id"], c_.get("trim"), c_.get("drive")))
    m = KWH.search(t)
    if m and c_.get("battery_kwh") and abs(float(m.group(1)) - float(c_["battery_kwh"])) > 3:
        bad["kWh in text differs by > 3"] += 1
    if ("long" in words and "range" in words) and "standard" in (c_.get("trim") or "").lower():
        bad["'long range' text on a 'standard' car"] += 1
print("matched used listings:", len(ul), dict(bad))
for e in ex: print("   ", e)
print("Tesla derivatives (trim · engine, battery, drive):")
for c_ in cars_pub:
    if c_.get("make") == "Tesla" and c_.get("on_sale"):
        print("   ", c_["id"], c_.get("model"), "|", c_.get("trim"), "|", c_.get("battery_kwh"), c_.get("drive"), c_.get("power_kw"))

sec("7. Used listings wrongly on the current version: an earlier variant covers the listing year and its battery")
n_wrong = 0; n_checked = 0; by_make = collections.Counter(); ex = []
for r in con.execute("select listing_key, source, year, car_id, make_slug, model_slug, json_extract(payload,'$.derivative') d from used_listings where car_id is not null and year is not null"):
    c_ = cars_by_id.get(r["car_id"])
    if not c_ or not c_.get("on_sale_since"): continue
    n_checked += 1
    if r["year"] >= int(str(c_["on_sale_since"])[:4]): continue
    vs = by_model.get(c_.get("model_key"), [])
    m = KWH.search(r["d"] or ""); tk = float(m.group(1)) if m else c_.get("battery_kwh")
    earlier = [v for v in vs if yrs(v)[0] <= r["year"] <= yrs(v)[1] and tk and _battery_fit(tk, (v["numbers"] or {}).get("battery_usable_kwh")) is not None]
    if earlier:
        n_wrong += 1; by_make[r["make_slug"]] += 1
        if len(ex) < 12: ex.append((r["source"], r["d"], r["year"], "->", c_["id"], c_.get("on_sale_since"), "earlier:", [v.get("model") for v in earlier][:3]))
print("checked:", n_checked, " registered before the car's version and an earlier variant fits:", n_wrong)
print(by_make.most_common(12))
for e in ex: print("   ", e)

sec("8. Derivative version dates vs EV Database on_sale_since: do price-list versions sit inside one variant's years?")
cnt = collections.Counter()
for c_ in cars_pub:
    v = ev_by_url.get(c_.get("evdb_url") or "")
    if not v or not c_.get("version_date"): continue
    a, b = yrs(v)
    y = int(c_["version_date"][:4])
    cnt["version date inside variant years" if a <= y <= b else ("version date before variant" if y < a else "version date after variant ended")] += 1
print(cnt)

sec("9. cinch/motorpoint derivative text vs CAP registry names: exact name match rate")
names = {resolve.name_key(d["name"]): cap for cap, d in derivs.items()}
hit = collections.Counter()
for r in con.execute("select source, json_extract(payload,'$.derivative') d from used_listings where source in ('cinch_used','motorpoint_used')"):
    k = resolve.name_key(r["d"]); k2 = re.sub(r"\s*\[[^\]]*\]", "", k).strip()
    hit[(r["source"], "exact CAP name" if k in names else ("CAP name minus brackets" if k2 in {re.sub(r'\s*\[[^\]]*\]', '', n).strip() for n in names} else "no"))] += 1
for k, n in sorted(hit.items()): print("   ", k, n)
