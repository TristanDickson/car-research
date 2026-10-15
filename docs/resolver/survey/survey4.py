import sqlite3, json, collections
con = sqlite3.connect("file:C:/Users/Tristan/car-research-nightly/data/car-research.sqlite?mode=ro", uri=True); con.row_factory = sqlite3.Row
print("=== registry keys in records but not in derivatives")
r = con.execute("""select count(distinct record_key) from records where source='carwow_model' and kind='derivative'
                   and record_key not in (select cap_id from derivatives)""").fetchone()[0]
print("missing:", r)
for x in con.execute("""select record_key, origin, first_seen_at, last_seen_at, substr(row,1,160) row from records where source='carwow_model' and kind='derivative'
                        and record_key not in (select cap_id from derivatives) order by last_seen_at desc limit 5"""): print("   ", dict(x))
print("by origin:", [dict(x) for x in con.execute("""select origin, count(distinct record_key) n from records where source='carwow_model' and kind='derivative'
                        and record_key not in (select cap_id from derivatives) group by 1""")])
print("last seen year:", [dict(x) for x in con.execute("""select substr(max(last_seen_at),1,7) m, count(*) n from (select record_key, max(last_seen_at) last_seen_at from records where source='carwow_model' and kind='derivative'
                        and record_key not in (select cap_id from derivatives) group by 1) group by 1""")])
# are those keys among the cars (as stubs)?
cars = {r[0] for r in con.execute("select id from cars")}
missing = [r[0] for r in con.execute("""select distinct record_key from records where source='carwow_model' and kind='derivative' and record_key not in (select cap_id from derivatives)""")]
print("of the missing keys, cars exist for:", sum(1 for k in missing if f"carwow-cap:{k}" in cars), "of", len(missing))
print("=== one CAP name under two model slugs (body styles)")
rows = con.execute("""select a.make_slug, a.model_slug ma, b.model_slug mb, a.name, a.rrp ra, b.rrp rb from derivatives a join derivatives b
                      on a.make_slug=b.make_slug and a.name=b.name and a.model_slug<b.model_slug""").fetchall()
print("pairs:", len(rows), " model pairs:", collections.Counter((r['ma'], r['mb']) for r in rows).most_common(12))
print("same RRP too:", sum(1 for r in rows if r['ra'] == r['rb']))
