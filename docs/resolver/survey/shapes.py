import sqlite3, json, collections
con = sqlite3.connect("file:C:/Users/Tristan/car-research-nightly/data/car-research.sqlite?mode=ro", uri=True)
con.row_factory = sqlite3.Row

def keys_of(d, prefix=""):
    out = set()
    for k, v in d.items():
        out.add(prefix + k)
        if isinstance(v, dict) and k in ("numbers", "car_ref", "flags", "stub"):
            out |= keys_of(v, prefix + k + ".")
    return out

print("=== specs by source: rows, key coverage")
for src, in con.execute("select distinct source from specs order by 1"):
    rows = [json.loads(r["payload"]) for r in con.execute("select payload from specs where source=?", (src,))]
    cnt = collections.Counter()
    for p in rows:
        for k in keys_of(p):
            v = p
            for part in k.split("."):
                v = v.get(part) if isinstance(v, dict) else None
            if v not in (None, "", [], {}):
                cnt[k] += 1
    print(f"--- {src}: {len(rows)} rows")
    for k, n in sorted(cnt.items()):
        print(f"    {k}: {n}")

print("\n=== one derivative payload")
r = con.execute("select payload from derivatives where name like '%[%' limit 1").fetchone()
print(json.dumps(json.loads(r[0]), indent=1)[:1500])

print("\n=== offer records: car_ref keys by source (from records table, kind=offer)")
cnt = collections.defaultdict(collections.Counter)
n_by = collections.Counter()
for r in con.execute("select source, row from records where kind='offer'"):
    ref = (json.loads(r["row"]).get("car_ref") or {})
    n_by[r["source"]] += 1
    for k, v in ref.items():
        if v not in (None, "", [], {}):
            cnt[r["source"]][k] += 1
    cnt[r["source"]]["ref.source=" + str(ref.get("source"))] += 1
for s in sorted(n_by):
    print(f"--- {s}: {n_by[s]} record spans")
    for k, n in sorted(cnt[s].items()):
        print(f"    {k}: {n}")

print("\n=== used_listings: payload keys by source")
cnt = collections.defaultdict(collections.Counter)
n_by = collections.Counter()
for r in con.execute("select source, payload from used_listings"):
    p = json.loads(r["payload"])
    n_by[r["source"]] += 1
    for k in keys_of(p):
        v = p
        for part in k.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        if v not in (None, "", [], {}):
            cnt[r["source"]][k] += 1
    cnt[r["source"]]["ref.source=" + str((p.get("car_ref") or {}).get("source"))] += 1
for s in sorted(n_by):
    print(f"--- {s}: {n_by[s]} listings")
    for k, n in sorted(cnt[s].items()):
        print(f"    {k}: {n}")

print("\n=== sample used listing per source")
for src, in con.execute("select distinct source from used_listings order by 1"):
    r = con.execute("select payload from used_listings where source=? and present=1 order by listing_key limit 1", (src,)).fetchone()
    p = json.loads(r[0])
    p.pop("finance", None); p.pop("tags", None); p.pop("badges", None)
    print(f"--- {src}: {json.dumps(p, ensure_ascii=False)[:900]}")

print("\n=== sample offer car_ref per source")
for src, in con.execute("select distinct source from records where kind='offer' order by 1"):
    r = con.execute("select row from records where kind='offer' and source=? order by record_key limit 1", (src,)).fetchone()
    p = json.loads(r[0])
    print(f"--- {src}: car_ref={json.dumps(p.get('car_ref'), ensure_ascii=False)[:600]}")

print("\n=== trim_map: status x method")
for r in con.execute("select status, method, count(*) n from trim_map group by 1,2 order by 1,2"):
    print(dict(r))

print("\n=== cars: source_kind counts, battery known")
for r in con.execute("select source, count(*) n, sum(battery_kwh is not null) with_kwh, sum(model_year is not null) with_year from cars group by 1"):
    print(dict(r))
