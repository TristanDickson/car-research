"use client";

import { useMemo, useState } from "react";

import { atHorizonNote, printed } from "@/components/CarCard";
import { LineChart } from "@/components/charts/LineChart";
import { OfferTable } from "@/components/OfferTable";
import { WindowPicker, type Window } from "@/components/PriceHistory";
import { Badge, Card, Empty } from "@/components/ui";
import { ROUTE_LABEL, ROUTE_SHORT, ROUTES, type CarCosts } from "@/lib/costs";
import { gbp, num } from "@/lib/format";
import { useOffersForCar, useResidualsForModel, useSeriesForCar, useUsedForModel } from "@/lib/hooks";
import type { UsedStock } from "@/lib/model/sightings";
import { clipChart, latestOf, seriesToChart, type Measure } from "@/lib/trends";
import type { Route, SnapshotCar, SnapshotUsed } from "@/lib/types";

const DAY = 86_400_000;
const day = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit", timeZone: "UTC" });

/**
 * Everything about what the car costs, under one route selector: the cheapest
 * figure per route with its end value and the deal as printed, then for the
 * chosen route the true cost over time by source, the price as printed over
 * time, and a ranked list of every current source. Buying used reads the
 * model's listings; the residual evidence sits with it. Nothing is costed
 * here: every figure comes from the stored results of lib/model, computed
 * under the reader's basis.
 */
export function Pricing({ car, costs, horizon, sources, staleDays }: { car: SnapshotCar; costs: CarCosts; horizon: number; sources: Record<string, string>; staleDays: number }) {
  const series = useSeriesForCar(car);
  const offers = useOffersForCar(car.id);
  const used = useUsedForModel(car.model_key ?? null);
  const residuals = useResidualsForModel(car.model_key ?? null);
  const [route, setRoute] = useState<Route | null>(null);
  const [win, setWin] = useState<Window>(null);
  const [now] = useState(() => Date.now());
  const name = (s: string) => sources[s] ?? s;

  const available = ROUTES.filter((r) => costs.byRoute[r] || series.data?.some((s) => s.route === r));
  const active: Route | null = route && available.includes(route) ? route : costs.trueCost?.route ?? available[0] ?? null;
  const rows = (series.data ?? []).filter((s) => s.route === active);
  const from = win == null ? null : now - win * DAY;
  const firstAt = Math.min(now, ...rows.flatMap((r) => r.points.map((p) => Date.parse(`${p.from}T00:00:00Z`))));
  const xDomain: [number, number] = [from ?? firstAt, now];
  const chart = (measure: Measure) => clipChart(seriesToChart(rows, measure, (s) => name(s.source)), from);
  const latest = rows.map((r) => ({ r, l: latestOf(r, "true") })).sort((a, b) => (a.l?.v ?? Infinity) - (b.l?.v ?? Infinity));

  const routeOffers = (offers.data ?? []).filter((o) => o.finance_type === active);
  const byYear = [...(residuals.data ?? [])].sort((a, b) => b.year - a.year);

  return (
    <Card title="Price">
      <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {ROUTES.map((r) => {
          const t = costs.byRoute[r];
          const best = t && t.route === costs.trueCost?.route;
          const on = r === active;
          const note = t ? atHorizonNote(t, horizon) : null;
          return (
            <button key={r} onClick={() => setRoute(r)} disabled={!available.includes(r)}
              className={`rounded-lg border p-3 text-left disabled:opacity-40 ${on ? "border-sky-600 bg-sky-950/30" : "border-gray-800 bg-gray-950/60 hover:border-gray-600"}`}>
              <div className="flex items-baseline justify-between">
                <span className="text-xs uppercase tracking-wide text-gray-400">{ROUTE_SHORT[r]}</span>
                {best && <Badge tone="good">cheapest</Badge>}
              </div>
              {t ? (
                <>
                  <div className="mt-1 text-xl font-semibold tabular-nums text-gray-100">{gbp(t.monthly)}<span className="text-sm font-normal text-gray-400">/mo over {t.horizonMonths} mo</span></div>
                  <div className="text-xs text-gray-300">{printed(t)}</div>
                  <div className="text-xs text-gray-500">{t.sourceName}{t.dealer && t.dealer !== t.sourceName ? ` · ${t.dealer}` : ""}</div>
                  <div className="text-xs text-gray-500">{t.endValue != null ? `worth ${gbp(t.endValue)} at the end (${t.residualSource ?? "?"})` : "nothing comes back"}</div>
                  {note && <div className="mt-1 text-[11px] text-amber-200/80">{note}{t.ownMonthly != null && t.ownMonthly !== t.monthly ? `; ${gbp(t.ownMonthly)}/mo over its own ${t.ownHorizonMonths} mo` : ""}</div>}
                </>
              ) : (
                <div className="mt-1 text-sm text-gray-500">{available.includes(r) ? "no current figure; history below" : "nothing seen"}</div>
              )}
            </button>
          );
        })}
      </div>

      {active && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="font-medium text-gray-100">{ROUTE_LABEL[active]}</span>
            <WindowPicker value={win} onChange={setWin} />
            <span className="text-gray-500">{active === "used" ? "the model's cheapest used example on each day, per site" : "one line per source"}</span>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">True £ per month over time</div>
              <LineChart series={chart("true")} format={(v) => gbp(v)} height={200} xDomain={xDomain} empty="Nothing sighted in this range." />
            </div>
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">{active === "cash" || active === "used" ? "Price as printed over time" : "Monthly as printed over time"}</div>
              <LineChart series={chart("headline")} format={(v) => gbp(v)} height={200} xDomain={xDomain} empty="Nothing sighted in this range." />
            </div>
          </div>

          <div>
            <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">Sources, cheapest first</div>
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-gray-500">
                <tr><th className="py-1 pr-3">Source</th><th className="py-1 pr-3 text-right">True £/mo</th><th className="py-1 pr-3">As printed</th><th className="py-1 pr-3">End value from</th><th className="py-1 pr-3">Seller</th><th className="py-1">Last confirmed</th></tr>
              </thead>
              <tbody>
                {latest.map(({ r, l }) => (
                  <tr key={r.id} className="border-t border-gray-800">
                    <td className="py-1 pr-3">{name(r.source)}{active === "used" && l?.point.n ? <span className="text-xs text-gray-500"> · {l.point.n} on sale</span> : null}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{l?.point.true_monthly != null ? gbp(l.point.true_monthly) : "—"}<span className="text-xs text-gray-500">{l ? ` / ${l.point.horizon_months} mo` : ""}</span></td>
                    <td className="py-1 pr-3 text-xs text-gray-300">{l ? printed({ route: active, terms: l.point.terms } as Parameters<typeof printed>[0]) : "—"}</td>
                    <td className="py-1 pr-3 text-xs text-gray-400">{l?.point.residual_source ?? "—"}</td>
                    <td className="py-1 pr-3 text-xs text-gray-400">{l?.point.seller ?? "—"}</td>
                    <td className="py-1 text-xs text-gray-400">{l ? day(l.point.to) : "—"}</td>
                  </tr>
                ))}
                {latest.length === 0 && <tr><td colSpan={6} className="py-2 text-gray-500">No sighting on this route yet.</td></tr>}
              </tbody>
            </table>
          </div>

          {active !== "used" && (
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">Every {ROUTE_LABEL[active]} offer observed · {routeOffers.length}</div>
              {routeOffers.length ? (
                <OfferTable offers={routeOffers} cars={new Map([[car.id, car]])} staleDays={staleDays} showCar={false} defaultSort={{ key: "true", dir: "asc" }} horizon={horizon} />
              ) : (
                <Empty>No {ROUTE_LABEL[active]} offer observed for this derivative.</Empty>
              )}
            </div>
          )}

          {active === "used" && (
            <UsedStockView car={car} listings={used.data ?? []} stock={costs.stock} byYear={byYear} />
          )}
        </div>
      )}
    </Card>
  );
}

function UsedStockView({ car, listings, stock, byYear }: { car: SnapshotCar; listings: SnapshotUsed[]; stock: UsedStock | null; byYear: { year: number; points: { date: string; median: number; n: number }[] }[] }) {
  const [all, setAll] = useState(false);
  const live = useMemo(() => listings.filter((l) => l.present && l.price_gbp != null).sort((a, b) => (a.price_gbp ?? 0) - (b.price_gbp ?? 0)), [listings]);
  const shown = all ? live : live.slice(0, 25);
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_minmax(18rem,24rem)]">
      <div>
        <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">
          {car.make} {car.model} on sale used · {live.length} listing{live.length === 1 ? "" : "s"}{stock?.sources ? ` · ${Object.entries(stock.sources).map(([s, n]) => `${s} ${n}`).join(", ")}` : ""}{stock ? ` · ${stock.count} distinct cars` : ""}
        </div>
        {live.length === 0 ? (
          <Empty>No used example of this model on the sites we read.</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-gray-500">
              <tr><th className="py-1 pr-3 text-right">Price</th><th className="py-1 pr-3">Year</th><th className="py-1 pr-3 text-right">Miles</th><th className="py-1 pr-3">Derivative</th><th className="py-1 pr-3">Where</th><th className="py-1">Source</th></tr>
            </thead>
            <tbody>
              {shown.map((l) => (
                <tr key={l.listing_key} className="border-t border-gray-800">
                  <td className="py-1 pr-3 text-right tabular-nums text-gray-100">{gbp(l.price_gbp)}</td>
                  <td className="py-1 pr-3">{l.year ?? "—"}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{l.mileage != null ? num(l.mileage) : "—"}</td>
                  <td className="py-1 pr-3 text-xs text-gray-300">{l.derivative ?? "—"}</td>
                  <td className="py-1 pr-3 text-xs text-gray-400">{l.town ?? "—"}</td>
                  <td className="py-1 text-xs">{l.url ? <a href={l.url} target="_blank" rel="noreferrer" className="text-gray-300 underline">{l.source ?? l.provider}</a> : (l.source ?? l.provider)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {live.length > shown.length && (
          <button onClick={() => setAll(true)} className="mt-2 text-xs text-gray-400 underline hover:text-gray-100">show all {live.length}</button>
        )}
      </div>
      <div>
        <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">What a used one is worth, by registration year</div>
        {stock?.by_year && Object.keys(stock.by_year).length > 0 ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-gray-500"><tr><th className="py-1 pr-3">Year</th><th className="py-1 pr-3 text-right">On sale</th><th className="py-1 pr-3 text-right">From</th><th className="py-1 pr-3 text-right">Median</th><th className="py-1 text-right">Since first reading</th></tr></thead>
            <tbody>
              {Object.entries(stock.by_year).sort((a, b) => Number(b[0]) - Number(a[0])).map(([y, v]) => {
                const hist = byYear.find((r) => r.year === Number(y));
                const d = hist && hist.points.length > 1 ? hist.points[hist.points.length - 1].median - hist.points[0].median : null;
                return (
                  <tr key={y} className="border-t border-gray-800">
                    <td className="py-1 pr-3">{y}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{v.n}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{gbp(v.min)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{gbp(v.median)}</td>
                    <td className={`py-1 text-right text-xs tabular-nums ${d == null ? "text-gray-500" : d < 0 ? "text-amber-300" : d > 0 ? "text-emerald-300" : "text-gray-400"}`}>
                      {d == null ? (hist ? `since ${day(hist.points[0].date)}` : "—") : d === 0 ? "unchanged" : `${d < 0 ? "−" : "+"}${gbp(Math.abs(d))}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <Empty>Not enough examples yet.</Empty>
        )}
        {stock?.residual && (
          <p className="mt-2 text-xs text-gray-500">
            The {stock.residual.year} median ({gbp(stock.residual.value)}, {stock.residual.n} cars, the same car on two sites counted once) is the end-of-term value behind this car&apos;s PCP equity and outright cost. Older years are what the used route itself will be worth later.
          </p>
        )}
      </div>
    </div>
  );
}
