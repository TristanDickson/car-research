"""Compare two snapshots: python scripts/compare_snapshots.py <new folder> <old folder | git:<ref>>

`git:origin/main` reads the old snapshot from that commit's web/public/data, byte for byte.

Prints the manifest counts side by side, which cars exist in only one, which car fields
differ and on how many cars, and every offer's price spans classified as identical,
identical once touching spans of the same price are joined, on a different car, only in
one snapshot, or with different prices or dates. The nightly job runs it against main's
snapshot while the laptop and the GitHub scrape run side by side.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

PRICE = ("vehicle_price", "monthly_payment", "apr", "gfv", "customer_deposit", "manufacturer_contribution", "num_payments",
         "term_months", "initial_rental", "monthly_rental", "num_rentals", "fees_gbp", "annual_mileage")


def load(d, f: str):
    if isinstance(d, str) and d.startswith("git:"):
        out = subprocess.run(["git", "show", f"{d[4:]}:web/public/data/{f}"], capture_output=True, check=True).stdout
        return json.loads(out.decode("utf-8"))
    return json.loads((Path(d) / f).read_text(encoding="utf-8"))


def joined(spans: list[dict]) -> list[tuple]:
    out: list[dict] = []
    for s in sorted(spans, key=lambda s: s["from"]):
        fp = json.dumps({k: s["deal"].get(k) for k in PRICE}, sort_keys=True)
        if out and out[-1]["present"] and s["present"] and out[-1]["fp"] == fp and s["from"] <= out[-1]["to"]:
            out[-1]["to"] = max(out[-1]["to"], s["to"])
            continue
        out.append({"from": s["from"], "to": s["to"], "fp": fp, "present": s["present"], "car": s["car_id"]})
    return [(s["from"], s["to"], s["fp"], s["car"]) for s in out]


def compare(new, old) -> list[str]:
    lines = []
    a, b = load(new, "manifest.json")["counts"], load(old, "manifest.json")["counts"]
    lines.append(f"{'count':22s} {'new':>8} {'old':>8}")
    for k in sorted(set(a) | set(b)):
        lines.append(f"{k:22s} {a.get(k)!s:>8} {b.get(k)!s:>8}" + ("" if a.get(k) == b.get(k) else "   differs"))
    cn = {c["id"]: c for c in load(new, "cars.json")}
    co = {c["id"]: c for c in load(old, "cars.json")}
    lines.append(f"cars only in new: {len(set(cn) - set(co))}  only in old: {len(set(co) - set(cn))}")
    for i in sorted(set(cn) ^ set(co))[:10]:
        lines.append(f"  {'new' if i in cn else 'old'}: {i}")
    diff = Counter()
    for i in set(cn) & set(co):
        for k in set(cn[i]) | set(co[i]):
            if cn[i].get(k) != co[i].get(k):
                diff[k] += 1
    lines.append("car fields that differ (field: cars): " + (", ".join(f"{k}: {n}" for k, n in diff.most_common(20)) or "none"))
    gn, go = defaultdict(list), defaultdict(list)
    for s in load(new, "sightings.json"):
        gn[s["key"]].append(s)
    for s in load(old, "sightings.json"):
        go[s["key"]].append(s)
    cls = Counter()
    for k in set(gn) | set(go):
        if k not in gn:
            cls["only in old"] += 1
        elif k not in go:
            cls["only in new"] += 1
        else:
            ja, jb = joined(gn[k]), joined(go[k])
            if [x[:3] for x in ja] != [x[:3] for x in jb]:
                cls["prices or dates differ"] += 1
            elif ja != jb:
                cls["same prices and dates, different car"] += 1
            elif len(gn[k]) != len(go[k]):
                cls["same once touching equal spans are joined"] += 1
            else:
                cls["identical"] += 1
    lines.append("offers: " + ", ".join(f"{c} {n}" for c, n in cls.most_common()))
    return lines


if __name__ == "__main__":
    print("\n".join(compare(sys.argv[1], sys.argv[2])))
