"use client";

import Link from "next/link";

import { DataTable, type Column } from "@/components/DataTable";
import { Badge, TriBadge } from "@/components/ui";
import { printed } from "@/components/CarCard";
import { ROUTE_SHORT } from "@/lib/costs";
import { carName, gbp, num } from "@/lib/format";
import { useShortlist, useToggleShortlist } from "@/lib/hooks";
import type { CarContext } from "@/lib/query";
import type { SnapshotCar } from "@/lib/types";

function ageHint(days: number | null): string | undefined {
  return days == null ? undefined : `last seen ${days === 0 ? "today" : `${days} day${days === 1 ? "" : "s"} ago`}`;
}

/** One row per car; `ctxOf` carries the brief verdict and the stored costs (lib/useCarQuery). */
export function CarTable({ cars, ctxOf, horizon }: { cars: SnapshotCar[]; ctxOf: (c: SnapshotCar) => CarContext; horizon: number }) {
  const { data: shortlist } = useShortlist();
  const toggle = useToggleShortlist();
  const picked = new Set((shortlist ?? []).map((s) => s.car_id));
  const briefOf = (c: SnapshotCar) => ctxOf(c).brief;
  const costsOf = (c: SnapshotCar) => ctxOf(c).costs;

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
      header: "Brief",
      title: "Your hard requirements (Requirements page): pass, fail, or not confirmed where the car carries no value",
      sortValue: (c) => ({ pass: 0, unknown: 1, fail: 2 }[briefOf(c).status]),
      render: (c) => {
        const b = briefOf(c);
        if (b.status === "pass") return <Badge tone="good">meets</Badge>;
        if (b.status === "fail") return <Badge tone="bad" title={`fails: ${b.failedLabels.join(", ")}`}>fails · {b.failedLabels.join(", ")}</Badge>;
        return <Badge tone="muted" title={`not confirmed: ${b.unknownLabels.join(", ")}`}>unconfirmed · {b.unknownLabels.join(", ")}</Badge>;
      },
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
      key: "true",
      header: `True £/mo · ${horizon} mo`,
      align: "right",
      title: `Cheapest current figure on one footing across cash, PCP, lease and used over ${horizon} months: payments discounted at your savings rate, the car's expected end value credited back`,
      sortValue: (c) => costsOf(c).trueCost?.monthly,
      render: (c) => {
        const t = costsOf(c).trueCost;
        return t ? (
          <span title={`${ROUTE_SHORT[t.route]} · ${t.sourceName} · ${printed(t)}`}>
            {gbp(t.monthly)}
            <span className="text-xs text-gray-500"> {ROUTE_SHORT[t.route].toLowerCase()}</span>
          </span>
        ) : "—";
      },
    },
    {
      key: "cash",
      header: "Best cash",
      align: "right",
      title: "Lowest current cash / outright price captured (not stale, not gone)",
      sortValue: (c) => costsOf(c).cash?.price,
      render: (c) => { const k = costsOf(c).cash; return <span title={ageHint(k?.ageDays ?? null)}>{gbp(k?.price)}</span>; },
    },
    {
      key: "pcp",
      header: "PCP £/mo",
      align: "right",
      title: "Cheapest current PCP as printed (monthly × payments, deposit, GFV in the tooltip)",
      sortValue: (c) => costsOf(c).byRoute.pcp?.headline,
      render: (c) => { const t = costsOf(c).byRoute.pcp; return t ? <span title={`${printed(t)} · ${t.sourceName}${t.ageDays != null ? ` · ${ageHint(t.ageDays)}` : ""}`}>{gbp(t.headline)}/mo</span> : "—"; },
    },
    {
      key: "pch",
      header: "Lease £/mo",
      align: "right",
      title: "Cheapest current lease as printed (initial rental spread over the term in the tooltip)",
      sortValue: (c) => costsOf(c).byRoute.pch?.headline,
      render: (c) => { const t = costsOf(c).byRoute.pch; return t ? <span title={`${printed(t)} · ${t.sourceName}${t.ageDays != null ? ` · ${ageHint(t.ageDays)}` : ""}`}>{gbp(t.headline)}/mo</span> : "—"; },
    },
    {
      key: "used",
      header: "Used from",
      align: "right",
      title: "Cheapest used example of the model on sale",
      sortValue: (c) => costsOf(c).byRoute.used?.headline,
      render: (c) => { const t = costsOf(c).byRoute.used; return t ? <span title={`${printed(t)} · ${t.sourceName}`}>{gbp(t.headline)}</span> : "—"; },
    },
  ];

  return <DataTable rows={cars} columns={columns} rowKey={(c) => c.id} defaultSort={{ key: "car", dir: "asc" }} dense />;
}
