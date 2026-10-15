"""The six known failures, by id, in the build database and the snapshot."""
import sqlite3, json, collections, re, sys
sys.path.insert(0, "C:/Users/Tristan/car-research")
from pipeline.services.facts import model_of, pick_variant, _battery_fit
con = sqlite3.connect("file:C:/Users/Tristan/car-research-nightly/data/car-research.sqlite?mode=ro", uri=True)
con.row_factory = sqlite3.Row
PUB = "C:/Users/Tristan/AppData/Local/Temp/claude/c--Users-Tristan-car-research/51d7059d-bf41-4af8-8848-833f98166772/scratchpad/pubdata/"
cars_pub = json.load(open(PUB + "cars.json", encoding="utf-8"))
used_spans = json.load(open(PUB + "used_spans.json", encoding="utf-8"))
KWH = re.compile(r"(\d+(?:\.\d+)?)\s*kwh", re.I)

def sec(t): print("\n" + "=" * 8 + " " + t)

sec("1. KONA ELECTRIC: cars, their battery, model year, and the EV Database variant they got")
kona = [c for c in cars_pub if c.get("model_key") == "hyundai/kona-electric"]
print("Kona cars:", len(kona), " on sale:", sum(1 for c in kona if c.get("on_sale")))
cnt = collections.Counter((c.get("battery_kwh"), c.get("model_year"), c.get("evdb_url")) for c in kona)
for k, n in sorted(cnt.items(), key=lambda kv: str(kv[0])): print("   ", n, k)
for r in con.execute("select spec_key, payload from specs where source='evdb' and make='Hyundai' and model like 'Kona%'"):
    p = json.loads(r["payload"]); n = p["numbers"]
    print("   evdb", r["spec_key"], p["model"], "usable", n.get("battery_usable_kwh"), "from", n.get("year_from"), "since", n.get("on_sale_since"), "until", n.get("on_sale_until"), "on_sale", n.get("on_sale"))
    print("      fit vs 65.4:", _battery_fit(65.4, n.get("battery_usable_kwh")), " vs 48.4:", _battery_fit(48.4, n.get("battery_usable_kwh")))
for r in con.execute("select spec_key, payload from specs where source='evdb_cars' and make='Hyundai' and model like 'Kona%'"):
    p = json.loads(r["payload"]); n = p["numbers"]
    print("   evdb_cars", r["spec_key"], p["model"], "gross", n.get("battery_kwh"), "usable", n.get("battery_usable_kwh"), "kW", n.get("power_kw"), "since", n.get("on_sale_since"), "until", n.get("on_sale_until"))
print("Kona registry names:")
for r in con.execute("select cap_id, name, rrp, version_date from derivatives where model_slug='kona-electric' order by name, version_date"):
    print("   ", dict(r))
print("Kona carwow spec batteries/engines:")
for r in con.execute("select cap_id, trim, variant, version_date, json_extract(payload,'$.numbers.battery_kwh') b, json_extract(payload,'$.numbers.power_bhp') hp from specs where source='carwow_specs' and model='Kona Electric' order by variant, trim"):
    print("   ", dict(r))
print("Hyundai spec guide Kona rows:")
for r in con.execute("select trim, json_extract(payload,'$.batteries') b, json_extract(payload,'$.powertrains') pt from specs where source='hyundai_specs' and model like 'Kona%'"):
    print("   ", r["trim"], r["b"], (r["pt"] or "")[:300])

sec("2. The 2021 Kona 'Ultimate 64kWh' used listing(s)")
for r in con.execute("select listing_key, source, year, price_gbp, mileage, car_id, json_extract(payload,'$.derivative') d from used_listings where model_slug='kona-electric' and json_extract(payload,'$.derivative') like '%Ultimate%' and year <= 2023 order by year"):
    print("   ", dict(r))
print("published used_key of those spans:")
keys = {u["key"]: u for u in used_spans}
for r in con.execute("select listing_key from used_listings where model_slug='kona-electric' and json_extract(payload,'$.derivative') like '%Ultimate%' and year <= 2023"):
    u = keys.get(r["listing_key"]); print("   ", r["listing_key"], u and u.get("used_key"), u and u.get("year"))
print("Kona used listings by year x text kWh:")
c = collections.Counter()
for r in con.execute("select year, json_extract(payload,'$.derivative') d from used_listings where model_slug='kona-electric'"):
    m = KWH.search(r["d"] or ""); c[(r["year"], m.group(1) if m else None)] += 1
for k, n in sorted(c.items(), key=lambda kv: str(kv[0])): print("   ", k, n)
print("Kona cars' used_key and on_sale_since:")
for k, n in collections.Counter((c_.get("used_key"), c_.get("on_sale_since")) for c_ in kona).items(): print("   ", n, k)

sec("3. Petrol derivatives (combustion) and the Astra battery claim")
for r in con.execute("select source, source_key, label, status, method from trim_map where method='combustion' or label like '%Turbo 130%' or label like '%EcoBoost%' or label like '%Mild Hybrid%' or label like '%Hybrid EV%'"):
    print("   ", dict(r))
for c_ in cars_pub:
    if re.search(r"turbo 130|ecoboost|mild hybrid|hybrid ev", (c_.get("trim") or ""), re.I):
        print("   STILL A CAR:", c_["id"], c_.get("make"), c_.get("model"), c_.get("trim"), c_.get("battery_kwh"))

sec("4. Gross vs usable: EV6, Ioniq 5, Kona across sources")
for mk, mo in (("Kia", "EV6"), ("Hyundai", "Ioniq 5"), ("Hyundai", "Kona Electric"), ("Kia", "EV3"), ("Hyundai", "Inster")):
    print("---", mk, mo)
    print("   carwow:", sorted({(r[0], r[1]) for r in con.execute("select json_extract(payload,'$.numbers.battery_kwh'), variant from specs where source='carwow_specs' and make=? and model=?", (mk, mo))}, key=str))
    print("   maker:", sorted({(r[0], r[1], r[2]) for r in con.execute("select trim, json_extract(payload,'$.numbers.battery_kwh'), json_extract(payload,'$.batteries') from specs where source in ('kia_specs','hyundai_specs') and make=? and model like ?", (mk, mo + "%"))}, key=str))
    print("   evdb:", sorted({(json.loads(r[0])["model"], json.loads(r[0])["numbers"].get("battery_usable_kwh"), json.loads(r[0])["numbers"].get("on_sale_since"), json.loads(r[0])["numbers"].get("on_sale")) for r in con.execute("select payload from specs where source='evdb' and make=? and model like ?", (mk, mo + "%"))}, key=str))
    print("   evdb_cars gross:", sorted({(json.loads(r[0])["model"], json.loads(r[0])["numbers"].get("battery_kwh"), json.loads(r[0])["numbers"].get("battery_usable_kwh")) for r in con.execute("select payload from specs where source='evdb_cars' and make=? and model like ?", (mk, mo + "%"))}, key=str))
    print("   broker text kWh:", sorted({r[0] for r in con.execute("select label from trim_map where source in ('ncd','leaseloco') and lower(label) like ?", (f"%{mo.lower()}%",))}, key=str)[:6])
    print("   used text kWh:", collections.Counter(KWH.search(r[0] or "") and KWH.search(r[0]).group(1) for r in con.execute("select json_extract(payload,'$.derivative') from used_listings where make=? and model_slug like ?", (mk, mo.lower().replace(' ', '-') + "%"))).most_common(6))

sec("5. Twins told apart only by RRP; [No Heat Pump] brackets")
for r in con.execute("select make_slug, model_slug, trim, engine, group_concat(cap_id || ' ' || name || ' £' || coalesce(rrp,'') || ' ' || coalesce(version_date,''), ' || ') g, count(*) n from derivatives group by 1,2,3,4 having n > 2 order by n desc limit 12"):
    print("   ", r["make_slug"], r["model_slug"], r["trim"], "|", r["engine"], "|", r["n"])
    for x in r["g"].split(" || "): print("        ", x)
print("names with '[No ' brackets:", con.execute("select count(*) from derivatives where name like '%[No %'").fetchone()[0])
for r in con.execute("select cap_id, make_slug, model_slug, name, rrp from derivatives where name like '%[No %' limit 10"): print("   ", dict(r))
print("broker labels with '[No ':", con.execute("select count(*) from trim_map where label like '%[No %'").fetchone()[0])

sec("6. Broker quirks: NCD KIA prefix, RRG Air at GT-Line price, Halliwell Jones")
for r in con.execute("select source, label, status, method, car_id, substr(evidence,1,200) e from trim_map where source='ncd' and label like 'KIA%' limit 6"): print("   ", dict(r))
for r in con.execute("select source, label, status, method, car_id, substr(evidence,1,300) e from trim_map where source='rrg'"): print("   ", dict(r))
for r in con.execute("select source, label, status, method, car_id, substr(evidence,1,200) e from trim_map where source='kia-dealer'"): print("   ", dict(r))

sec("7. Owner decisions: trim_map.json rows")
seed = json.load(open("C:/Users/Tristan/car-research/data/seed/trim_map.json", encoding="utf-8"))
rows = seed if isinstance(seed, list) else seed.get("trim_map") or seed.get("rows") or list(seed.values())[0]
c = collections.Counter((r.get("source"), "car" if r.get("car_id") else r.get("status") or "ignored") for r in rows)
for k, n in sorted(c.items(), key=str): print("   ", k, n)
print("   examples:", [ {k: r.get(k) for k in ("source","source_key","car_id","status")} for r in rows[:4]])
cars_seed = json.load(open("C:/Users/Tristan/car-research/data/seed/cars.json", encoding="utf-8"))
cl = cars_seed if isinstance(cars_seed, list) else cars_seed.get("cars") or list(cars_seed.values())[0]
print("   owner cars:", len(cl), [(x.get("id"), x.get("cap_id"), x.get("used"), x.get("battery_kwh"), x.get("model_year")) for x in cl])

sec("8. hyundai_offers CAP codes vs Carwow CAP ids")
for r in con.execute("select source, source_key, label, status, method, car_id from trim_map where source='hyundai-cap'"): print("   ", dict(r))
