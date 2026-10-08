#!/usr/bin/env python3
"""The shared arithmetic fixture: what model/deal_math.py says a set of deals
cost, written as JSON so the browser's port (web/src/lib/model/dealMath.ts)
and this module are checked against the same numbers.

    python3 -m model.cost_fixture > tests/fixtures/cost_cases.json

tests/test_deal_math.py asserts this module still reproduces the file;
web/src/lib/model/dealMath.test.ts asserts the port does. Regenerate the file
when the model changes on purpose, and both suites will say whether the other
side followed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from model.deal_math import DEFAULT_BASIS, compute, used_route

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "cost_cases.json"

PCP = {"id": "p", "car_id": "c", "finance_type": "pcp", "status": "live", "list_price": 40000.0, "vehicle_price": 36000.0,
       "customer_deposit": 0.0, "manufacturer_contribution": 0.0, "apr": 0.0, "num_payments": 36, "term_months": 37,
       "gfv": 18000.0, "monthly_payment": 500.0}
PCH = {"id": "l", "car_id": "c", "finance_type": "pch", "status": "live", "term_months": 36, "num_rentals": 35,
       "monthly_rental": 400.0, "initial_rental": 3600.0, "fees_gbp": 300.0}
CASH = {"id": "k", "car_id": "c", "finance_type": "cash", "status": "live", "list_price": 40000.0, "vehicle_price": 34000.0}
# A dearer, longer PCP with a deposit, a contribution, fees and a different first payment.
PCP_LONG = {"id": "p49", "car_id": "c", "finance_type": "pcp", "status": "lead", "list_price": 40000.0, "vehicle_price": 37500.0,
            "customer_deposit": 2000.0, "manufacturer_contribution": 1000.0, "fees_gbp": 10.0, "apr": 0.069, "num_payments": 48,
            "term_months": 49, "gfv": 14000.0, "monthly_payment": 455.0, "first_payment": 465.0}
# Monthly to be solved from APR, credit and GFV.
PCP_DERIVED = {"id": "pd", "car_id": "c", "finance_type": "pcp", "status": "derived", "list_price": 40000.0, "vehicle_price": 36000.0,
               "customer_deposit": 0.0, "manufacturer_contribution": 500.0, "apr": 0.089, "num_payments": 36, "gfv": 17000.0}
# Credit to be back-solved from the payments; the price follows.
PCP_BACKSOLVED = {"id": "pb", "car_id": "c2", "finance_type": "pcp", "status": "live", "list_price": 30000.0, "customer_deposit": 1000.0,
                  "manufacturer_contribution": 0.0, "apr": 0.049, "num_payments": 36, "gfv": 12000.0, "monthly_payment": 320.0}
CAMPAIGN = {"id": "cmp", "car_id": "c", "finance_type": "campaign", "status": "campaign", "apr": 0.0, "manufacturer_contribution": 1500.0}

BASIS_ZERO = {"term_months": 37, "savings_rate_apr": 0.0, "residual_pct_of_list": 0.45, "residual_at_months": 37}
BASIS_55 = {"term_months": 37, "savings_rate_apr": 0.04, "residual_pct_of_list": 0.55, "residual_at_months": 36}
BASIS_25 = {"term_months": 25, "savings_rate_apr": 0.05, "residual_pct_of_list": 0.5, "residual_at_months": 36}


def _deal_case(name, deals, basis=None, residuals=None):
    return {"name": name, "basis": basis or DEFAULT_BASIS, "residuals": residuals or {}, "deals": deals,
            "expected": compute(deals, basis, residuals)}


def _used_case(name, price, age_years, basis, value_at_end=None):
    return {"name": name, "price": price, "age_years": age_years, "basis": basis, "value_at_end": value_at_end,
            "expected": used_route(price, age_years, basis, value_at_end)}


def build() -> dict:
    seed = json.loads((ROOT / "data" / "seed" / "deals.json").read_text(encoding="utf-8"))["deals"]
    return {
        "generated_by": "python3 -m model.cost_fixture",
        "default_basis": DEFAULT_BASIS,
        "deal_cases": [
            _deal_case("seed deals, default basis", seed),
            _deal_case("plain arithmetic at a zero rate", [PCP, PCH, CASH], BASIS_ZERO),
            _deal_case("equity and a savings rate", [PCP, PCH, CASH], BASIS_55),
            _deal_case("used-market residual beats the gfv", [PCP, CASH], DEFAULT_BASIS, {"c": {"value": 21000.0, "source": "used-market", "n": 5}}),
            _deal_case("longer, dearer pcp with fees and a first payment", [PCP_LONG, CASH], DEFAULT_BASIS),
            _deal_case("monthly solved from apr", [PCP_DERIVED, CASH], DEFAULT_BASIS),
            _deal_case("credit back-solved, no cash benchmark, no floor for cash", [PCP_BACKSOLVED, {**CASH, "car_id": "c3", "id": "k3"}], BASIS_25),
            _deal_case("a campaign is skipped", [CAMPAIGN, PCH], DEFAULT_BASIS),
        ],
        "used_cases": [
            _used_case("used with the market's figure", 19000.0, 2, DEFAULT_BASIS, 9000.0),
            _used_case("used on the assumption", 19000.0, 2, DEFAULT_BASIS),
            _used_case("used over a shorter term", 12500.0, 4, BASIS_25),
        ],
    }


def main() -> int:
    json.dump(build(), sys.stdout, indent=1, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
