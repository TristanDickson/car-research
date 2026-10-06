import type { Pt } from "@/lib/trends";

import { ACCENT, DE_EMPHASIS, SURFACE } from "./palette";

/**
 * Stat-tile sparkline: the body in the de-emphasis grey, the current point in the
 * accent. No axes, no tooltip; the number beside it is the value.
 */
export function Sparkline({ points, width = 96, height = 24, title }: { points: Pt[]; width?: number; height?: number; title?: string }) {
  if (points.length < 2) return null;
  const xs = points.map((p) => p.t), ys = points.map((p) => p.v);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const pad = 4;
  const sx = (t: number) => pad + ((t - x0) / (x1 - x0 || 1)) * (width - 2 * pad);
  const sy = (v: number) => pad + (1 - (v - y0) / (y1 - y0)) * (height - 2 * pad);
  const d = points.map((p, i) => `${i ? "L" : "M"}${sx(p.t).toFixed(1)},${sy(p.v).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  return (
    <svg width={width} height={height} role="img" aria-label={title} className="shrink-0">
      {title && <title>{title}</title>}
      <path d={d} fill="none" stroke={DE_EMPHASIS} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={sx(last.t)} cy={sy(last.v)} r={3.5} fill={ACCENT} stroke={SURFACE} strokeWidth={2} />
    </svg>
  );
}
