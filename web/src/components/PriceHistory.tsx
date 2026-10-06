"use client";

import { useMemo, useState } from "react";

import { LineChart } from "@/components/charts/LineChart";
import { gbp } from "@/lib/format";
import { lastDays, offerSeries, spanEnd, toMs, type Series } from "@/lib/trends";
import type { SnapshotCar, SnapshotOffer } from "@/lib/types";

import { Empty } from "./ui";

export type Window = 30 | 90 | null;

export function WindowPicker({ value, onChange }: { value: Window; onChange: (w: Window) => void }) {
  const opts: { w: Window; label: string }[] = [{ w: 30, label: "30 days" }, { w: 90, label: "90 days" }, { w: null, label: "All" }];
  return (
    <div role="radiogroup" aria-label="Date range" className="inline-flex overflow-hidden rounded border border-gray-700 text-xs">
      {opts.map((o) => (
        <button
          key={o.label} role="radio" aria-checked={value === o.w} onClick={() => onChange(o.w)}
          className={`px-2.5 py-1 ${value === o.w ? "bg-gray-700 text-gray-100" : "text-gray-400 hover:bg-gray-800"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function routeLabel(o: SnapshotOffer): string {
  const who = o.dealer ?? o.source ?? o.id;
  if (o.finance_type === "pcp") {
    const dep = (o.customer_deposit ?? 0) > 0 ? `, ${gbp(o.customer_deposit)} down` : ", nothing down";
    return `PCP${dep} · ${who}`;
  }
  if (o.finance_type === "pch") return `Lease ${o.profile ?? ""} · ${who}`.replace("  ", " ");
  return who;
}

function clip(series: Series[], days: Window, now: number): Series[] {
  if (days == null) return series;
  const from = now - days * 86_400_000;
  return series
    .map((s) => ({ ...s, segments: s.segments.map((seg) => seg.filter((p) => p.t >= from)).filter((seg) => seg.length) }))
    .filter((s) => s.segments.length);
}

/**
 * Price over time for one car: outright prices by source, and advertised monthly
 * payments by offer, each as a step line through its sightings. The span table
 * underneath is the chart's table twin.
 */
export function PriceHistory({ car, offers }: { car: SnapshotCar; offers: SnapshotOffer[] }) {
  const [win, setWin] = useState<Window>(null);
  const [now] = useState(() => Date.now());
  const cash = useMemo(() => offers.filter((o) => o.finance_type === "cash"), [offers]);
  const monthly = useMemo(() => offers.filter((o) => o.finance_type === "pcp" || o.finance_type === "pch"), [offers]);
  const cashSeries = useMemo(() => clip(offerSeries(cash, "vehicle_price", (o) => o.dealer ?? o.source ?? o.id), win, now), [cash, win, now]);
  const pcpSeries = useMemo(() => offerSeries(monthly.filter((o) => o.finance_type === "pcp"), "monthly_payment", routeLabel), [monthly]);
  const pchSeries = useMemo(() => offerSeries(monthly.filter((o) => o.finance_type === "pch"), "monthly_rental", routeLabel), [monthly]);
  const monthlySeries = useMemo(() => clip([...pcpSeries, ...pchSeries].map((s, i) => ({ ...s, slot: i })), win, now), [pcpSeries, pchSeries, win, now]);
  const listAfterGrant = car.list_price_gbp != null ? car.list_price_gbp - (car.grant_gbp ?? 0) : null;
  const xDomain: [number, number] | undefined = win == null ? undefined : [now - win * 86_400_000, now];

  const spans = useMemo(() => {
    const rows: { label: string; from: number; to: number; value: number; kind: string }[] = [];
    for (const o of offers) {
      for (const h of o.freshness.history) {
        const v = o.finance_type === "cash" ? h.vehicle_price : o.finance_type === "pcp" ? h.monthly_payment : h.monthly_rental;
        if (!h.present || v == null) continue;
        rows.push({ label: routeLabel(o), from: toMs(h.observed_at), to: spanEnd(h), value: v, kind: o.finance_type });
      }
    }
    return lastDays(rows.map((r) => ({ ...r, t: r.to, v: r.value })), win, now).sort((a, b) => b.to - a.to || a.label.localeCompare(b.label));
  }, [offers, win, now]);

  if (!offers.length) return <Empty>No offers observed for this trim yet.</Empty>;
  const fmtDay = (ms: number) => new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-400">
        <WindowPicker value={win} onChange={setWin} />
        <span>A line holds its level between the sightings that confirmed it and breaks where the offer was gone.</span>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-1 text-sm font-medium text-gray-200">Buy outright</h3>
          <LineChart series={cashSeries} format={(v) => gbp(v)} height={220}
            reference={listAfterGrant != null ? { value: listAfterGrant, label: "list after grant" } : null}
            xDomain={xDomain} empty="No cash prices seen in this range." />
        </div>
        <div>
          <h3 className="mb-1 text-sm font-medium text-gray-200">Monthly payment as advertised</h3>
          <LineChart series={monthlySeries} format={(v) => `${gbp(v)}/mo`} height={220} xDomain={xDomain}
            empty="No finance offers seen in this range." />
          <p className="mt-1 text-xs text-gray-500">As the seller states it: a PCP with a deposit and a lease with an initial rental are not the same money. The price board below normalises them.</p>
        </div>
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer text-gray-400">Every sighting as a table ({spans.length})</summary>
        <table className="mt-2 w-full text-xs">
          <thead className="text-left uppercase text-gray-500">
            <tr><th className="py-1 pr-3">Offer</th><th className="py-1 pr-3">Seen from</th><th className="py-1 pr-3">Last confirmed</th><th className="py-1 text-right">Value</th></tr>
          </thead>
          <tbody>
            {spans.map((r, i) => (
              <tr key={i} className="border-t border-gray-800">
                <td className="py-1 pr-3 text-gray-300">{r.label}</td>
                <td className="py-1 pr-3 text-gray-400">{fmtDay(r.from)}</td>
                <td className="py-1 pr-3 text-gray-400">{fmtDay(r.to)}</td>
                <td className="py-1 text-right tabular-nums text-gray-200">{r.kind === "cash" ? gbp(r.value) : `${gbp(r.value)}/mo`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
