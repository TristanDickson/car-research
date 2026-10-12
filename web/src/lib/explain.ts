// The sum behind a figure, in words, for the reader to check: what was compared with what.
import { gbp, pct } from "./format";
import type { SnapshotOffer } from "./types";

/** How a PCP's rate against cash is worked out (lib/model/dealMath.ts, pcpMetrics), one step a line: what
 * stays with you today by not paying the cheapest cash price, and what you pay back to own the car.
 * Null when there is no cash price for the same car to compare with. */
export function rateVsCashSteps(o: Pick<SnapshotOffer, "metrics" | "first_payment" | "fees_gbp">): string | null {
  const m = o.metrics;
  const cash = m.best_cash_price, rate = m.effective_rate_vs_cash, n = m.num_payments, pay = m.monthly_payment;
  if (cash == null || rate == null || n == null || pay == null) return null;
  const dep = m.customer_deposit ?? 0, fees = o.fees_gbp ?? 0, gfv = m.gfv ?? 0, contrib = m.manufacturer_contribution ?? 0;
  const first = o.first_payment ?? pay;
  const down = dep + fees;
  const kept = cash - down;
  const payments = first + pay * (n - 1);
  const back = payments + gfv;
  const today = down
    ? `${[dep ? `a ${gbp(dep)} deposit` : null, fees ? `${gbp(fees)} fees` : null].filter(Boolean).join(" and ")} instead of ${gbp(cash)}, so ${gbp(kept)} stays with you`
    : `nothing down instead of ${gbp(cash)}, so all ${gbp(cash)} stays with you`;
  const schedule = first === pay ? `${n} payments of ${gbp(pay)}` : `a first payment of ${gbp(first)} and ${n - 1} of ${gbp(pay)}`;
  const diff = back - kept;
  return [
    `Cash: ${gbp(cash)}, the cheapest cash price for this car.`,
    `PCP, today: ${today}.`,
    `Then: ${schedule} (${gbp(payments)}${m.derived_fields?.includes("monthly_payment") ? ", the monthly worked out from the APR, not printed" : ""}), and ${gbp(gfv)} at month ${n + 1} to keep the car: ${gbp(back)} paid back.`,
    Math.round(diff) === 0
      ? `You pay back what you kept: ${pct(rate)} a year.`
      : diff > 0
        ? `You pay back ${gbp(diff)} more than you kept: like borrowing ${gbp(kept)} at ${pct(rate)} a year.`
        : `You pay back ${gbp(-diff)} less than you kept (${pct(rate)} a year): this finance costs less than paying cash.`,
    ...(contrib ? [`The maker puts ${gbp(contrib)} towards the deposit only if you take its finance.`] : []),
    "Either way you own the car at the end, so what it will then be worth does not come into it, nor does your term.",
  ].join("\n");
}
