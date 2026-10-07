"use client";

import Link from "next/link";

import { DataTable, type Column } from "@/components/DataTable";
import { Badge, SeenBadge, StatusBadge } from "@/components/ui";
import { carName, gbp, pct } from "@/lib/format";
import { ageLabel, isStale } from "@/lib/freshness";
import type { SnapshotCar, SnapshotOffer } from "@/lib/types";

interface Props {
  offers: SnapshotOffer[];
  cars: Map<string, SnapshotCar>;
  staleDays: number;
  showCar?: boolean;
  defaultSort?: { key: string; dir: "asc" | "desc" };
}

function monthly(o: SnapshotOffer): string {
  const m = o.metrics;
  if (o.finance_type === "pcp" && m.monthly_payment != null) {
    const star = m.derived_fields?.includes("monthly_payment") ? "*" : "";
    return `${gbp(m.monthly_payment)}${star} × ${m.num_payments}`;
  }
  if (o.finance_type === "pch" && m.monthly_rental != null) return `${gbp(m.monthly_rental)} × ${m.num_rentals}`;
  return "—";
}

function effMonthly(o: SnapshotOffer): number | null {
  const m = o.metrics;
  if (o.finance_type === "pcp") return m.effective_monthly_hand_back ?? null;
  if (o.finance_type === "pch") return m.effective_monthly ?? null;
  return null;
}

export function OfferTable({ offers, cars, staleDays, showCar = true, defaultSort }: Props) {
  const now = new Date();
  const columns: Column<SnapshotOffer>[] = [
    {
      key: "seen",
      header: "Seen",
      title: "Last sighting of this offer at its source. Grey rows are stale or gone.",
      sortValue: (o) => o.freshness.last_seen_at ?? "",
      render: (o) => {
        const f = o.freshness;
        const gone = f.state === "gone";
        return (
          <div className="whitespace-nowrap">
            <SeenBadge label={ageLabel(f.last_seen_at, now)} stale={isStale(f, staleDays, now)} gone={gone} />
            {f.observations > 1 && (
              <div className="mt-0.5 text-xs text-gray-500" title={f.history.map((h) => `${h.observed_at}: ${h.present ? gbp(h.monthly_payment ?? h.vehicle_price) : "gone"}`).join("\n")}>
                {f.observations} sightings since {f.first_seen_at.slice(0, 10)}
              </div>
            )}
          </div>
        );
      },
    },
    ...(showCar
      ? [
          {
            key: "car",
            header: "Car",
            sortValue: (o: SnapshotOffer) => (cars.get(o.car_id) ? carName(cars.get(o.car_id)!) : o.car_id),
            render: (o: SnapshotOffer) => {
              const c = cars.get(o.car_id);
              return (
                <Link href={`/cars/view?id=${encodeURIComponent(o.car_id)}`} className="text-gray-100 hover:underline">
                  {c ? carName(c) : o.car_id}
                </Link>
              );
            },
          } satisfies Column<SnapshotOffer>,
        ]
      : []),
    { key: "type", header: "Type", sortValue: (o) => o.finance_type, render: (o) => <Badge tone="info">{o.finance_type.toUpperCase()}</Badge> },
    { key: "state", header: "State", sortValue: (o) => o.freshness.state, render: (o) => <StatusBadge status={o.freshness.state} /> },
    {
      key: "seller",
      header: "Seller / source",
      sortValue: (o) => o.dealer ?? o.source ?? "",
      render: (o) => (
        <div className="max-w-[16rem] text-gray-300">
          {o.source_url ? (
            <a href={o.source_url} target="_blank" rel="noreferrer" className="hover:underline">
              {o.dealer ?? o.source}
            </a>
          ) : (
            o.dealer ?? o.source
          )}
          {o.dealer && o.source && o.dealer !== o.source && <div className="text-xs text-gray-500">{o.source}</div>}
          <div className="text-xs text-gray-600">via {o.provider} · {o.verification}</div>
        </div>
      ),
    },
    {
      key: "price",
      header: "Price",
      title: "Net vehicle price after discount and grant, before finance contribution",
      align: "right",
      sortValue: (o) => o.metrics.vehicle_price ?? o.vehicle_price,
      render: (o) => gbp(o.metrics.vehicle_price ?? o.vehicle_price),
    },
    {
      key: "contrib",
      header: "Contrib.",
      title: "Manufacturer finance contribution",
      align: "right",
      sortValue: (o) => o.manufacturer_contribution,
      render: (o) => (o.manufacturer_contribution ? gbp(o.manufacturer_contribution) : "—"),
    },
    { key: "dep", header: "Deposit", align: "right", sortValue: (o) => o.customer_deposit ?? o.initial_rental, render: (o) => gbp(o.customer_deposit ?? o.initial_rental) },
    { key: "monthly", header: "Monthly × n", align: "right", sortValue: (o) => o.metrics.monthly_payment ?? o.metrics.monthly_rental, render: monthly },
    {
      key: "apr",
      header: "APR stated / implied",
      align: "right",
      sortValue: (o) => o.metrics.apr_implied ?? o.apr,
      render: (o) => (o.finance_type === "pcp" || o.finance_type === "campaign" ? `${pct(o.apr)} / ${pct(o.metrics.apr_implied)}` : "—"),
    },
    {
      key: "gfv",
      header: "GFV (% price)",
      align: "right",
      sortValue: (o) => o.metrics.gfv_pct_of_price,
      render: (o) => (o.metrics.gfv ? `${gbp(o.metrics.gfv)} (${pct(o.metrics.gfv_pct_of_price)})` : "—"),
    },
    {
      key: "handback",
      header: "Paid if handed back",
      align: "right",
      sortValue: (o) => o.metrics.paid_if_handed_back ?? o.metrics.total_cost,
      render: (o) => gbp(o.metrics.paid_if_handed_back ?? o.metrics.total_cost),
    },
    {
      key: "true",
      header: "True £/mo",
      title: "Every route on one footing: each payment discounted at the savings rate, the car's expected value at the end credited back (PCP: equity above the GFV, never below zero; outright: sold), spread over the agreement. In brackets: the same with the car worth only its GFV.",
      align: "right",
      sortValue: (o) => o.metrics.true_monthly,
      render: (o) =>
        o.metrics.true_monthly != null ? (
          <span className="font-medium text-gray-100">
            {gbp(o.metrics.true_monthly)}
            {o.metrics.true_monthly_floor != null && o.metrics.true_monthly_floor !== o.metrics.true_monthly && (
              <span className="font-normal text-gray-500"> ({gbp(o.metrics.true_monthly_floor)})</span>
            )}
          </span>
        ) : (
          "—"
        ),
    },
    {
      key: "eff",
      header: "Eff. monthly",
      title: "Everything paid if handed back, spread over the term, no equity assumed",
      align: "right",
      sortValue: effMonthly,
      render: (o) => (effMonthly(o) != null ? `${gbp(effMonthly(o))}/mo` : "—"),
    },
    { key: "bought", header: "Paid if bought", align: "right", sortValue: (o) => o.metrics.paid_if_bought, render: (o) => gbp(o.metrics.paid_if_bought) },
    { key: "credit", header: "Cost of credit", align: "right", sortValue: (o) => o.metrics.cost_of_credit, render: (o) => (o.metrics.cost_of_credit != null ? gbp(o.metrics.cost_of_credit) : "—") },
    {
      key: "premium",
      header: "Premium vs best cash",
      title: "Everything paid to own the car, minus the best confirmed cash price for the same car",
      align: "right",
      sortValue: (o) => o.metrics.funding_premium_vs_cash,
      render: (o) =>
        o.metrics.funding_premium_vs_cash != null ? (
          <span title={`best cash ${gbp(o.metrics.best_cash_price)}`}>{gbp(o.metrics.funding_premium_vs_cash)}</span>
        ) : (
          "—"
        ),
    },
    {
      key: "effrate",
      header: "Eff. rate vs cash",
      title: "Annualised cost of taking this finance instead of the best cash price",
      align: "right",
      sortValue: (o) => o.metrics.effective_rate_vs_cash,
      render: (o) =>
        o.metrics.effective_rate_vs_cash != null ? (
          <span className={o.metrics.effective_rate_vs_cash > 0.06 ? "text-rose-300" : o.metrics.effective_rate_vs_cash <= 0 ? "text-emerald-300" : ""}>
            {pct(o.metrics.effective_rate_vs_cash)}
          </span>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <div>
      <DataTable rows={offers} columns={columns} rowKey={(o) => o.id} defaultSort={defaultSort ?? { key: "seen", dir: "desc" }} dense />
      <p className="mt-2 text-xs text-gray-500">
        * monthly solved from APR, credit and GFV (derived, not a quote). PCP totals assume 36 payments then the balloon at month 37.
        True £/mo puts cash, PCP and lease on one footing (savings rate and residual assumptions on the Data page); the bracketed figure is the GFV floor.
        Stale = an active offer not seen for more than {staleDays} days.
      </p>
    </div>
  );
}
