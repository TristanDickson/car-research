import { describe, expect, it } from "vitest";

import { doesNotAddUp, rateVsCashSteps } from "./explain";
import { pcpMetrics, type DealFields } from "./model/dealMath";
import type { SnapshotOffer } from "./types";

const offer = (d: DealFields, cash: number) =>
  ({ ...d, metrics: pcpMetrics(d, { id: "k", car_id: "c", finance_type: "cash", vehicle_price: cash }) }) as unknown as SnapshotOffer;

describe("the rate against cash, step by step", () => {
  it("shows what stays with you today and what is paid back, with the rate the sum gives", () => {
    // A Carwow representative PCP of 11 Oct 2026, with a deposit contribution from the maker.
    const o = offer({ id: "p", car_id: "c", finance_type: "pcp", vehicle_price: 33108, manufacturer_contribution: 6550, customer_deposit: 6621,
      num_payments: 36, monthly_payment: 294, gfv: 11963, apr: 0.049 }, 32622);
    expect(rateVsCashSteps(o)).toBe([
      "Cash: £32,622, the cheapest cash price for this car.",
      "PCP, today: a £6,621 deposit instead of £32,622, so £26,001 stays with you.",
      "Then: 36 payments of £294 (£10,584), and £11,963 at month 37 to keep the car: £22,547 paid back.",
      "You pay back £3,454 less than you kept (-5.8% a year): this finance costs less than paying cash.",
      "The maker puts £6,550 towards the deposit only if you take its finance.",
      "Either way you own the car at the end, so what it will then be worth does not come into it, nor does your term.",
    ].join("\n"));
  });

  it("counts the fees as paid today, names an odd first payment, and agrees with the premium over cash", () => {
    const o = offer({ id: "p", car_id: "c", finance_type: "pcp", vehicle_price: 36000, customer_deposit: 1000, fees_gbp: 99,
      num_payments: 36, first_payment: 520, monthly_payment: 500, gfv: 18000, apr: 0.049 }, 35000);
    const steps = rateVsCashSteps(o)!.split("\n");
    expect(steps[1]).toBe("PCP, today: a £1,000 deposit and £99 fees instead of £35,000, so £33,901 stays with you.");
    expect(steps[2]).toBe("Then: a first payment of £520 and 35 of £500 (£18,020), and £18,000 at month 37 to keep the car: £36,020 paid back.");
    expect(steps[3]).toMatch(/^You pay back £2,119 more than you kept: like borrowing £33,901 at \d+\.\d% a year\.$/);
    expect(o.metrics.funding_premium_vs_cash).toBeCloseTo(2119, 2);
  });

  it("says nothing without a cash price for the same car", () => {
    const d: DealFields = { id: "p", car_id: "c", finance_type: "pcp", vehicle_price: 36000, num_payments: 36, monthly_payment: 500, gfv: 18000 };
    expect(rateVsCashSteps({ ...d, metrics: pcpMetrics(d, null) } as unknown as SnapshotOffer)).toBeNull();
  });
});

describe("a quote whose own figures do not add up", () => {
  it("says what it prints, what its figures give, and the headline that disagrees too", () => {
    // Halliwell Jones's EV5 Storm example of 11 Oct 2026.
    const d: DealFields = { id: "p", car_id: "c", finance_type: "pcp", vehicle_price: 43145, customer_deposit: 3999, manufacturer_contribution: 2646,
      amount_of_credit: 36500, apr: 0.039, num_payments: 36, gfv: 21962.58, monthly_payment: 449 };
    const o = { ...d, banner_monthly: 499, metrics: pcpMetrics(d, null) } as unknown as SnapshotOffer & { banner_monthly: number };
    expect(doesNotAddUp(o)).toBe([
      "It prints £449.00 a month, but the £36,500 it lends at its 3.9% APR, with £21,963 at the end, comes to £500.09 a month.",
      "The headline above it says £499 a month.",
      "So it is left out of the cheapest prices. Check it with the seller before relying on it.",
    ].join("\n"));
    expect(doesNotAddUp({ ...o, monthly_payment: 500, metrics: pcpMetrics({ ...d, monthly_payment: 500 }, null) } as unknown as SnapshotOffer)).toBeNull();
  });
});
