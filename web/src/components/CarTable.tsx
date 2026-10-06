"use client";

import Link from "next/link";

import { DataTable, type Column } from "@/components/DataTable";
import { Badge, TriBadge } from "@/components/ui";
import { carName, gbp, num } from "@/lib/format";
import { useShortlist, useToggleShortlist } from "@/lib/hooks";
import type { SnapshotCar } from "@/lib/types";

export function CarTable({ cars }: { cars: SnapshotCar[] }) {
  const { data: shortlist } = useShortlist();
  const toggle = useToggleShortlist();
  const picked = new Set((shortlist ?? []).map((s) => s.car_id));

  const columns: Column<SnapshotCar>[] = [
    {
      key: "pick",
      header: "★",
      title: "Shortlist (saved in this browser)",
      render: (c) => (
        <button
          onClick={() => toggle.mutate(c.id)}
          aria-label={picked.has(c.id) ? "Remove from shortlist" : "Add to shortlist"}
          className={picked.has(c.id) ? "text-amber-300" : "text-gray-600 hover:text-gray-300"}
        >
          {picked.has(c.id) ? "★" : "☆"}
        </button>
      ),
    },
    {
      key: "car",
      header: "Car",
      sortValue: (c) => carName(c),
      render: (c) => (
        <div>
          <Link href={`/cars/view?id=${encodeURIComponent(c.id)}`} className="font-medium text-gray-100 hover:underline">
            {carName(c)}
          </Link>
          {c.used && <Badge tone="muted">used</Badge>}
          {c.packs && c.packs.length > 0 && (
            <div className="text-xs text-gray-500">{c.packs.join(" + ")}</div>
          )}
        </div>
      ),
    },
    {
      key: "req",
      header: "Meets brief",
      title: "Hard requirements: heat pump, internal V2L, seats, BEV",
      sortValue: (c) => (c.requirement_check.passes ? 0 : 1),
      render: (c) =>
        c.requirement_check.passes ? (
          <Badge tone={c.requirement_check.unknown.length ? "warn" : "good"} title={c.requirement_check.unknown.length ? `unverified: ${c.requirement_check.unknown.join(", ")}` : undefined}>
            {c.requirement_check.unknown.length ? "yes?" : "yes"}
          </Badge>
        ) : (
          <Badge tone="bad" title={`fails: ${c.requirement_check.failures.join(", ")}`}>
            no: {c.requirement_check.failures.join(", ")}
          </Badge>
        ),
    },
    { key: "seats", header: "Seats", align: "right", sortValue: (c) => c.seats, render: (c) => num(c.seats) },
    { key: "kwh", header: "kWh", align: "right", sortValue: (c) => c.battery_kwh, render: (c) => num(c.battery_kwh, 1) },
    { key: "range", header: "WLTP mi", align: "right", sortValue: (c) => c.wltp_range_mi, render: (c) => num(c.wltp_range_mi) },
    { key: "dc", header: "DC kW", align: "right", sortValue: (c) => c.dc_peak_kw, render: (c) => num(c.dc_peak_kw) },
    { key: "width", header: "Width", align: "right", title: "mm (Ioniq 5 = 1,890)", sortValue: (c) => c.width_mm, render: (c) => num(c.width_mm) },
    { key: "hp", header: "Heat pump", render: (c) => <TriBadge value={c.heat_pump} detail={c.packs_required?.heat_pump} /> },
    { key: "v2l", header: "Int. V2L", render: (c) => <TriBadge value={c.internal_v2l} detail={c.packs_required?.internal_v2l} /> },
    { key: "list", header: "List", align: "right", sortValue: (c) => c.list_price_gbp, render: (c) => gbp(c.list_price_gbp) },
    { key: "grant", header: "Grant", align: "right", sortValue: (c) => c.grant_gbp, render: (c) => (c.grant_gbp ? gbp(c.grant_gbp) : "—") },
    {
      key: "cash",
      header: "Best cash",
      align: "right",
      title: "Lowest active cash / outright price captured",
      sortValue: (c) => c.deal_summary.best_cash_price,
      render: (c) => gbp(c.deal_summary.best_cash_price),
    },
    {
      key: "pcp",
      header: "Best PCP £0 down",
      align: "right",
      title: "Lowest monthly on an active £0-deposit PCP",
      sortValue: (c) => c.deal_summary.best_pcp_monthly,
      render: (c) => (c.deal_summary.best_pcp_monthly != null ? `${gbp(c.deal_summary.best_pcp_monthly)}/mo` : "—"),
    },
    {
      key: "pch",
      header: "Best PCH eff.",
      align: "right",
      title: "Lowest effective monthly on an active lease (initial rental spread over the term)",
      sortValue: (c) => c.deal_summary.best_pch_effective_monthly,
      render: (c) => (c.deal_summary.best_pch_effective_monthly != null ? `${gbp(c.deal_summary.best_pch_effective_monthly)}/mo` : "—"),
    },
  ];

  return <DataTable rows={cars} columns={columns} rowKey={(c) => c.id} defaultSort={{ key: "car", dir: "asc" }} dense />;
}
