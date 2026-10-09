"use client";

import Link from "next/link";
import { useMemo, type ReactNode } from "react";

import { DataTable, type Column } from "@/components/DataTable";
import { Badge, TriBadge } from "@/components/ui";
import { printed } from "@/components/CarCard";
import { ROUTE_SHORT, type CarCosts } from "@/lib/costs";
import { FIELDS, flagFields, show, triOf, type Field } from "@/lib/fields";
import { carName, gbp } from "@/lib/format";
import type { CarContext } from "@/lib/query";
import type { SnapshotCar } from "@/lib/types";

function ageHint(days: number | null | undefined): string | undefined {
  return days == null ? undefined : `last seen ${days === 0 ? "today" : `${days} day${days === 1 ? "" : "s"} ago`}`;
}

/** Shown until the reader picks otherwise; every other field is one click away in the chooser. */
const DEFAULT_SHOWN = ["true", "seats", "range", "width", "wheels", "flag:heat_pump", "flag:v2l_internal", "battery", "dc", "list", "cash", "pcp", "pch", "used", "grant"];

/** The cost columns say where their figure came from on hover. */
function costCell(key: string, k: CarCosts): ReactNode | undefined {
  const route = key === "pcp" || key === "pch" || key === "used" ? k.byRoute[key] : null;
  switch (key) {
    case "true": {
      const t = k.trueCost;
      return t ? (
        <span title={`${ROUTE_SHORT[t.route]} · ${t.sourceName} · ${printed(t)}`}>
          {gbp(t.monthly)}
          <span className="text-xs text-gray-500"> {ROUTE_SHORT[t.route].toLowerCase()}</span>
        </span>
      ) : "—";
    }
    case "cash":
      return k.cash ? <span title={ageHint(k.cash.ageDays)}>{gbp(k.cash.price)}</span> : "—";
    case "pcp":
    case "pch":
    case "used":
      return route ? (
        <span title={`${printed(route)} · ${route.sourceName}${route.ageDays != null ? ` · ${ageHint(route.ageDays)}` : ""}`}>
          {gbp(route.headline)}{key === "used" ? "" : "/mo"}
        </span>
      ) : "—";
  }
  return undefined;
}

/** One row per car; `ctxOf` carries the stored costs (lib/useCarQuery). Every field is a column the reader can show and order. */
export function CarTable({ cars, ctxOf, horizon, flagLabels }: {
  cars: SnapshotCar[];
  ctxOf: (c: SnapshotCar) => CarContext;
  horizon: number;
  flagLabels: Record<string, string>;
}) {
  const columns = useMemo(() => {
    const costsOf = (c: SnapshotCar) => ctxOf(c).costs;
    const fields: Field[] = [...FIELDS, ...flagFields(flagLabels)];
    const shown = new Set(DEFAULT_SHOWN);
    const toColumn = (x: Field): Column<SnapshotCar> => ({
      key: x.key,
      header: x.key === "true" ? `True £/mo · ${horizon} mo` : x.short ?? x.label,
      label: x.unit && x.kind === "number" ? `${x.label} (${x.unit})` : x.label,
      group: x.group,
      title: x.key === "true" ? `Cheapest current figure on one footing across cash, PCP, lease and used over ${horizon} months: payments discounted at your savings rate, the car's expected end value credited back` : x.title ?? x.label,
      align: x.kind === "number" || x.kind === "money" ? "right" : undefined,
      hidden: !shown.has(x.key),
      sortValue: (c) => {
        const v = x.value(c, costsOf(c));
        if (x.kind === "tri") return ({ standard: 0, pack: 1, option: 2, none: 3 } as Record<string, number>)[String(v)] ?? null;
        if (x.kind === "bool") return v == null ? null : v ? 0 : 1;
        return typeof v === "number" || typeof v === "string" ? v : null;
      },
      render: (c) => {
        const k = costsOf(c);
        if (x.kind === "tri") return <TriBadge value={triOf(x.value(c, k))} detail={x.pack?.(c)} />;
        // The header carries the unit.
        return costCell(x.key, k) ?? show({ ...x, unit: undefined }, x.value(c, k));
      },
    });
    const car: Column<SnapshotCar> = {
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
          {c.packs && c.packs.length > 0 && <div className="text-xs text-gray-500">{c.packs.join(" + ")}</div>}
        </div>
      ),
    };
    // The default columns in their default order, then the rest in field order.
    const byKey = new Map(fields.map((x) => [x.key, x]));
    const first = DEFAULT_SHOWN.map((k) => byKey.get(k)).filter((x): x is Field => !!x);
    const rest = fields.filter((x) => !shown.has(x.key) && x.key !== "packs");
    return [car, ...[...first, ...rest].map(toColumn)];
  }, [ctxOf, flagLabels, horizon]);

  return <DataTable rows={cars} columns={columns} rowKey={(c) => c.id} defaultSort={{ key: "car", dir: "asc" }} dense prefsKey="cars" />;
}
