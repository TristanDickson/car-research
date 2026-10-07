// IndexedDB (Dexie) is the browser-side database.
//
//   public  cars / deals / meta  — seeded from the committed snapshot on load and
//           re-seeded whenever manifest.generated_at changes (the pipeline
//           publishes a new cut). Pages query these tables, not the JSON files.
//   private shortlist            — the user's own picks, this browser only.
//
// Same split as etf-tool: public data committed and served, private data in
// IndexedDB.
import Dexie, { type Table } from "dexie";

import { getManifest, loadCars, loadData, loadModels, loadOffers, loadRequirements, loadResiduals, loadSeries, loadSpecs } from "./snapshot";
import type { DataPage, Requirements, ResidualSeries, SnapshotCar, SnapshotManifest, SnapshotModel, SnapshotOffer, SnapshotSeries, SnapshotSpec } from "./types";

export interface MetaRow {
  key: string;
  value: string;
}

export interface ShortlistRow {
  car_id: string;
  added_at: string;
  note: string | null;
}

export class CarResearchDB extends Dexie {
  cars!: Table<SnapshotCar, string>;
  offers!: Table<SnapshotOffer, string>;
  specs!: Table<SnapshotSpec, string>;
  models!: Table<SnapshotModel, string>;
  series!: Table<SnapshotSeries, string>;
  residuals!: Table<ResidualSeries, string>;
  meta!: Table<MetaRow, string>;
  shortlist!: Table<ShortlistRow, string>;

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
  }
}

let _db: CarResearchDB | null = null;
let _seeding: Promise<SnapshotManifest> | null = null;

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

  const [cars, offers, requirements, data, specs, models, series, residuals] = await Promise.all([
    loadCars(),
    loadOffers(),
    loadRequirements(),
    loadData().catch(() => null as DataPage | null),
    loadSpecs().catch(() => [] as SnapshotSpec[]),
    loadModels().catch(() => [] as SnapshotModel[]),
    loadSeries().catch(() => [] as SnapshotSeries[]),
    loadResiduals().catch(() => [] as ResidualSeries[]),
  ]);
  await db.transaction("rw", [db.cars, db.offers, db.specs, db.models, db.series, db.residuals, db.meta], async () => {
    await db.cars.clear();
    await db.offers.clear();
    await db.specs.clear();
    await db.models.clear();
    await db.series.clear();
    await db.residuals.clear();
    await db.cars.bulkPut(cars);
    await db.offers.bulkPut(offers);
    await db.specs.bulkPut(specs);
    await db.models.bulkPut(models);
    await db.series.bulkPut(series);
    await db.residuals.bulkPut(residuals.map((r) => ({ ...r, id: `${r.model}|${r.year}` })));
    await db.meta.bulkPut([
      { key: "generated_at", value: manifest.generated_at },
      { key: "schema_version", value: manifest.schema_version },
      { key: "requirements", value: JSON.stringify(requirements) },
      { key: "data", value: JSON.stringify(data) },
    ]);
  });
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

export async function getRequirements(): Promise<Requirements | null> {
  await ensureSeeded();
  const row = await getDb().meta.get("requirements");
  return row ? (JSON.parse(row.value) as Requirements) : null;
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
}

/** Test hook: drop the database and re-arm seeding. */
export async function __resetForTests(): Promise<void> {
  if (_db !== null) {
    _db.close();
    _db = null;
  }
  _seeding = null;
  await Dexie.delete("CarResearchDB");
}
