import type { ResolverChange, ResolverCounts } from "./types";

/** Sources whose records are prices (pipeline/services/snapshot.py, PRICE_SOURCES). */
const PRICE_SOURCES = new Set(["carwow_deals", "ncd", "leaseloco", "rrg", "kia_dealers", "cinch_new", "hyundai_offers"]);
const USED_SOURCES = new Set(["carwow_used", "cinch_used", "motorpoint_used"]);

/** The outcomes in the order the owner reads them, with their plain words. */
export const OUTCOMES = [
  { key: "same", short: "keep", long: "keeps its car" },
  { key: "merged", short: "merged", long: "keeps its car, which the resolver makes one car with another of today's" },
  { key: "to best spec", short: "best spec", long: "goes to the best spec of the cars it fits, today's included" },
  { key: "moved", short: "moved", long: "moves to another car" },
  { key: "newly placed", short: "newly placed", long: "gets a car it has none of today" },
  { key: "lost", short: "lost", long: "loses its car" },
  { key: "unplaced", short: "placed by neither", long: "gets no car today or from the resolver" },
] as const;

export const outcomeWords = (key: string): string => OUTCOMES.find((o) => o.key === key)?.long ?? key;

/** Losses and moves of prices first (0), then of used cars (1), then the rest (2). */
export function changeRank(c: Pick<ResolverChange, "source" | "outcome">): number {
  if (c.outcome !== "lost" && c.outcome !== "moved" && c.outcome !== "merged") return 2;
  if (PRICE_SOURCES.has(c.source)) return 0;
  return USED_SOURCES.has(c.source) ? 1 : 2;
}

/** The changes in the owner's reading order: by rank, losses before moves, then the biggest groups first. */
export function orderChanges(changes: ResolverChange[]): ResolverChange[] {
  return changes
    .map((c) => ({ c, rank: changeRank(c) }))
    .sort((a, b) => a.rank - b.rank
      || (a.c.outcome === "lost" ? 0 : 1) - (b.c.outcome === "lost" ? 0 : 1)
      || b.c.records - a.c.records
      || a.c.source.localeCompare(b.c.source) || (a.c.label ?? "").localeCompare(b.c.label ?? ""))
    .map((x) => x.c);
}

export function filterChanges(changes: ResolverChange[], source: string, outcome: string): ResolverChange[] {
  return changes.filter((c) => (source === "all" || c.source === source) && (outcome === "all" || c.outcome === outcome));
}

/** Records in each outcome over several sources' counts. */
export function sumCounts(rows: ResolverCounts[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of rows) for (const [k, v] of Object.entries(r)) out[k] = (out[k] ?? 0) + (v ?? 0);
  return out;
}

/** Each source the resolver reads, in plain words (the pipeline's providers, and where its cars come from). */
const SOURCE_NAMES: Record<string, string> = {
  carwow: "Carwow", parkers: "Parkers",
  carwow_deals: "Carwow deals", carwow_model: "Carwow's list of derivatives", carwow_options: "Carwow configurator",
  carwow_specs: "Carwow spec pages", carwow_used: "Carwow used", cinch_new: "cinch new", cinch_used: "cinch used",
  evdb: "EV Database", evdb_cars: "EV Database car pages", hyundai_configurator: "Hyundai configurator",
  hyundai_offers: "Hyundai UK offers", hyundai_specs: "Hyundai guides", kia_dealers: "Kia dealers", kia_specs: "Kia grade tables",
  leaseloco: "LeaseLoco", motorpoint_used: "Motorpoint", ncd: "New Car Discount", rrg: "RRG",
};

export const sourceName = (s: string): string => SOURCE_NAMES[s] ?? s;
