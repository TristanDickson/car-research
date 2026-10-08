"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, type ReactNode } from "react";

import { CarImage } from "@/components/CarImage";
import { Badge, Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { carCosts, ROUTE_LABEL, type CarCosts } from "@/lib/costs";
import { carName, gbp, num } from "@/lib/format";
import { useCars, useCosts, useDataPage } from "@/lib/hooks";
import type { SnapshotCar, Tri } from "@/lib/types";

export default function ComparePage() {
  return (
    <Suspense fallback={<Loading />}>
      <Compare />
    </Suspense>
  );
}

const tri = (v?: Tri) => (v === "standard" ? "yes" : v === "pack" || v === "option" ? "with pack" : v === "none" ? "no" : "?");

function Compare() {
  const ids = (useSearchParams().get("ids") ?? "").split(",").filter(Boolean).slice(0, 4);
  const cars = useCars();
  const rows_ = useCosts();
  const data = useDataPage();
  const staleDays = data.data?.stale_days ?? 14;

  const picked = useMemo(() => {
    const byId = new Map((cars.data ?? []).map((c) => [c.id, c]));
    return ids.map((id) => byId.get(id)).filter((c): c is SnapshotCar => !!c);
  }, [cars.data, ids]);

  const costs = useMemo(() => {
    const out = new Map<string, CarCosts>();
    for (const c of picked) out.set(c.id, carCosts(c, rows_.data?.get(c.id), data.data?.sources));
    return out;
  }, [picked, rows_.data, data.data?.sources]);

  if (cars.error) return <ErrorNote error={cars.error} />;
  if (!cars.data || !rows_.data) return <Loading />;
  if (picked.length < 2) {
    return (
      <Empty>
        Pick at least two cars to compare on the <Link href="/" className="underline">Pick</Link> page.
      </Empty>
    );
  }

  const trues = picked.map((c) => costs.get(c.id)!.trueCost?.monthly ?? null);
  const cheapest = trues.reduce<{ i: number; v: number } | null>((acc, v, i) => (v != null && (acc == null || v < acc.v) ? { i, v } : acc), null);
  const base = cheapest ? picked[cheapest.i] : null;

  const rows: { label: string; cell: (c: SnapshotCar) => ReactNode; delta?: (c: SnapshotCar) => ReactNode }[] = [
    {
      label: "True cost per month (cheapest route)",
      cell: (c) => { const t = costs.get(c.id)!.trueCost; return t ? <>{big(t.monthly, "/mo")}<div className="text-xs text-gray-500">{ROUTE_LABEL[t.route]} · {t.sourceName}</div></> : big(null); },
      delta: (c) => diffMoney(costs.get(c.id)!.trueCost?.monthly ?? null, base ? costs.get(base.id)!.trueCost?.monthly ?? null : null),
    },
    { label: "Pay monthly (as printed)", cell: (c) => big(costs.get(c.id)!.monthly, "/mo") },
    {
      label: "Over that agreement, handed back",
      cell: (c) => big(costs.get(c.id)!.threeYear),
      delta: (c) => diffMoney(costs.get(c.id)!.threeYear, base ? costs.get(base.id)!.threeYear : null),
    },
    { label: "Buy outright", cell: (c) => big(costs.get(c.id)!.cash?.price ?? null), delta: (c) => diffMoney(costs.get(c.id)!.cash?.price ?? null, base ? costs.get(base.id)!.cash?.price ?? null : null) },
    { label: "Seats", cell: (c) => num(c.seats), delta: (c) => diffNum(c.seats, base?.seats, "") },
    { label: "Range (WLTP)", cell: (c) => unit(c.wltp_range_mi, " mi"), delta: (c) => diffNum(c.wltp_range_mi, base?.wltp_range_mi, " mi") },
    { label: "Rapid charging", cell: (c) => (c.dc_peak_kw ? `${num(c.dc_peak_kw)} kW` : "—"), delta: (c) => diffNum(c.dc_peak_kw, base?.dc_peak_kw, " kW") },
    { label: "Width", cell: (c) => unit(c.width_mm, " mm"), delta: (c) => diffNum(c.width_mm, base?.width_mm, " mm", true) },
    { label: "Boot", cell: (c) => (c.boot_l ? `${num(c.boot_l)} L` : "—"), delta: (c) => diffNum(c.boot_l, base?.boot_l, " L") },
    { label: "Heat pump", cell: (c) => tri(c.heat_pump) },
    { label: "Cabin 3-pin socket", cell: (c) => tri(c.internal_v2l) },
    { label: "Powered sliding doors", cell: (c) => (c.powered_sliding_doors ? String(c.powered_sliding_doors) : "no") },
    { label: "Household verdicts", cell: (c) => (c.picks.length ? c.picks.map((p, i) => <Badge key={i}>{p.who}: {p.verdict}</Badge>) : <span className="text-gray-500">—</span>) },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Side by side"
        subtitle={base ? <>Differences are against the cheapest true cost per month, <b>{carName(base)}</b>: what the extra money buys, or doesn&apos;t.</> : "No current price for these cars yet."}
      />
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="bg-gray-900">
              <th className="sticky left-0 z-10 bg-gray-900 p-2 text-left text-xs uppercase text-gray-500">&nbsp;</th>
              {picked.map((c) => (
                <th key={c.id} className="p-2 text-left align-top">
                  <div className="aspect-[16/9] w-full min-w-[12rem] overflow-hidden rounded-md"><CarImage car={c} /></div>
                  <Link href={`/cars/view?id=${encodeURIComponent(c.id)}`} className="mt-2 block font-semibold text-gray-100 hover:underline">{carName(c)}</Link>
                  {base?.id === c.id && <Badge tone="good">cheapest true cost</Badge>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {rows.map((r) => (
              <tr key={r.label}>
                <th className="sticky left-0 z-10 bg-gray-950 p-2 text-left font-medium text-gray-400">{r.label}</th>
                {picked.map((c) => (
                  <td key={c.id} className="p-2 align-top tabular-nums text-gray-200">
                    {r.cell(c)}
                    {r.delta && base && base.id !== c.id && <div className="text-xs">{r.delta(c)}</div>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-500">
        True cost puts cash, PCP, lease and used on one footing over your term (Requirements page), from prices seen in the last {staleDays} days. &quot;Pay monthly&quot; is the cheapest PCP or lease as printed.
      </p>
    </div>
  );
}

function unit(v: number | null | undefined, u: string) {
  return v == null ? "—" : `${num(v)}${u}`;
}

function big(v: number | null | undefined, suffix = "") {
  return v == null ? <span className="text-gray-500">—</span> : <span className="text-lg font-semibold">{gbp(v)}{suffix}</span>;
}

function diffMoney(v: number | null | undefined, base: number | null | undefined) {
  if (v == null || base == null) return null;
  const d = v - base;
  if (d === 0) return null;
  return <span className={d > 0 ? "text-rose-300" : "text-emerald-300"}>{d > 0 ? "+" : "−"}{gbp(Math.abs(d))} vs cheapest</span>;
}

function diffNum(v: number | null | undefined, base: number | null | undefined, unit: string, lowerIsBetter = false) {
  if (v == null || base == null) return null;
  const d = v - base;
  if (d === 0) return <span className="text-gray-500">same</span>;
  const good = lowerIsBetter ? d < 0 : d > 0;
  return <span className={good ? "text-emerald-300" : "text-rose-300"}>{d > 0 ? "+" : "−"}{num(Math.abs(d))}{unit}</span>;
}
