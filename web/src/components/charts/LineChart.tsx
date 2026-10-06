"use client";

import { useId, useMemo, useState } from "react";

import type { Series } from "@/lib/trends";

import { GRID, INK, SURFACE, seriesColor } from "./palette";
import { dateTicks, longDate, niceTicks, shortDate } from "./scales";
import { useMeasure } from "./useMeasure";

interface Props {
  series: Series[];
  /** Formats a y value for ticks, labels and the tooltip. */
  format: (v: number) => string;
  height?: number;
  /** Draw a horizontal reference (e.g. the list price or the budget line). */
  reference?: { value: number; label: string } | null;
  /** Fix the x range (ms); defaults to the data's own. */
  xDomain?: [number, number];
  /** Caption shown when there is nothing to draw. */
  empty?: string;
}

const M = { top: 12, right: 16, bottom: 26, left: 56 };
const LABEL_W = 48; // room for a direct end-label

/**
 * Multi-series step/line chart: 2px lines, >=8px end markers with a surface ring,
 * hairline grid, a legend for two or more series, direct end-labels for up to
 * four, and a crosshair tooltip that reads every series at the snapped date.
 * Every value is also in the table the caller renders alongside.
 */
export function LineChart({ series, format, height = 220, reference = null, xDomain, empty = "Nothing to draw yet." }: Props) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  const id = useId();

  const geom = useMemo(() => {
    const pts = series.flatMap((s) => s.segments.flat());
    if (!pts.length) return null;
    let x0 = xDomain?.[0] ?? Math.min(...pts.map((p) => p.t));
    let x1 = xDomain?.[1] ?? Math.max(...pts.map((p) => p.t));
    if (x1 === x0) { x0 -= 86_400_000; x1 += 86_400_000; }
    const vs = pts.map((p) => p.v).concat(reference ? [reference.value] : []);
    let y0 = Math.min(...vs), y1 = Math.max(...vs);
    const pad = (y1 - y0) * 0.1 || Math.abs(y0) * 0.05 || 1;
    y0 -= pad; y1 += pad;
    const yTicks = niceTicks(y0, y1, 4);
    if (yTicks.length) { y0 = Math.min(y0, yTicks[0]); y1 = Math.max(y1, yTicks[yTicks.length - 1]); }
    const xs = Array.from(new Set(pts.map((p) => p.t))).sort((a, b) => a - b);
    return { x0, x1, y0, y1, yTicks, xTicks: dateTicks(x0, x1, Math.max(2, Math.floor(width / 110))), xs };
  }, [series, reference, xDomain, width]);

  if (!geom || width === 0) {
    return <div ref={ref} className="text-sm text-gray-500" style={{ minHeight: geom ? height : undefined }}>{geom ? "" : empty}</div>;
  }
  const W = width, H = height;
  const labelled = series.length <= 4;
  const right = M.right + (labelled ? LABEL_W : 0);
  const iw = W - M.left - right, ih = H - M.top - M.bottom;
  const sx = (t: number) => M.left + ((t - geom.x0) / (geom.x1 - geom.x0)) * iw;
  const sy = (v: number) => M.top + ih - ((v - geom.y0) / (geom.y1 - geom.y0)) * ih;
  const span = geom.x1 - geom.x0;

  const active = focus ?? hover;
  const readAt = (s: Series, t: number): number | null => {
    for (const seg of s.segments) {
      if (t < seg[0].t || t > seg[seg.length - 1].t) continue;
      let v = seg[0].v;
      for (const p of seg) { if (p.t <= t) v = p.v; else break; }
      return v;
    }
    return null;
  };
  const snap = (clientX: number, el: SVGSVGElement) => {
    const r = el.getBoundingClientRect();
    const t = geom.x0 + ((clientX - r.left - M.left) / iw) * span;
    let best = geom.xs[0];
    for (const x of geom.xs) if (Math.abs(x - t) < Math.abs(best - t)) best = x;
    return best;
  };
  const rows = active == null ? [] : series.map((s) => ({ s, v: readAt(s, active) })).filter((r) => r.v != null) as { s: Series; v: number }[];
  const tipX = active == null ? 0 : sx(active);
  const tipLeft = tipX > W * 0.6;

  return (
    <div ref={ref} className="relative">
      <svg
        width={W} height={H} role="img" aria-labelledby={`${id}-t`} tabIndex={0}
        className="block select-none outline-none focus-visible:ring-1 focus-visible:ring-blue-500"
        onPointerMove={(e) => setHover(snap(e.clientX, e.currentTarget))}
        onPointerLeave={() => setHover(null)}
        onKeyDown={(e) => {
          const i = geom.xs.indexOf(focus ?? geom.xs[geom.xs.length - 1]);
          if (e.key === "ArrowLeft") { setFocus(geom.xs[Math.max(0, i - 1)]); e.preventDefault(); }
          if (e.key === "ArrowRight") { setFocus(geom.xs[Math.min(geom.xs.length - 1, i + 1)]); e.preventDefault(); }
          if (e.key === "Escape") setFocus(null);
        }}
        onBlur={() => setFocus(null)}
      >
        <title id={`${id}-t`}>{series.map((s) => s.label).join(", ")} over time</title>
        {geom.yTicks.map((v) => (
          <g key={v}>
            <line x1={M.left} x2={W - right} y1={sy(v)} y2={sy(v)} stroke={GRID} strokeWidth={1} />
            <text x={M.left - 8} y={sy(v)} dy="0.35em" textAnchor="end" fontSize={11} fill={INK.muted} className="tabular-nums">{format(v)}</text>
          </g>
        ))}
        {geom.xTicks.map((t) => (
          <text key={t} x={sx(t)} y={H - 8} textAnchor="middle" fontSize={11} fill={INK.muted}>{shortDate(t, span)}</text>
        ))}
        <line x1={M.left} x2={W - right} y1={M.top + ih} y2={M.top + ih} stroke={GRID} strokeWidth={1} />
        {reference && (
          <g>
            <line x1={M.left} x2={W - right} y1={sy(reference.value)} y2={sy(reference.value)} stroke={INK.muted} strokeWidth={1} />
            <text x={W - right} y={sy(reference.value) - 4} textAnchor="end" fontSize={10} fill={INK.muted}>{reference.label}</text>
          </g>
        )}
        {series.map((s) => {
          const color = seriesColor(s.slot);
          return (
            <g key={s.id}>
              {s.segments.map((seg, i) => (
                <g key={i}>
                  <path d={seg.map((p, j) => `${j ? "L" : "M"}${sx(p.t).toFixed(1)},${sy(p.v).toFixed(1)}`).join(" ")}
                        fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                  {seg.length === 1 && <circle cx={sx(seg[0].t)} cy={sy(seg[0].v)} r={4} fill={color} stroke={SURFACE} strokeWidth={2} />}
                </g>
              ))}
              {(() => {
                const last = s.segments[s.segments.length - 1];
                const p = last[last.length - 1];
                return (
                  <g>
                    <circle cx={sx(p.t)} cy={sy(p.v)} r={4} fill={color} stroke={SURFACE} strokeWidth={2} />
                    {labelled && (
                      <text x={sx(p.t) + 7} y={sy(p.v)} dy="0.35em" fontSize={11} fill={INK.secondary} className="tabular-nums">{format(p.v)}</text>
                    )}
                  </g>
                );
              })()}
            </g>
          );
        })}
        {active != null && (
          <g>
            <line x1={tipX} x2={tipX} y1={M.top} y2={M.top + ih} stroke={INK.muted} strokeWidth={1} />
            {rows.map(({ s, v }) => (
              <circle key={s.id} cx={tipX} cy={sy(v)} r={4} fill={seriesColor(s.slot)} stroke={SURFACE} strokeWidth={2} />
            ))}
          </g>
        )}
      </svg>
      {active != null && rows.length > 0 && (
        <div
          className="pointer-events-none absolute top-2 z-10 rounded border border-gray-700 bg-gray-950/95 px-2.5 py-1.5 text-xs shadow"
          style={tipLeft ? { right: W - tipX + 10 } : { left: tipX + 10 }}
        >
          <div className="mb-1 text-gray-400">{longDate(active)}</div>
          {rows.sort((a, b) => a.v - b.v).map(({ s, v }) => (
            <div key={s.id} className="flex items-center gap-2">
              <span className="inline-block h-0.5 w-3 rounded" style={{ background: seriesColor(s.slot) }} aria-hidden />
              <span className="font-semibold tabular-nums text-gray-100">{format(v)}</span>
              <span className="text-gray-400">{s.label}</span>
            </div>
          ))}
        </div>
      )}
      {series.length > 1 && (
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-400">
          {series.map((s) => (
            <li key={s.id} className="flex items-center gap-1.5">
              <span className="inline-block h-0.5 w-4 rounded" style={{ background: seriesColor(s.slot) }} aria-hidden />
              {s.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
