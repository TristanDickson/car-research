"use client";

import Link from "next/link";

import { CarImage } from "@/components/CarImage";
import { Sparkline } from "@/components/charts/Sparkline";
import { Badge } from "@/components/ui";
import { budgetGap, IONIQ5_WIDTH_MM, ROUTE_SHORT, ROUTES, type CarCosts, type TrueCost } from "@/lib/costs";
import { carName, gbp, num } from "@/lib/format";
import type { Trend } from "@/lib/model/sightings";
import type { SearchPack } from "@/lib/query";
import type { SnapshotCar } from "@/lib/types";

interface Props {
  car: SnapshotCar;
  costs: CarCosts;
  /** Packs the search's equipment needs on this car, priced. */
  packs?: SearchPack[];
  flagLabels?: Record<string, string>;
  ceiling: number | null;
  /** The reader's term, the months every comparable figure is spread over. */
  horizon: number;
  compared: boolean;
  onCompare: () => void;
}

const VERDICT_TONE: Record<string, "good" | "warn" | "bad" | "muted"> = { want: "good", maybe: "warn", no: "bad", control: "muted" };

const seen = (days: number | null | undefined) => (days == null ? "" : days === 0 ? "seen today" : `seen ${days}d ago`);

/** The deal as the source printed it, in a few words. */
export function printed(t: TrueCost): string {
  const d = t.terms;
  switch (t.route) {
    case "pcp": return `${gbp(d.monthly)} × ${d.payments ?? "?"}${d.derived ? "*" : ""}${d.deposit ? `, ${gbp(d.deposit)} down` : ", £0 down"}${d.gfv ? `, GFV ${gbp(d.gfv)}` : ""}`;
    case "pch": return `${gbp(d.monthly)} × ${d.rentals ?? "?"}${d.initial ? `, ${gbp(d.initial)} up front` : ""}${d.term_months ? `, ${d.term_months} mo` : ""}`;
    case "cash": return `${gbp(d.price)} outright`;
    case "used": return `${gbp(d.price)}${d.year ? `, ${d.year}` : ""}${d.mileage != null ? `, ${num(d.mileage)} mi` : ""}`;
  }
}

/** What the comparable figure assumes when the deal's length is not the reader's term; null when it is. */
export function atHorizonNote(t: TrueCost, horizon: number): string | null {
  switch (t.atHorizon) {
    case "settle_early": return `${t.ownHorizonMonths}-month deal settled at month ${horizon}, car sold`;
    case "balloon_then_keep": return `${t.ownHorizonMonths}-month deal; balloon paid, car kept to month ${horizon} and sold`;
    case "lease_ends": return `${t.ownHorizonMonths}-month lease; the same cost per month assumed to continue`;
    case "lease_cut": return `${t.ownHorizonMonths}-month lease; the rentals within ${horizon} months`;
    default: return null;
  }
}

/**
 * One car. The cost block shows every route the car can be had by, on one
 * footing (true £ per month over the reader's horizon, with what the car is
 * expected to be worth at the end), the cheapest marked; then the deal as the
 * source printed it.
 */
export function CarCard({ car, costs, packs = [], flagLabels = {}, ceiling, horizon, compared, onCompare }: Props) {
  const gap = budgetGap(costs.trueCost?.monthly ?? costs.monthly, ceiling);
  const widthDelta = car.width_mm != null ? car.width_mm - IONIQ5_WIDTH_MM : null;
  const routes = ROUTES.filter((r) => costs.byRoute[r]);

  return (
    <article className={`flex flex-col overflow-hidden rounded-xl border bg-gray-900 ${compared ? "border-blue-700" : "border-gray-800"}`}>
      <div className="relative aspect-[16/9] w-full">
        <CarImage car={car} />
        <div className="absolute left-2 top-2 flex gap-1">
          {car.picks.map((p, i) => (
            <Badge key={i} tone={VERDICT_TONE[p.verdict] ?? "muted"} title={p.note ?? undefined}>
              {p.who}: {p.verdict}
            </Badge>
          ))}
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <div>
          <div className="flex items-baseline justify-between gap-2">
            <Link href={`/cars/view?id=${encodeURIComponent(car.id)}`} className="text-base font-semibold text-gray-100 hover:underline">
              {carName(car)}
            </Link>
            {costs.sources > 0 && (
              <span className="shrink-0 text-xs tabular-nums text-gray-500" title="Sources with a current price for this car">
                {costs.sources} source{costs.sources === 1 ? "" : "s"}
              </span>
            )}
          </div>
          <div className="text-xs text-gray-500">
            {car.packs?.length ? car.packs.join(" + ") : car.used ? "used" : car.body ?? ""}
            {car.model_year ? `${car.packs?.length || car.used || car.body ? " · " : ""}${car.model_year}` : ""}
          </div>
        </div>

        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-gray-300">
          <li><span className="text-gray-500">seats</span> {num(car.seats)}</li>
          <li><span className="text-gray-500">range</span> {car.wltp_range_mi != null ? `${num(car.wltp_range_mi)} mi` : "—"}</li>
          <li><span className="text-gray-500">battery</span> {car.battery_kwh != null ? `${num(car.battery_kwh, 0)} kWh` : "—"}</li>
          <li title={car.dc_peak_kw ? "DC peak" : "DC 10–80% average (EV Database)"}><span className="text-gray-500">charge</span> {car.dc_peak_kw ? `${num(car.dc_peak_kw)} kW` : car.dc_avg_kw ? `${num(car.dc_avg_kw)} kW avg` : "—"}</li>
          <li title="width versus the Ioniq 5 (1,890 mm)">
            <span className="text-gray-500">width</span>{" "}
            {widthDelta == null ? "—" : widthDelta === 0 ? "same as Ioniq 5" : widthDelta < 0 ? `${-widthDelta} mm narrower` : `${widthDelta} mm wider`}
          </li>
        </ul>

        {packs.length > 0 && (
          <div className="text-xs text-amber-200/80" title="Equipment the search asks for comes on this car only in these packs; the prices are what the configurator asks.">
            needs {packs.map((p) => `${p.pack}${p.price != null ? ` (${gbp(p.price)})` : ""} for ${flagLabels[p.flag] ?? p.flag.replaceAll("_", " ")}`).join(", ")}
          </div>
        )}

        <div className="mt-auto rounded-lg border border-gray-800 bg-gray-950/60 p-3">
          {routes.length ? (
            <>
              <div className="flex items-baseline justify-between gap-2">
                <div title={`True cost per month over ${horizon} months: every payment discounted at your savings rate, the car's expected value at the end credited back.`}>
                  <span className="text-2xl font-semibold tabular-nums text-gray-100">{gbp(costs.trueCost!.monthly)}</span>
                  <span className="text-sm text-gray-400">/mo over {horizon} mo</span>
                </div>
                {gap != null && (
                  <Badge tone={gap <= 0 ? "good" : "warn"}>{gap <= 0 ? "within budget" : `+${gbp(gap)} over`}</Badge>
                )}
              </div>
              <table className="mt-2 w-full text-xs">
                <tbody>
                  {routes.map((r) => {
                    const t = costs.byRoute[r]!;
                    const best = t.route === costs.trueCost?.route;
                    const note = atHorizonNote(t, horizon);
                    return (
                      <tr key={r} className={best ? "text-gray-100" : "text-gray-400"} title={[`${t.sourceName}${t.dealer && t.dealer !== t.sourceName ? ` · ${t.dealer}` : ""}`, note].filter(Boolean).join(" · ")}>
                        <td className="py-0.5 pr-2 font-medium">{ROUTE_SHORT[r]}</td>
                        <td className="py-0.5 pr-2 text-right tabular-nums">{gbp(t.monthly)}/mo</td>
                        <td className="py-0.5 pr-2 text-right text-gray-500" title="The deal as the source printed it">{printed(t)}</td>
                        <td className="py-0.5 text-right tabular-nums text-gray-500" title="Expected value of the car at the end under this route">
                          {t.endValue != null ? `worth ${gbp(t.endValue)} at end` : ""}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          ) : (
            <div className="text-sm text-gray-500">No current price to cost.</div>
          )}
          {costs.cash && (
            <div className="mt-2 flex items-center justify-between gap-2 border-t border-gray-800 pt-2 text-sm text-gray-300">
              <div>
                Buy outright: <b className="tabular-nums">{gbp(costs.cash.price)}</b>
                <span className="text-xs text-gray-500">{costs.cash.dealer ? ` · ${costs.cash.dealer}` : ""}{costs.cash.ageDays != null ? ` · ${seen(costs.cash.ageDays)}` : ""}</span>
              </div>
              {costs.trend && costs.trend.spark.length >= 2 && (
                <Sparkline points={costs.trend.spark.map(([d, v]) => ({ t: Date.parse(`${d}T00:00:00Z`), v }))} title={`Best outright price, last ${costs.trend.spark.length} readings`} />
              )}
            </div>
          )}
          {costs.trend && <MovementLine m={costs.trend} />}
        </div>

        <div className="flex items-center justify-between text-sm">
          <label className="flex items-center gap-2 text-gray-300">
            <input type="checkbox" checked={compared} onChange={onCompare} /> Compare
          </label>
          <Link href={`/cars/view?id=${encodeURIComponent(car.id)}`} className="text-gray-400 hover:text-gray-100">
            Details and every price →
          </Link>
        </div>
      </div>
    </article>
  );
}

function MovementLine({ m }: { m: Trend }) {
  const day = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
  const d = m.delta;
  if (d == null) return <div className="text-xs text-gray-500">first seen {day(m.first_at)}; no earlier price to compare</div>;
  const held = `at this price ${m.days_at_now} day${m.days_at_now === 1 ? "" : "s"}`;
  return (
    <div className="text-xs">
      {d === 0 ? (
        <span className="text-gray-500">unchanged over {m.window_days} days · {held}</span>
      ) : (
        <span className={d < 0 ? "text-emerald-300" : "text-amber-300"}>
          {d < 0 ? "down" : "up"} {gbp(Math.abs(d))} over {m.window_days} days<span className="text-gray-500"> · {held}</span>
        </span>
      )}
    </div>
  );
}
