"use client";

import Link from "next/link";

import { DataTable, type Column } from "@/components/DataTable";
import { Badge, StatusBadge } from "@/components/ui";
import { carName, gbp, pct } from "@/lib/format";
import type { SnapshotCar, SnapshotDeal } from "@/lib/types";

interface Props {
  deals: SnapshotDeal[];
  cars: Map<string, SnapshotCar>;
  showCar?: boolean;
}

function monthly(d: SnapshotDeal): string {
  const m = d.metrics;
  if (d.finance_type === "pcp" && m.monthly_payment != null) {
    const star = m.derived_fields?.includes("monthly_payment") ? "*" : "";
    return `${gbp(m.monthly_payment)}${star} × ${m.num_payments}`;
  }
  if (d.finance_type === "pch" && m.monthly_rental != null) return `${gbp(m.monthly_rental)} × ${m.num_rentals}`;
  return "—";
}

function effMonthly(d: SnapshotDeal): number | null {
  const m = d.metrics;
  if (d.finance_type === "pcp") return m.effective_monthly_hand_back ?? null;
  if (d.finance_type === "pch") return m.effective_monthly ?? null;
  return null;
}

export function DealTable({ deals, cars, showCar = true }: Props) {
  const columns: Column<SnapshotDeal>[] = [
    { key: "date", header: "Captured", sortValue: (d) => d.captured_at, render: (d) => <span className="whitespace-nowrap text-gray-400">{d.captured_at}</span> },
    ...(showCar
      ? [
          {
            key: "car",
            header: "Car",
            sortValue: (d: SnapshotDeal) => (cars.get(d.car_id) ? carName(cars.get(d.car_id)!) : d.car_id),
            render: (d: SnapshotDeal) => {
              const c = cars.get(d.car_id);
              return (
                <Link href={`/cars/view?id=${encodeURIComponent(d.car_id)}`} className="text-gray-100 hover:underline">
                  {c ? carName(c) : d.car_id}
                </Link>
              );
            },
          } satisfies Column<SnapshotDeal>,
        ]
      : []),
    { key: "type", header: "Type", sortValue: (d) => d.finance_type, render: (d) => <Badge tone="info">{d.finance_type.toUpperCase()}</Badge> },
    { key: "status", header: "Status", sortValue: (d) => d.status, render: (d) => <StatusBadge status={d.status} /> },
    {
      key: "seller",
      header: "Seller / source",
      sortValue: (d) => d.dealer ?? d.source ?? "",
      render: (d) => (
        <div className="max-w-[16rem] text-gray-300">
          {d.source_url ? (
            <a href={d.source_url} target="_blank" rel="noreferrer" className="hover:underline">
              {d.dealer ?? d.source}
            </a>
          ) : (
            d.dealer ?? d.source
          )}
          {d.dealer && d.source && d.dealer !== d.source && <div className="text-xs text-gray-500">{d.source}</div>}
        </div>
      ),
    },
    {
      key: "price",
      header: "Price",
      title: "Net vehicle price after discount and grant, before finance contribution",
      align: "right",
      sortValue: (d) => d.metrics.vehicle_price ?? d.vehicle_price,
      render: (d) => gbp(d.metrics.vehicle_price ?? d.vehicle_price),
    },
    {
      key: "contrib",
      header: "Contrib.",
      title: "Manufacturer finance contribution",
      align: "right",
      sortValue: (d) => d.manufacturer_contribution,
      render: (d) => (d.manufacturer_contribution ? gbp(d.manufacturer_contribution) : "—"),
    },
    { key: "dep", header: "Deposit", align: "right", sortValue: (d) => d.customer_deposit ?? d.initial_rental, render: (d) => gbp(d.customer_deposit ?? d.initial_rental) },
    { key: "monthly", header: "Monthly × n", align: "right", sortValue: (d) => d.metrics.monthly_payment ?? d.metrics.monthly_rental, render: monthly },
    {
      key: "apr",
      header: "APR stated / implied",
      align: "right",
      sortValue: (d) => d.metrics.apr_implied ?? d.apr,
      render: (d) =>
        d.finance_type === "pcp" || d.finance_type === "campaign"
          ? `${pct(d.apr)} / ${pct(d.metrics.apr_implied)}`
          : "—",
    },
    {
      key: "gfv",
      header: "GFV (% price)",
      align: "right",
      sortValue: (d) => d.metrics.gfv_pct_of_price,
      render: (d) => (d.metrics.gfv ? `${gbp(d.metrics.gfv)} (${pct(d.metrics.gfv_pct_of_price)})` : "—"),
    },
    {
      key: "handback",
      header: "Paid if handed back",
      align: "right",
      sortValue: (d) => d.metrics.paid_if_handed_back ?? d.metrics.total_cost,
      render: (d) => gbp(d.metrics.paid_if_handed_back ?? d.metrics.total_cost),
    },
    {
      key: "eff",
      header: "Eff. monthly",
      title: "Everything paid if handed back, spread over the term, no equity assumed",
      align: "right",
      sortValue: effMonthly,
      render: (d) => (effMonthly(d) != null ? `${gbp(effMonthly(d))}/mo` : "—"),
    },
    { key: "bought", header: "Paid if bought", align: "right", sortValue: (d) => d.metrics.paid_if_bought, render: (d) => gbp(d.metrics.paid_if_bought) },
    {
      key: "credit",
      header: "Cost of credit",
      align: "right",
      sortValue: (d) => d.metrics.cost_of_credit,
      render: (d) => (d.metrics.cost_of_credit != null ? gbp(d.metrics.cost_of_credit) : "—"),
    },
    {
      key: "premium",
      header: "Premium vs best cash",
      title: "Everything paid to own the car, minus the best confirmed cash price for the same car",
      align: "right",
      sortValue: (d) => d.metrics.funding_premium_vs_cash,
      render: (d) =>
        d.metrics.funding_premium_vs_cash != null ? (
          <span title={`best cash ${gbp(d.metrics.best_cash_price)}`}>{gbp(d.metrics.funding_premium_vs_cash)}</span>
        ) : (
          "—"
        ),
    },
    {
      key: "effrate",
      header: "Eff. rate vs cash",
      title: "Annualised cost of taking this finance instead of the best cash price",
      align: "right",
      sortValue: (d) => d.metrics.effective_rate_vs_cash,
      render: (d) =>
        d.metrics.effective_rate_vs_cash != null ? (
          <span className={d.metrics.effective_rate_vs_cash > 0.06 ? "text-rose-300" : d.metrics.effective_rate_vs_cash <= 0 ? "text-emerald-300" : ""}>
            {pct(d.metrics.effective_rate_vs_cash)}
          </span>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <div>
      <DataTable rows={deals} columns={columns} rowKey={(d) => d.id} defaultSort={{ key: "date", dir: "desc" }} dense />
      <p className="mt-2 text-xs text-gray-500">
        * monthly solved from APR, credit and GFV (derived deal, not a quote). PCP totals assume 36 payments then the balloon at month 37.
      </p>
    </div>
  );
}
