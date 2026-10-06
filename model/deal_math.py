#!/usr/bin/env python3
"""Normalise PCP, PCH and cash deals onto one footing.

Reads data/seed/deals.json and data/seed/cars.json. For each deal it computes:

  PCP  total paid if handed back / if bought, cost of credit, implied APR (as a check on the
       stated APR), monthly at 0% with the same GFV, GFV as % of list and of price, effective
       monthly (hand back, no equity), and, where a cash benchmark exists for the same car:
       acquisition-price penalty, funding premium if bought, and the effective annual rate of
       taking this finance deal instead of that cash price.
  PCH  total rentals + fees and effective monthly.
  cash price only; the lowest cash price per car is the benchmark.

If a PCP's monthly_payment is null it is solved from apr, amount_of_credit and gfv.
If amount_of_credit is null it is back-solved as the PV of the payments at the stated APR.

Usage:
  python3 model/deal_math.py            # markdown tables
  python3 model/deal_math.py --json     # machine-readable, for the export step

Conventions: payments at months 1..n, balloon at month n+1 (UK 37-month PCP with 36 payments).
APR is an effective annual rate, so the monthly rate is (1+APR)^(1/12)-1. This reproduces
Carwow's figures to within pennies.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed"


def load(name):
    with open(SEED / name) as f:
        return json.load(f)


def monthly_rate(apr):
    return (1 + apr) ** (1 / 12) - 1


def annualise(r_m):
    return (1 + r_m) ** 12 - 1


def npv(flows, r):
    return sum(a / (1 + r) ** m for m, a in flows)


def irr_monthly(flows):
    """Bisection on monthly rate. flows = [(month, amount)], positive = money to you."""
    lo, hi = -0.5, 0.5
    f_lo, f_hi = npv(flows, lo), npv(flows, hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(flows, mid)
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def annuity_factor(r, n):
    if r == 0:
        return n
    return (1 - (1 + r) ** -n) / r


def solve_monthly(credit, apr, gfv, n):
    r = monthly_rate(apr)
    pv_balloon = gfv / (1 + r) ** (n + 1)
    return (credit - pv_balloon) / annuity_factor(r, n)


def pv_of_payments(monthly, apr, gfv, n, first=None):
    r = monthly_rate(apr)
    first = monthly if first is None else first
    pv = first / (1 + r) + sum(monthly / (1 + r) ** k for k in range(2, n + 1))
    return pv + gfv / (1 + r) ** (n + 1)


def payment_flows(d, n, m, first, gfv):
    flows = [(1, -first)] + [(k, -m) for k in range(2, n + 1)]
    flows.append((n + 1, -gfv))
    return flows


def pcp_metrics(d, best_cash):
    out = {"id": d["id"], "car_id": d["car_id"], "finance_type": "pcp", "status": d["status"]}
    n = d.get("num_payments")
    gfv = d.get("gfv") or 0.0
    dep = d.get("customer_deposit") or 0.0
    contrib = d.get("manufacturer_contribution") or 0.0
    fees = d.get("fees_gbp") or 0.0
    apr = d.get("apr")
    price = d.get("vehicle_price")
    credit = d.get("amount_of_credit")
    if credit is None and price is not None:
        credit = price - dep - contrib
    m = d.get("monthly_payment")
    derived = []

    if m is None:
        if None in (credit, apr, n):
            out["skipped"] = "no monthly and not enough to solve it"
            return out
        m = solve_monthly(credit, apr, gfv, n)
        derived.append("monthly_payment")
    first = d.get("first_payment") or m

    if credit is None:
        if apr is None or n is None:
            out["skipped"] = "no credit and no apr to back-solve"
            return out
        credit = pv_of_payments(m, apr, gfv, n, first)
        derived.append("amount_of_credit")
        if price is None:
            price = credit + dep + contrib
            derived.append("vehicle_price")

    paid_hand_back = dep + first + m * (n - 1) + fees
    paid_bought = paid_hand_back + gfv
    cost_of_credit = (paid_bought - dep) - credit  # total charge for credit, deposit excluded
    net_vs_own_cash = paid_bought - price  # vs this seller's own cash price
    r = irr_monthly([(0, credit)] + payment_flows(d, n, m, first, gfv))
    implied_apr = annualise(r) if r is not None else None
    zero_pct_monthly = (credit - gfv) / n
    term = d.get("term_months") or (n + 1)

    out.update({
        "list_price": d.get("list_price"),
        "vehicle_price": round(price, 2),
        "manufacturer_contribution": contrib,
        "customer_deposit": dep,
        "amount_of_credit": round(credit, 2),
        "num_payments": n,
        "term_months": term,
        "monthly_payment": round(m, 2),
        "apr_stated": apr,
        "apr_implied": round(implied_apr, 4) if implied_apr is not None else None,
        "gfv": gfv,
        "gfv_pct_of_list": round(gfv / d["list_price"], 3) if d.get("list_price") else None,
        "gfv_pct_of_price": round(gfv / price, 3) if price else None,
        "paid_if_handed_back": round(paid_hand_back, 2),
        "paid_if_bought": round(paid_bought, 2),
        "cost_of_credit": round(cost_of_credit, 2),
        "finance_vs_own_cash_price": round(net_vs_own_cash, 2),
        "effective_monthly_hand_back": round(paid_hand_back / term, 2),
        "monthly_at_0pct_same_gfv": round(zero_pct_monthly, 2),
        "interest_per_month": round(m - zero_pct_monthly, 2),
        "derived_fields": derived,
    })
    if best_cash:
        bc = best_cash["vehicle_price"]
        acq_penalty = (price - contrib) - bc
        funding_premium = paid_bought - bc
        r2 = irr_monthly([(0, bc - dep)] + payment_flows(d, n, m, first, gfv))
        out.update({
            "best_cash_price": bc,
            "best_cash_deal_id": best_cash["id"],
            "acquisition_penalty_vs_cash": round(acq_penalty, 2),
            "funding_premium_vs_cash": round(funding_premium, 2),
            "effective_rate_vs_cash": round(annualise(r2), 4) if r2 is not None else None,
        })
    return out


def pch_metrics(d):
    out = {"id": d["id"], "car_id": d["car_id"], "finance_type": "pch", "status": d["status"]}
    term = d.get("term_months")
    n = d.get("num_rentals")
    m = d.get("monthly_rental")
    init = d.get("initial_rental") or 0.0
    fees = d.get("fees_gbp") or 0.0
    if None in (term, n, m):
        out["skipped"] = "term or rental profile missing"
        return out
    total = d.get("total_stated") or (init + n * m + fees)
    out.update({
        "term_months": term,
        "initial_rental": init,
        "monthly_rental": m,
        "num_rentals": n,
        "fees": fees,
        "total_cost": round(total, 2),
        "effective_monthly": round(total / term, 2),
        "annual_mileage": d.get("annual_mileage"),
    })
    return out


def cash_metrics(d):
    return {
        "id": d["id"], "car_id": d["car_id"], "finance_type": "cash", "status": d["status"],
        "list_price": d.get("list_price"), "vehicle_price": d["vehicle_price"],
        "discount_vs_list": round(d["list_price"] - d["vehicle_price"], 2) if d.get("list_price") else None,
    }


def compute(deals):
    cash = [d for d in deals if d["finance_type"] == "cash" and d.get("vehicle_price")]
    best_cash = {}
    for d in cash:
        cur = best_cash.get(d["car_id"])
        if cur is None or d["vehicle_price"] < cur["vehicle_price"]:
            best_cash[d["car_id"]] = d
    results = []
    for d in deals:
        t = d["finance_type"]
        if t == "pcp":
            results.append(pcp_metrics(d, best_cash.get(d["car_id"])))
        elif t == "pch":
            results.append(pch_metrics(d))
        elif t == "cash":
            results.append(cash_metrics(d))
        else:
            results.append({"id": d["id"], "car_id": d["car_id"], "finance_type": t, "status": d["status"],
                            "apr": d.get("apr"), "manufacturer_contribution": d.get("manufacturer_contribution"),
                            "skipped": "campaign terms only"})
    return results


def gbp(x):
    return "" if x is None else f"£{x:,.0f}"


def pct(x):
    return "" if x is None else f"{x * 100:.1f}%"


def print_markdown(results, cars):
    name = {c["id"]: f'{c["make"]} {c["model"]} {c["trim"]}' for c in cars["cars"]}
    pcp = [r for r in results if r["finance_type"] == "pcp" and "skipped" not in r]
    pch = [r for r in results if r["finance_type"] == "pch" and "skipped" not in r]
    cash = [r for r in results if r["finance_type"] == "cash"]
    skipped = [r for r in results if "skipped" in r]

    print("## PCP deals, normalised\n")
    print("| Car | Status | Price | Contrib | Deposit | Monthly × n | APR stated / implied | GFV (% price) | Paid if handed back | Paid if bought | Cost of credit | Eff. monthly (hand back) | Monthly at 0% | Best cash | Funding premium vs cash | Eff. rate vs cash |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in pcp:
        star = "*" if r["derived_fields"] else ""
        print(f'| {name.get(r["car_id"], r["car_id"])} | {r["status"]} | {gbp(r["vehicle_price"])} | {gbp(r["manufacturer_contribution"])} | {gbp(r["customer_deposit"])} | '
              f'{gbp(r["monthly_payment"])}{star} × {r["num_payments"]} | {pct(r["apr_stated"])} / {pct(r["apr_implied"])} | '
              f'{gbp(r["gfv"])} ({pct(r["gfv_pct_of_price"])}) | {gbp(r["paid_if_handed_back"])} | {gbp(r["paid_if_bought"])} | '
              f'{gbp(r["cost_of_credit"])} | {gbp(r["effective_monthly_hand_back"])} | {gbp(r["monthly_at_0pct_same_gfv"])} | '
              f'{gbp(r.get("best_cash_price"))} | {gbp(r.get("funding_premium_vs_cash"))} | {pct(r.get("effective_rate_vs_cash"))} |')
    print("\n\\* monthly solved from APR, credit and GFV (derived deal).\n")

    print("## PCH deals\n")
    print("| Car | Status | Term | Initial | Monthly × n | Fees | Total | Effective monthly | Miles/yr |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in pch:
        print(f'| {name.get(r["car_id"], r["car_id"])} | {r["status"]} | {r["term_months"]} | {gbp(r["initial_rental"])} | '
              f'{gbp(r["monthly_rental"])} × {r["num_rentals"]} | {gbp(r["fees"])} | {gbp(r["total_cost"])} | {gbp(r["effective_monthly"])} | {r["annual_mileage"] or ""} |')

    print("\n## Cash prices (benchmarks)\n")
    print("| Car | Status | List | Price | Off list |")
    print("|---|---|---:|---:|---:|")
    for r in cash:
        print(f'| {name.get(r["car_id"], r["car_id"])} | {r["status"]} | {gbp(r["list_price"])} | {gbp(r["vehicle_price"])} | {gbp(r["discount_vs_list"])} |')

    if skipped:
        print("\n## Not computed\n")
        for r in skipped:
            print(f'- {r["id"]}: {r["skipped"]}')


def main():
    deals = load("deals.json")["deals"]
    cars = load("cars.json")
    results = compute(deals)
    if "--json" in sys.argv:
        json.dump(results, sys.stdout, indent=2)
        print()
    else:
        print_markdown(results, cars)


if __name__ == "__main__":
    main()
