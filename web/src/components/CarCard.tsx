"use client";

import Link from "next/link";

import { CarImage } from "@/components/CarImage";
import { Sparkline } from "@/components/charts/Sparkline";
import { Badge } from "@/components/ui";
import type { Brief } from "@/lib/brief";
import { budgetGap, IONIQ5_WIDTH_MM, ROUTE_SHORT, ROUTES, type CarCosts } from "@/lib/costs";
import { carName, gbp, num } from "@/lib/format";
import type { CashTrend, SnapshotCar } from "@/lib/types";

interface Props {
  car: SnapshotCar;
  costs: CarCosts;
  brief: Brief;
  ceiling: number | null;
  starred: boolean;
  onStar: () => void;
  compared: boolean;
  onCompare: () => void;
}

const VERDICT_TONE: Record<string, "good" | "warn" | "bad" | "muted"> = { want: "good", maybe: "warn", no: "bad", control: "muted" };

const seen = (days: number | null | undefined) => (days == null ? "" : days === 0 ? "seen today" : `seen ${days}d ago`);

/**
 * One car. The cost block shows every route the car can be had by, on one
 * footing (true £ per month, with what the car is expected to be worth at the
 * end of the term), the cheapest marked; then what you would actually pay.
 */
export function CarCard({ car, costs, brief, ceiling, starred, onStar, compared, onCompare }: Props) {
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
        <button
          onClick={onStar}
          aria-label={starred ? "Remove from my shortlist" : "Add to my shortlist"}
          className={`absolute right-2 top-2 rounded-full bg-gray-950/70 px-2 py-0.5 text-lg ${starred ? "text-amber-300" : "text-gray-400 hover:text-gray-100"}`}
        >
          {starred ? "★" : "☆"}
        </button>
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
          <li><span className="text-gray-500">charge</span> {car.dc_peak_kw ? `${num(car.dc_peak_kw)} kW` : "—"}</li>
          <li title="width versus the Ioniq 5 (1,890 mm)">
            <span className="text-gray-500">width</span>{" "}
            {widthDelta == null ? "—" : widthDelta === 0 ? "same as Ioniq 5" : widthDelta < 0 ? `${-widthDelta} mm narrower` : `${widthDelta} mm wider`}
          </li>
        </ul>

        <div className="flex flex-wrap gap-1.5" title={brief.status === "unknown" ? `Not confirmed: ${brief.unknownLabels.join(", ")}` : undefined}>
          {brief.rules.map((t) => (
            <Badge key={t.id} tone={t.ok === true ? "good" : t.ok === false ? "bad" : "muted"}>
              {t.ok === true ? "✓" : t.ok === false ? "✗" : "?"} {t.label}
            </Badge>
          ))}
        </div>

        <div className="mt-auto rounded-lg border border-gray-800 bg-gray-950/60 p-3">
          {routes.length ? (
            <>
              <div className="flex items-baseline justify-between gap-2">
                <div title="True cost per month: every payment discounted at the savings rate, the car's expected value at the end credited back, spread over the agreement.">
                  <span className="text-2xl font-semibold tabular-nums text-gray-100">{gbp(costs.trueCost!.monthly)}</span>
                  <span className="text-sm text-gray-400">/mo true cost</span>
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
                    return (
                      <tr key={r} className={best ? "text-gray-100" : "text-gray-400"}>
                        <td className="py-0.5 pr-2 font-medium">{ROUTE_SHORT[r]}</td>
                        <td className="py-0.5 pr-2 text-right tabular-nums">{gbp(t.monthly)}/mo</td>
                        <td className="py-0.5 pr-2 text-right tabular-nums" title="What the source printed">{t.headline != null ? (r === "cash" || r === "used" ? gbp(t.headline) : `${gbp(t.headline)}/mo`) : "—"}</td>
                        <td className="py-0.5 text-right tabular-nums text-gray-500" title="Expected value of the car at the end of the term under this route">
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
              {car.deal_summary.trend && car.deal_summary.trend.spark.length >= 2 && (
                <Sparkline points={car.deal_summary.trend.spark.map(([d, v]) => ({ t: Date.parse(`${d}T00:00:00Z`), v }))} title={`Best outright price, last ${car.deal_summary.trend.spark.length} readings`} />
              )}
            </div>
          )}
          {car.deal_summary.trend && <MovementLine m={car.deal_summary.trend} />}
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

function MovementLine({ m }: { m: CashTrend }) {
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
