"use client";

import Link from "next/link";

import { DataTable, type Column } from "@/components/DataTable";
import { Badge, TriBadge } from "@/components/ui";
import { printed } from "@/components/CarCard";
import { ROUTE_SHORT } from "@/lib/costs";
import { carName, gbp, num } from "@/lib/format";
import type { CarContext } from "@/lib/query";
import type { SnapshotCar } from "@/lib/types";

function ageHint(days: number | null): string | undefined {
  return days == null ? undefined : `last seen ${days === 0 ? "today" : `${days} day${days === 1 ? "" : "s"} ago`}`;
}

/** One row per car; `ctxOf` carries the stored costs (lib/useCarQuery). The reader picks the columns and their order. */
export function CarTable({ cars, ctxOf, horizon }: { cars: SnapshotCar[]; ctxOf: (c: SnapshotCar) => CarContext; horizon: number }) {
  const costsOf = (c: SnapshotCar) => ctxOf(c).costs;

  const columns: Column<SnapshotCar>[] = [
    {
      key: "car",
      header: "Car",
      pinned: true,
      sortValue: (c) => carName(c),
      render: (c) => (
        <div className="min-w-[8rem] max-w-[12rem] sm:max-w-[20rem]">
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
      key: "true",
      header: `True £/mo · ${horizon} mo`,
      label: "True £/month",
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
    { key: "seats", header: "Seats", align: "right", sortValue: (c) => c.seats, render: (c) => num(c.seats) },
    { key: "range", header: "WLTP mi", label: "WLTP range (mi)", align: "right", sortValue: (c) => c.wltp_range_mi, render: (c) => num(c.wltp_range_mi) },
    { key: "width", header: "Width", label: "Width (mm)", align: "right", title: "mm (Ioniq 5 = 1,890)", sortValue: (c) => c.width_mm, render: (c) => num(c.width_mm) },
    { key: "hp", header: "Heat pump", render: (c) => <TriBadge value={c.heat_pump} detail={c.packs_required?.heat_pump} /> },
    { key: "v2l", header: "Int. V2L", label: "Cabin socket (internal V2L)", render: (c) => <TriBadge value={c.internal_v2l} detail={c.packs_required?.internal_v2l} /> },
    { key: "kwh", header: "kWh", label: "Battery (kWh)", align: "right", sortValue: (c) => c.battery_kwh, render: (c) => num(c.battery_kwh, 1) },
    { key: "dc", header: "DC kW", label: "DC peak (kW)", align: "right", sortValue: (c) => c.dc_peak_kw, render: (c) => num(c.dc_peak_kw) },
    { key: "list", header: "List", label: "List price", align: "right", sortValue: (c) => c.list_price_gbp, render: (c) => gbp(c.list_price_gbp) },
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
    { key: "grant", header: "Grant", align: "right", sortValue: (c) => c.grant_gbp, render: (c) => (c.grant_gbp ? gbp(c.grant_gbp) : "—") },
    { key: "ev2l", header: "Ext. V2L", label: "External V2L", hidden: true, render: (c) => <TriBadge value={c.external_v2l} detail={c.packs_required?.external_v2l} /> },
    { key: "length", header: "Length", label: "Length (mm)", align: "right", hidden: true, sortValue: (c) => c.length_mm, render: (c) => num(c.length_mm) },
    { key: "turn", header: "Turn m", label: "Turning circle (m)", align: "right", hidden: true, sortValue: (c) => c.turning_circle_m, render: (c) => num(c.turning_circle_m, 1) },
    { key: "boot", header: "Boot L", label: "Boot (L)", align: "right", hidden: true, sortValue: (c) => c.boot_l, render: (c) => num(c.boot_l) },
    { key: "power", header: "hp", label: "Power (hp)", align: "right", hidden: true, sortValue: (c) => c.power_hp, render: (c) => num(c.power_hp) },
    { key: "eff", header: "mi/kWh", label: "Efficiency (mi/kWh)", align: "right", hidden: true, sortValue: (c) => c.efficiency_mi_kwh, render: (c) => num(c.efficiency_mi_kwh, 1) },
    { key: "charge", header: "10–80 min", label: "DC 10–80% (min)", align: "right", hidden: true, sortValue: (c) => c.dc_10_80_min, render: (c) => num(c.dc_10_80_min) },
    { key: "year", header: "Year", label: "Model year", align: "right", hidden: true, sortValue: (c) => c.model_year, render: (c) => (c.model_year ? String(c.model_year) : "—") },
  ];

  return <DataTable rows={cars} columns={columns} rowKey={(c) => c.id} defaultSort={{ key: "car", dir: "asc" }} dense prefsKey="cars" />;
}
