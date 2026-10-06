// Chart colours for the app's dark surface (gray-900 #111827), validated with the
// dataviz palette checker: lightness band, chroma, CVD separation, 3:1 contrast.
// Slots are assigned by entity (sorted offer id), never by rank, so filtering
// never repaints a line.
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"] as const;
export const DE_EMPHASIS = "#6b7280"; // gray-500: sparkline body, context lines
export const ACCENT = SERIES[0];
export const GRID = "#1f2937"; // gray-800 hairlines
export const SURFACE = "#111827"; // gray-900: the ring around markers
export const INK = { primary: "#f3f4f6", secondary: "#9ca3af", muted: "#6b7280" } as const;

export function seriesColor(slot: number): string {
  return SERIES[slot % SERIES.length];
}
