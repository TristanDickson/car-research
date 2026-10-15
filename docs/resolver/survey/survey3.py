import sqlite3, json, collections, re, sys, unicodedata
sys.path.insert(0, "C:/Users/Tristan/car-research")
from pipeline.services.facts import model_of
con = sqlite3.connect("file:C:/Users/Tristan/car-research-nightly/data/car-research.sqlite?mode=ro", uri=True); con.row_factory = sqlite3.Row
PUB = "C:/Users/Tristan/AppData/Local/Temp/claude/c--Users-Tristan-car-research/51d7059d-bf41-4af8-8848-833f98166772/scratchpad/pubdata/"
cars_pub = json.load(open(PUB + "cars.json", encoding="utf-8"))
catalogue = [dict(r) for r in con.execute("select slug, make, model, make_name, model_name from models where electric=1")]
ev = [json.loads(r["payload"]) for r in con.execute("select payload from specs where source='evdb'")]
def strip(s): return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
print("=== 1. unfiled cards: filed once accents are stripped from the make?")
c = collections.Counter(); ex = collections.Counter()
for v in ev:
    if model_of(v.get("make") or "", v.get("model") or "", catalogue): continue
    m2 = model_of(strip(v.get("make")), strip(v.get("model")), catalogue)
    c["filed after stripping accents" if m2 else "still unfiled"] += 1
    if not m2: ex[(v.get("make"), (v.get("model") or "").split(" (")[0][:28])] += 1
print(c); print("still unfiled, top:", ex.most_common(25))
print("=== 2. the same-name twin pair")
for r in con.execute("select cap_id, name, trim, engine, rrp, version_date from derivatives where cap_id in ('110379','110402','109400','109434')"): print("   ", dict(r))
print("same CAP name on two registry rows (any model):", con.execute("select count(*) from (select make_slug, model_slug, name from derivatives group by 1,2,3 having count(*)>1)").fetchone()[0])
for r in con.execute("select make_slug, model_slug, name, count(*) n, group_concat(cap_id||' £'||rrp||' '||version_date, ' | ') g from derivatives group by 1,2,3 having n>1 limit 12"): print("   ", dict(r))
print("=== 3. used listings whose text kWh matches no derivative of the model within 1.5 kWh (old generations)")
KWH = re.compile(r"(\d+(?:\.\d+)?)\s*kwh", re.I)
kwhs = collections.defaultdict(set)
for cc in cars_pub:
    k = cc.get("battery_kwh")
    if not k:
        m = KWH.search(cc.get("trim") or "")
        k = float(m.group(1)) if m else None
    if k: kwhs[cc["model_key"]].add(float(k))
tot = collections.Counter(); models = collections.Counter()
for r in con.execute("select make_slug, model_slug, year, present, json_extract(payload,'$.derivative') d from used_listings"):
    m = KWH.search(r["d"] or "")
    if not m: tot["no kWh in text"] += 1; continue
    k = float(m.group(1)); mk = f"{(r['make_slug'] or '').lower()}/{r['model_slug'] or ''}"
    if not kwhs.get(mk): tot["model has no car with a kWh"] += 1
    elif any(abs(k - x) <= 1.5 for x in kwhs[mk]): tot["a current derivative has this kWh"] += 1
    else: tot["no derivative has this kWh: an earlier generation"] += 1; models[(mk, k)] += 1
print(tot); print("top (model, kWh):", models.most_common(20))
print("=== 4. filed EV Database variants on sale vs discontinued, and used listings by the years they fall in")
filed = [v for v in ev if model_of(v.get("make") or "", v.get("model") or "", catalogue)]
print("filed:", len(filed), " on sale:", sum(1 for v in filed if (v['numbers'] or {}).get('on_sale') is True), " discontinued:", sum(1 for v in filed if (v['numbers'] or {}).get('on_sale') is False))
print("=== 5. records per source and kind (records table, distinct keys)")
for r in con.execute("select source, kind, count(distinct record_key) n from records group by 1,2 order by 1,2"): print("   ", r["source"], r["kind"], r["n"])
