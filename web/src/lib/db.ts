// IndexedDB (Dexie) is the browser-side database.
//
//   facts    cars / sightings / used_spans / specs / models / meta — seeded from
//            the committed snapshot on load and re-seeded whenever
//            manifest.generated_at changes (the pipeline publishes a new cut).
//   results  costs / series / residuals / offers — what the one cost model
//            (lib/model) makes of the facts under the reader's basis, as of
//            today; recomputed whenever the snapshot, the basis or the day
//            changes, and read by every page. Nothing is costed at render time.
//   private  shortlist / settings — the reader's own picks and brief, this
//            browser only, kept across reseeds.
import Dexie, { type Table } from "dexie";

import { basisOf, type Basis } from "./model/dealMath";
import { computeAll, type CarCostRow } from "./model/recompute";
import type { ResidualRow, SeriesRow } from "./model/sightings";
import { setProgress } from "./progress";
import { getManifest, loadCars, loadData, loadDetails, loadModels, loadRequirements, loadSightings, loadSpecs, loadUsed, loadUsedSpans } from "./snapshot";
import type { CarDetails, DataPage, Requirements, SnapshotCar, SnapshotManifest, SnapshotModel, SnapshotOffer, SnapshotSighting, SnapshotSpec, SnapshotUsed, SnapshotUsedSpan } from "./types";

export const DEFAULT_STALE_DAYS = 14;

export interface MetaRow {
  key: string;
  value: string;
}

export interface ShortlistRow {
  car_id: string;
  added_at: string;
  note: string | null;
}

/** The reader's own copy of a document (the requirements): seeded once from the
 * snapshot, kept across snapshot reseeds, replaced only on an explicit reset. */
export interface SettingsRow {
  key: string;
  value: string;
  seeded_from: string;
  updated_at: string;
}

export class CarResearchDB extends Dexie {
  cars!: Table<SnapshotCar, string>;
  sightings!: Table<SnapshotSighting & { id?: number }, number>;
  used_spans!: Table<SnapshotUsedSpan & { id?: number }, number>;
  specs!: Table<SnapshotSpec, string>;
  models!: Table<SnapshotModel, string>;
  details!: Table<CarDetails, string>;
  used!: Table<SnapshotUsed, string>;
  costs!: Table<CarCostRow, string>;
  series!: Table<SeriesRow, string>;
  residuals!: Table<ResidualRow, string>;
  offers!: Table<SnapshotOffer, string>;
  meta!: Table<MetaRow, string>;
  shortlist!: Table<ShortlistRow, string>;
  settings!: Table<SettingsRow, string>;

  constructor() {
    super("CarResearchDB");
    this.version(1).stores({
      cars: "id, make, model, seats",
      deals: "id, car_id, finance_type, status, captured_at",
      meta: "key",
      shortlist: "car_id",
    });
    // v2 (snapshot schema 2): deals became offers (latest observation + freshness).
    // Dropping the old store forces a re-seed on next load (meta.generated_at
    // is cleared too), so nothing stale survives the upgrade.
    this.version(2)
      .stores({
        deals: null,
        offers: "id, car_id, finance_type, status, captured_at",
      })
      .upgrade((tx) => tx.table("meta").clear());
    // v3 (snapshot schema 3): scraped specs per variant; cars carry spec summaries.
    this.version(3)
      .stores({ specs: "spec_key, car_id, make, model, trim" })
      .upgrade((tx) => tx.table("meta").clear());
    // v4 (snapshot schema 4): every EV on sale as a generated car; the catalogue of models.
    this.version(4)
      .stores({ models: "slug, make" })
      .upgrade((tx) => tx.table("meta").clear());
    // v5 (snapshot schema 5): every sighting by route and source over time, and the residual evidence behind it.
    this.version(5)
      .stores({ series: "id, subject, route, source, car_id, model", residuals: "id, model" })
      .upgrade((tx) => tx.table("meta").clear());
    // v6 (snapshot schema 6): cars.json slimmed, per-car detail on demand; the
    // reader's own requirements live in settings and survive reseeds.
    this.version(6)
      .stores({ details: "id", settings: "key" })
      .upgrade((tx) => tx.table("meta").clear());
    // v7: used listings on demand, by model, for the car page's ranked list.
    this.version(7).stores({ used: "listing_key, model_key, car_id" });
    // v8 (snapshot schema 7): the pipeline exports facts only. The spans are
    // seeded; costs, series, residuals and offers are computed here under the
    // reader's basis and stored.
    this.version(8)
      .stores({ sightings: "++id, key, car_id, route, source, model", used_spans: "++id, key, model, source", costs: "id, model" })
      .upgrade((tx) => tx.table("meta").clear());
  }
}

let _db: CarResearchDB | null = null;
let _seeding: Promise<SnapshotManifest> | null = null;
let _computing: Promise<void> | null = null;

export function getDb(): CarResearchDB {
  if (typeof indexedDB === "undefined") {
    throw new Error("IndexedDB unavailable (the local store is client-only)");
  }
  if (_db === null) _db = new CarResearchDB();
  return _db;
}

async function seed(): Promise<SnapshotManifest> {
  const db = getDb();
  const manifest = await getManifest();
  const current = await db.meta.get("generated_at");
  if (current?.value === manifest.generated_at) return manifest;

  setProgress({ label: "Downloading the snapshot", done: 0, total: 2 });
  const [cars, sightings, usedSpans, requirements, data, specs, models] = await Promise.all([
    loadCars(),
    loadSightings().catch(() => [] as SnapshotSighting[]),
    loadUsedSpans().catch(() => [] as SnapshotUsedSpan[]),
    loadRequirements(),
    loadData().catch(() => null as DataPage | null),
    loadSpecs().catch(() => [] as SnapshotSpec[]),
    loadModels().catch(() => [] as SnapshotModel[]),
  ]);
  setProgress({ label: "Storing the facts", done: 1, total: 2 });
  await db.transaction("rw", [db.cars, db.sightings, db.used_spans, db.specs, db.models, db.details, db.used, db.meta, db.settings], async () => {
    await db.cars.clear();
    await db.sightings.clear();
    await db.used_spans.clear();
    await db.specs.clear();
    await db.models.clear();
    await db.details.clear();   // refetched on demand against the new snapshot
    await db.used.clear();
    // The reader's requirements are theirs: seed them once, never overwrite on a new snapshot.
    if (!(await db.settings.get("requirements"))) {
      await db.settings.put({ key: "requirements", value: JSON.stringify(requirements), seeded_from: manifest.generated_at, updated_at: new Date().toISOString() });
    }
    await db.cars.bulkPut(cars);
    await db.sightings.bulkAdd(sightings);
    await db.used_spans.bulkAdd(usedSpans);
    await db.specs.bulkPut(specs);
    await db.models.bulkPut(models);
    await db.meta.bulkPut([
      { key: "generated_at", value: manifest.generated_at },
      { key: "schema_version", value: manifest.schema_version },
      { key: "requirements", value: JSON.stringify(requirements) },
      { key: "data", value: JSON.stringify(data) },
    ]);
  });
  setProgress(null);
  return manifest;
}

/** Make sure the local DB holds the current snapshot. Memoised as a promise so
 * concurrent first-load callers share one seeding pass; a failure re-arms it. */
export function ensureSeeded(): Promise<SnapshotManifest> {
  if (_seeding === null) {
    _seeding = seed().catch((e) => {
      _seeding = null;
      throw e;
    });
  }
  return _seeding;
}

export const todayIso = (): string => new Date().toISOString().slice(0, 10);

async function readRequirements(db: CarResearchDB): Promise<Requirements | null> {
  const own = await db.settings.get("requirements");
  if (own) return JSON.parse(own.value) as Requirements;
  const row = await db.meta.get("requirements");
  return row ? (JSON.parse(row.value) as Requirements) : null;
}

/** The reader's quoting basis: the settings' copy, else the seed's. */
export async function getBasis(): Promise<Basis> {
  await ensureSeeded();
  const reqs = await readRequirements(getDb());
  return basisOf(reqs?.quoting_basis);
}

async function staleDays(db: CarResearchDB): Promise<number> {
  const row = await db.meta.get("data");
  const data = row ? (JSON.parse(row.value) as DataPage | null) : null;
  return data?.stale_days ?? DEFAULT_STALE_DAYS;
}

/** What the stored results were computed from: the snapshot, the basis, the day. */
function costKey(generatedAt: string, basis: Basis, today: string): string {
  return JSON.stringify({ generatedAt, basis, today });
}

/** Statistics of the last recompute, for the Data page. */
export interface ComputeStats {
  key: string;
  computed_at: string;
  sightings: number;
  costed: number;
  cars: number;
  series: number;
  offers: number;
  /** Milliseconds: the model itself, reading the facts, writing the results. */
  ms: number;
  read_ms: number;
  write_ms: number;
}

async function recompute(): Promise<void> {
  const db = getDb();
  const manifest = await ensureSeeded();
  const basis = basisOf((await readRequirements(db))?.quoting_basis);
  const today = todayIso();
  const key = costKey(manifest.generated_at, basis, today);
  const have = await db.meta.get("costed");
  if (have?.value === key) return;
  const STEPS = 7;
  const step = (n: number, label: string) => setProgress({ label, done: n, total: STEPS });
  try {
    step(0, "Reading the facts");
    const t0 = Date.now();
    const [sightings, usedSpans, cars, stale] = await Promise.all([db.sightings.toArray(), db.used_spans.toArray(), db.cars.toArray(), staleDays(db)]);
    const t1 = Date.now();
    step(1, `Costing ${(sightings.length + usedSpans.length).toLocaleString("en-GB")} sightings over ${basis.term_months} months at ${(basis.savings_rate_apr * 100).toFixed(1)}%`);
    await new Promise((r) => setTimeout(r, 0));   // let the bar paint before the model runs
    const r = computeAll({ sightings, usedSpans, cars, basis, today, staleDays: stale });
    const t2 = Date.now();
    await db.transaction("rw", [db.costs, db.series, db.residuals, db.offers, db.meta], async () => {
      step(2, "Storing what every car costs");
      await db.costs.clear();
      await db.costs.bulkPut(r.cars);
      step(3, "Storing every series");
      await db.series.clear();
      await db.series.bulkPut(r.series);
      step(4, "Storing the residual evidence");
      await db.residuals.clear();
      await db.residuals.bulkPut(r.residuals);
      step(5, "Storing every offer");
      await db.offers.clear();
      await db.offers.bulkPut(r.offers);
      step(6, "Done");
      const stats: ComputeStats = { key, computed_at: new Date().toISOString(), sightings: r.stats.sightings, costed: r.stats.costed,
                                  cars: r.cars.length, series: r.series.length, offers: r.offers.length, ms: r.stats.ms, read_ms: t1 - t0, write_ms: Date.now() - t2 };
      await db.meta.bulkPut([{ key: "costed", value: key }, { key: "compute_stats", value: JSON.stringify(stats) }]);
    });
  } finally {
    setProgress(null);
  }
}

/** Make sure the stored results match the current snapshot, basis and day. One pass at a time. */
export function ensureComputed(): Promise<void> {
  if (_computing === null) {
    _computing = recompute().finally(() => { _computing = null; });
  }
  return _computing;
}

export async function getComputeStats(): Promise<ComputeStats | null> {
  await ensureComputed();
  const row = await getDb().meta.get("compute_stats");
  return row ? (JSON.parse(row.value) as ComputeStats) : null;
}

/** The reader's requirements (settings), else the snapshot's seed. */
export async function getRequirements(): Promise<Requirements | null> {
  await ensureSeeded();
  return readRequirements(getDb());
}

/** The snapshot's seed copy (data/seed/requirements.json), for reset and for showing what changed. */
export async function getSeedRequirements(): Promise<Requirements | null> {
  await ensureSeeded();
  const row = await getDb().meta.get("requirements");
  return row ? (JSON.parse(row.value) as Requirements) : null;
}

/** Save the reader's brief; a changed quoting basis recomputes every stored figure before this resolves. */
export async function saveRequirements(doc: Requirements): Promise<void> {
  const db = getDb();
  const cur = await db.settings.get("requirements");
  await db.settings.put({ key: "requirements", value: JSON.stringify(doc), seeded_from: cur?.seeded_from ?? "", updated_at: new Date().toISOString() });
  await ensureComputed();
}

/** Back to the seed: the only time the reader's copy is overwritten. */
export async function resetRequirements(): Promise<Requirements | null> {
  const seed = await getSeedRequirements();
  if (seed) await saveRequirements(seed);
  return seed;
}

/** A car's on-demand detail, fetching details.json once per snapshot. */
export async function getCarDetails(id: string): Promise<CarDetails | null> {
  await ensureSeeded();
  const db = getDb();
  const hit = await db.details.get(id);
  if (hit) return hit;
  if ((await db.details.count()) === 0) {
    const all = await loadDetails();
    await db.details.bulkPut(Object.entries(all).map(([cid, d]) => ({ id: cid, ...d })));
    return (await db.details.get(id)) ?? null;
  }
  return null;
}

export async function getDataPage(): Promise<DataPage | null> {
  await ensureSeeded();
  const row = await getDb().meta.get("data");
  return row ? (JSON.parse(row.value) as DataPage | null) : null;
}

export async function toggleShortlist(carId: string): Promise<boolean> {
  const db = getDb();
  const existing = await db.shortlist.get(carId);
  if (existing) {
    await db.shortlist.delete(carId);
    return false;
  }
  await db.shortlist.put({ car_id: carId, added_at: new Date().toISOString(), note: null });
  return true;
}

/** Test hook: forget the in-memory handle and seeding memo but keep the stored
 * rows, i.e. what a page reload looks like to this module. */
export function __clearSeedingMemoForTests(): void {
  if (_db !== null) {
    _db.close();
    _db = null;
  }
  _seeding = null;
  _computing = null;
}

/** Test hook: drop the database and re-arm seeding. */
export async function __resetForTests(): Promise<void> {
  if (_db !== null) {
    _db.close();
    _db = null;
  }
  _seeding = null;
  _computing = null;
  await Dexie.delete("CarResearchDB");
}

/** A model's used listings (every one ever seen), fetching used.json once per snapshot. */
export async function getUsedForModel(modelKey: string): Promise<SnapshotUsed[]> {
  await ensureSeeded();
  const db = getDb();
  if ((await db.used.count()) === 0) {
    const all = await loadUsed();
    await db.used.bulkPut(all.map((u) => ({ ...u, model_key: `${(u.make_slug ?? "").toLowerCase()}/${u.model_slug ?? ""}` })));
  }
  return db.used.where("model_key").equals(modelKey).toArray();
}
