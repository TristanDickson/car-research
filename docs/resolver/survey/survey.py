"""Read-only survey of the build database and the published snapshot for the resolver design."""
import sqlite3, json, collections, re, sys
sys.path.insert(0, "C:/Users/Tristan/car-research")
from pipeline.services.facts import model_of, pick_variant, _battery_fit
from pipeline.services import match, resolve, claims
from pipeline import gold

con = sqlite3.connect("file:C:/Users/Tristan/car-research-nightly/data/car-research.sqlite?mode=ro", uri=True)
con.row_factory = sqlite3.Row
PUB = "C:/Users/Tristan/AppData/Local/Temp/claude/c--Users-Tristan-car-research/51d7059d-bf41-4af8-8848-833f98166772/scratchpad/pubdata/"
cars_pub = json.load(open(PUB + "cars.json", encoding="utf-8"))
used_spans = json.load(open(PUB + "used_spans.json", encoding="utf-8"))
catalogue = [dict(r) for r in con.execute("select slug, make, model, make_name, model_name from models where electric=1")]
for m in catalogue:
    m.setdefault("make_name", None)

KW = re.compile(r"(\d+)\s*kw(?!h)", re.I)
KWH = re.compile(r"(\d+(?:\.\d+)?)\s*kwh", re.I)
BR = re.compile(r"\[([^\]]+)\]")
SEAT = re.compile(r"\b(\d)\s*-?\s*(?:seat|seats|st)\b", re.I)

def sec(t):
    print("\n" + "=" * 8 + " " + t)

# ---------------------------------------------------------------- A. registry
sec("A. REGISTRY (derivatives table, Carwow model pages)")
derivs = [dict(r, p=json.loads(r["payload"])) for r in con.execute("select * from derivatives")]
print("derivatives:", len(derivs))
print("names with kW:", sum(1 for d in derivs if KW.search(d["name"])), " kWh:", sum(1 for d in derivs if KWH.search(d["name"])),
      " brackets:", sum(1 for d in derivs if BR.search(d["name"])), " seat count:", sum(1 for d in derivs if SEAT.search(d["name"])),
      " rrp:", sum(1 for d in derivs if d["rrp"]), " version_date:", sum(1 for d in derivs if d["version_date"]))
print("makes:", len({d["make_slug"] for d in derivs}), " models:", len({(d["make_slug"], d["model_slug"]) for d in derivs}))
brk = collections.Counter(b.strip() for d in derivs for b in BR.findall(d["name"]))
print("bracket kinds (top 25):", brk.most_common(25))
# twins: same make/model/trim/engine
groups = collections.defaultdict(list)
for d in derivs:
    groups[(d["make_slug"], d["model_slug"], (d["trim"] or "").lower(), (d["engine"] or "").lower())].append(d)
twins = {k: v for k, v in groups.items() if len(v) > 1}
print("trim+engine groups:", len(groups), " with 2+ derivatives (twins):", len(twins), " derivatives in twins:", sum(len(v) for v in twins.values()))
sizes = collections.Counter(len(v) for v in twins.values())
print("twin group sizes:", sorted(sizes.items()))
distinct_rrp = sum(1 for v in twins.values() if len({d["rrp"] for d in v}) == len(v))
same_rrp = sum(1 for v in twins.values() if len({d["rrp"] for d in v}) < len(v))
print("twin groups with all-distinct RRPs:", distinct_rrp, " with a shared RRP:", same_rrp)
only_brackets = sum(1 for v in twins.values() if len({BR.sub('', d['name']).strip() for d in v}) == 1)
distinct_names = sum(1 for v in twins.values() if len({d["name"] for d in v}) == len(v))
print("twin groups whose names differ only by brackets:", only_brackets, " all names distinct:", distinct_names)
print("twin groups with the same name twice (price-list versions):", sum(1 for v in twins.values() if len({d['name'] for d in v}) < len(v)))
print("examples of twins with same name:")
n = 0
for k, v in twins.items():
    if len({d["name"] for d in v}) < len(v) and n < 6:
        n += 1
        print("  ", k[:2], [(d["cap_id"], d["name"], d["rrp"], d["version_date"]) for d in v])
# engine text kWh vs spec number
sec("A2. CARWOW SPEC rows: engine text vs numbers")
specs_cw = [json.loads(r["payload"]) for r in con.execute("select payload from specs where source='carwow_specs'")]
diff = []
for p in specs_cw:
    n_ = (p.get("numbers") or {}).get("battery_kwh")
    m = KWH.search(p.get("engine") or "")
    if n_ and m and abs(float(m.group(1)) - float(n_)) > 0.6:
        diff.append((p["make"], p["model"], p["engine"], n_))
print("carwow_specs rows:", len(specs_cw), " engine prints kWh:", sum(1 for p in specs_cw if KWH.search(p.get('engine') or '')),
      " engine prints kW:", sum(1 for p in specs_cw if KW.search(p.get('engine') or '')),
      " numbers.battery_kwh:", sum(1 for p in specs_cw if (p.get('numbers') or {}).get('battery_kwh')))
print("rows where the engine text's kWh differs from the number by > 0.6:", len(diff))
for x in diff[:15]:
    print("   ", x)
drive = collections.Counter((p.get("numbers") or {}).get("drive") for p in specs_cw)
print("drive values:", drive.most_common(8))
vd = collections.Counter((p.get("version_date") or "")[:4] for p in specs_cw)
print("version_date years:", sorted(vd.items()))

# ---------------------------------------------------------------- B. EV Database
sec("B. EV DATABASE variants per catalogue model")
ev = [json.loads(r["payload"]) for r in con.execute("select payload from specs where source='evdb'")]
pages = {str(p.get("evdb_id") or p["spec_key"].split(":", 1)[1]): p for p in (json.loads(r["payload"]) for r in con.execute("select payload from specs where source='evdb_cars'"))}
by_model = collections.defaultdict(list)
unfiled = 0
for v in ev:
    m = model_of(v.get("make") or "", v.get("model") or "", catalogue)
    if not m:
        unfiled += 1
        continue
    by_model[m["slug"]].append(v)
print("evdb index cards:", len(ev), " filed under a catalogue model:", sum(len(v) for v in by_model.values()), " unfiled:", unfiled,
      " models with any:", len(by_model), " car pages read:", len(pages))
print("variants per model:", sorted(collections.Counter(len(v) for v in by_model.values()).items()))
same_kwh = 0; same_kwh_models = []
for slug, vs in by_model.items():
    c = collections.Counter(round((v["numbers"] or {}).get("battery_usable_kwh") or 0) for v in vs)
    if any(n > 1 for n in c.values()):
        same_kwh += 1
        same_kwh_models.append(slug)
print("models with two or more variants of the same usable kWh (rounded):", same_kwh)
on = collections.Counter((v["numbers"] or {}).get("on_sale") for v in ev)
print("on_sale values:", on)
print("cards with on_sale_until:", sum(1 for v in ev if (v['numbers'] or {}).get('on_sale_until')), " year_from:", sum(1 for v in ev if (v['numbers'] or {}).get('year_from')))
print("car pages with power_kw:", sum(1 for p in pages.values() if (p['numbers'] or {}).get('power_kw')), " with battery_kwh (gross):", sum(1 for p in pages.values() if (p['numbers'] or {}).get('battery_kwh')))
# gross vs usable ratio on car pages
ratios = []
for p in pages.values():
    n_ = p["numbers"] or {}
    if n_.get("battery_kwh") and n_.get("battery_usable_kwh"):
        ratios.append(n_["battery_usable_kwh"] / n_["battery_kwh"])
ratios.sort()
if ratios:
    print(f"usable/gross on {len(ratios)} car pages: min {ratios[0]:.3f} p10 {ratios[len(ratios)//10]:.3f} median {ratios[len(ratios)//2]:.3f} p90 {ratios[9*len(ratios)//10]:.3f} max {ratios[-1]:.3f}")
    print("  pages with usable == gross:", sum(1 for r in ratios if r >= 0.999))
def show_model(slug):
    vs = sorted(by_model.get(slug, []), key=lambda v: ((v["numbers"] or {}).get("year_from") or 0, v["spec_key"]))
    print(f"--- {slug}: {len(vs)} variants")
    for v in vs:
        n_ = v["numbers"] or {}
        pg = pages.get(v["spec_key"].split(":", 1)[1], {})
        pn = pg.get("numbers") or {}
        print(f"   {v['spec_key'].split(':')[1]:>5} {v.get('model')!s:<50} usable {n_.get('battery_usable_kwh')!s:>5} gross {pn.get('battery_kwh')!s:>5} kW {pn.get('power_kw')!s:>4} "
              f"from {n_.get('year_from')} since {n_.get('on_sale_since')} until {n_.get('on_sale_until')} on_sale {n_.get('on_sale')} seats {n_.get('seats')} drive {pn.get('drive')}")
for slug in ("hyundai/kona-electric", "hyundai/ioniq-5", "kia/ev6", "kia/ev3", "kia/ev9", "volkswagen/id3", "tesla/model-y", "skoda/enyaq", "mg/mg4", "renault/megane-etech-electric", "bmw/ix1", "cupra/born", "hyundai/inster", "peugeot/e-208", "nissan/leaf", "polestar/2"):
    show_model(slug)
print("models with same-kWh variants (first 40):", same_kwh_models[:40])

# ---------------------------------------------------------------- C. which variant each car got, and does its year cover the car
sec("C. CARS -> EV Database variant (published cars.json): year coverage")
ev_by_url = {v.get("source_url"): v for v in ev}
cov = collections.Counter()
bad = []
for c in cars_pub:
    u = c.get("evdb_url")
    if not u:
        cov["no variant"] += 1
        continue
    v = ev_by_url.get(u)
    if not v:
        cov["url not in index"] += 1
        continue
    n_ = v["numbers"] or {}
    y = c.get("model_year")
    start = n_.get("year_from") or 0
    until = int(str(n_["on_sale_until"])[:4]) if n_.get("on_sale_until") else None
    if not y:
        cov["car has no year"] += 1
    elif start <= y and (until is None or until >= y):
        cov["covers"] += 1
    else:
        cov["does not cover"] += 1
        bad.append((c["id"], c.get("make"), c.get("model"), c.get("trim"), y, c.get("battery_kwh"), v.get("model"), start, until, n_.get("battery_usable_kwh")))
print(cov)
print("cars tied to a variant whose years do not cover the car's year (first 40):")
for b in bad[:40]:
    print("   ", b)
# how many cars are on a discontinued variant while an on-sale variant of the same model exists with usable within the car's gross?
sec("C2. cars on a discontinued variant while an on-sale one of the same model fits the battery")
n_disc = 0; ex = []
slug_of = {}
for c in cars_pub:
    u = c.get("evdb_url"); v = ev_by_url.get(u) if u else None
    if not v:
        continue
    n_ = v["numbers"] or {}
    if n_.get("on_sale") is True:
        continue
    m = model_of(v.get("make") or "", v.get("model") or "", catalogue)
    alts = [a for a in by_model.get(m["slug"], []) if (a["numbers"] or {}).get("on_sale") is True and _battery_fit(c.get("battery_kwh"), (a["numbers"] or {}).get("battery_usable_kwh")) is not None]
    if alts:
        n_disc += 1
        if len(ex) < 25:
            ex.append((c["id"], c.get("make"), c.get("model"), c.get("trim"), c.get("model_year"), c.get("battery_kwh"), "->", v.get("model"), n_.get("battery_usable_kwh"), "| on sale:", [(a.get("model"), (a["numbers"] or {}).get("battery_usable_kwh")) for a in alts]))
print("count:", n_disc)
for e in ex:
    print("   ", e)

# ---------------------------------------------------------------- D. battery disagreements across sources
sec("D. BATTERY: Carwow spec gross vs maker tables vs EV Database gross")
kia = [json.loads(r["payload"]) for r in con.execute("select payload from specs where source='kia_specs'")]
hy = [json.loads(r["payload"]) for r in con.execute("select payload from specs where source='hyundai_specs'")]
print("kia_specs batteries by model:", sorted({(p.get("model"), (p.get("numbers") or {}).get("battery_kwh")) for p in kia}))
print("hyundai_specs batteries by model:", sorted({(p.get("model"), tuple(p.get("batteries") or []), tuple(pt.get("battery_kwh") for pt in p.get("powertrains") or [])) for p in hy}))
cw_batt = collections.defaultdict(set)
for p in specs_cw:
    b = (p.get("numbers") or {}).get("battery_kwh")
    if b:
        cw_batt[(p["make"].lower(), p["model"].lower())].add(float(b))
for k in sorted(cw_batt):
    if k[0] in ("kia", "hyundai"):
        print("  carwow", k, sorted(cw_batt[k]))
# EV Database gross vs Carwow battery for cars whose variant page has gross
sec("D2. for cars tied to a variant with a car page: Carwow battery vs EV Database gross and usable")
dist = collections.Counter(); ex = []
for c in cars_pub:
    u = c.get("evdb_url"); v = ev_by_url.get(u) if u else None
    if not v or not c.get("battery_kwh"):
        continue
    pg = pages.get(v["spec_key"].split(":", 1)[1])
    if not pg:
        continue
    g = (pg["numbers"] or {}).get("battery_kwh"); us = (pg["numbers"] or {}).get("battery_usable_kwh")
    b = float(c["battery_kwh"])
    if g and abs(g - b) <= 0.6:
        dist["carwow = evdb gross"] += 1
    elif us and abs(us - b) <= 0.6:
        dist["carwow = evdb usable"] += 1
        if len(ex) < 12: ex.append((c.get("make"), c.get("model"), c.get("trim"), b, "gross", g, "usable", us))
    else:
        dist["neither"] += 1
        if len(ex) < 24: ex.append((c.get("make"), c.get("model"), c.get("trim"), b, "gross", g, "usable", us))
print(dist)
for e in ex: print("   ", e)
# Carwow's own battery vs the maker's figure for the same trim, Kia/Hyundai
sec("D3. broker text kWh vs Carwow derivative kWh (resolved rows)")
rows = con.execute("select source, source_key, car_id, label, method from trim_map where status='auto' and source in ('ncd','leaseloco','cinch-new','rrg','kia-dealer')").fetchall()
cars_by_id = {c["id"]: c for c in cars_pub}
d_ = collections.Counter(); ex = []
for r in rows:
    m = KWH.search(r["label"] or "")
    c = cars_by_id.get(r["car_id"])
    if not m or not c or not c.get("battery_kwh"):
        d_["n/a"] += 1; continue
    t, b = float(m.group(1)), float(c["battery_kwh"])
    if abs(t - b) <= 0.6: d_["same"] += 1
    elif abs(t - b) <= 3: d_["within 3"] += 1; ex.append((r["source"], r["label"], b))
    else: d_["further"] += 1; ex.append((r["source"], r["label"], b))
print(d_)
for e in ex[:15]: print("   ", e)

# ---------------------------------------------------------------- E. used listings
sec("E. USED LISTINGS: what the text names, and what they joined")
ul = [dict(r, p=json.loads(r["payload"])) for r in con.execute("select * from used_listings")]
by_src = collections.defaultdict(collections.Counter)
for l in ul:
    s = l["source"]; p = l["p"]; t = p.get("derivative") or ""
    c = by_src[s]
    c["listings"] += 1
    c["present"] += int(l["present"])
    c["has derivative text"] += bool(t)
    c["text has kWh"] += bool(KWH.search(t))
    c["text has kW"] += bool(KW.search(t))
    c["text has bracket"] += bool(BR.search(t))
    c["has year"] += bool(l["year"])
    c["has vrm"] += bool(p.get("vrm"))
    c["matched to a car"] += bool(l["car_id"])
    c["has cap in car_ref"] += ((p.get("car_ref") or {}).get("source") == "carwow-cap")
for s, c in by_src.items():
    print("---", s, dict(c))
print("sample used derivative texts per source:")
for s in by_src:
    ts = [l["p"].get("derivative") for l in ul if l["source"] == s and l["p"].get("derivative")]
    print("  ", s, ts[:8])
# wrong joins: listing year earlier than its car's on-sale year (version_date) or model_year
sec("E2. used listings matched to a car whose version date is after the listing's registration year")
wrong = []; checked = 0
for l in ul:
    c = cars_by_id.get(l["car_id"])
    if not c or not l["year"]:
        continue
    checked += 1
    since = str(c.get("on_sale_since") or "")[:4]
    if since.isdigit() and l["year"] < int(since):
        wrong.append((l["source"], l["p"].get("derivative"), l["year"], "->", c["id"], c.get("trim"), c.get("model_year"), "on_sale_since", c.get("on_sale_since")))
print("checked:", checked, " listing year < car's on_sale_since:", len(wrong))
for w in wrong[:20]: print("   ", w)
# published used_key: how many spans have one; via car_id vs via text
sec("E3. published used_spans: used_key coverage")
uk = collections.Counter()
for u in used_spans:
    uk["spans"] += 1
    uk["with used_key"] += bool(u.get("used_key"))
    uk["with car_id"] += bool(u.get("car_id"))
print(uk)
# the used-key assignment by text: how many listings could fit several trims (ties) -> None
sec("E4. how a used listing's text fits the model's trims: unique / tie / none (used_key_for_text replica)")
from pipeline.services.snapshot import used_key_for_text
by_model_cars = collections.defaultdict(list)
for c in cars_pub:
    if c.get("used_key"):
        by_model_cars[c["model_key"]].append(c)
fit = collections.Counter(); ties = []
for l in ul:
    if l["car_id"] or not l["p"].get("derivative"):
        continue
    model = f"{(l['make_slug'] or '').lower()}/{l['model_slug'] or ''}"
    cars_m = by_model_cars.get(model, [])
    if not cars_m:
        fit["model has no cars with a used_key"] += 1; continue
    k = used_key_for_text(l["p"]["derivative"], cars_m, l["year"])
    if k: fit["one trim+battery"] += 1
    else:
        fit["none or tie"] += 1
        if len(ties) < 15: ties.append((l["source"], model, l["p"]["derivative"], l["year"]))
print(fit)
for t in ties: print("   ", t)

# ---------------------------------------------------------------- F. brokers
sec("F. BROKER TEXT and how it resolved")
for src in ("ncd", "leaseloco", "rrg", "cinch-new", "kia-dealer", "carwow", "hyundai-cap"):
    rows = con.execute("select status, method, label, evidence from trim_map where source=?", (src,)).fetchall()
    if not rows: continue
    c = collections.Counter()
    for r in rows:
        c[f"{r['status']}/{r['method']}"] += 1
        t = r["label"] or ""
        c["text kW"] += bool(KW.search(t)); c["text kWh"] += bool(KWH.search(t)); c["text bracket"] += bool(BR.search(t)); c["text seats"] += bool(SEAT.search(t))
    print("---", src, len(rows), dict(c))
sec("F2. conflict reasons")
reasons = collections.Counter()
for r in con.execute("select source, label, evidence from trim_map where status='conflict'"):
    ev_ = json.loads(r["evidence"] or "{}")
    reasons[(r["source"], ev_.get("reason") or "pack vs 3+ prices", len(ev_.get("prices") or []))] += 1
for k, n in reasons.most_common(20): print("   ", k, n)
sec("F3. a few conflicts in full")
for r in con.execute("select source, label, evidence from trim_map where status='conflict' order by source, label limit 8"):
    print("   ", r["source"], r["label"], r["evidence"][:300])
sec("F4. unmapped rows (nothing fits) by source, examples")
for r in con.execute("select source, count(*) n from trim_map where status='unmapped' group by 1"):
    print("   ", dict(r))
for r in con.execute("select source, label, evidence from trim_map where status='unmapped' order by source, label limit 25"):
    print("   ", r["source"], "|", r["label"], "|", (r["evidence"] or "")[:160])

# ---------------------------------------------------------------- G. combustion
sec("G. combustion-named derivatives")
for r in con.execute("select source, label from trim_map where method='combustion'"):
    print("   ", r["source"], r["label"])

# ---------------------------------------------------------------- H. cars with same display name
sec("H. cars.json: cars on sale, same displayed name counts")
on_sale = sum(1 for c in cars_pub if c.get("on_sale"))
names = collections.Counter((c.get("make"), c.get("model"), c.get("trim")) for c in cars_pub if c.get("on_sale"))
print("cars:", len(cars_pub), " on sale:", on_sale, " on-sale cars sharing make/model/trim with another:", sum(n for n in names.values() if n > 1), " such name groups:", sum(1 for n in names.values() if n > 1))
print("cars with on_sale_since:", sum(1 for c in cars_pub if c.get("on_sale_since")), " with evdb_url:", sum(1 for c in cars_pub if c.get("evdb_url")), " with battery_usable_kwh:", sum(1 for c in cars_pub if c.get("battery_usable_kwh")), " with power_kw:", sum(1 for c in cars_pub if c.get("power_kw")), " with drive:", sum(1 for c in cars_pub if c.get("drive")))
