// Fetch layer for the committed snapshot. The SPA does not read these files
// directly on every page: db.ts seeds them into IndexedDB once per snapshot
// generation, and pages query that local DB.
import type { CarDetails, DataPage, Requirements, SnapshotCar, SnapshotManifest, SnapshotModel, SnapshotSighting, SnapshotSpec, SnapshotUsed, SnapshotUsedSpan } from "./types";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
export const SNAPSHOT_BASE = `${BASE_PATH}/data`;

// Must match pipeline/services/snapshot.py SCHEMA_VERSION.
export const SUPPORTED_SCHEMA_VERSION = "7";

async function fetchJson<T>(rel: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${SNAPSHOT_BASE}/${rel}`, init);
  if (!res.ok) throw new Error(`snapshot ${rel} -> ${res.status}`);
  return res.json() as Promise<T>;
}

// Uncached so a "refresh" always sees the latest deploy.
export const getManifest = () =>
  fetchJson<SnapshotManifest>("manifest.json", { cache: "no-store" });
// no-cache = revalidate against the server's ETag: changed files download fresh.
export const loadCars = () => fetchJson<SnapshotCar[]>("cars.json", { cache: "no-cache" });
/** Every offer observation span: the facts the browser costs (lib/model). */
export const loadSightings = () => fetchJson<SnapshotSighting[]>("sightings.json", { cache: "no-cache" });
/** Every used listing's asking-price spans: the residual evidence and the used route. */
export const loadUsedSpans = () => fetchJson<SnapshotUsedSpan[]>("used_spans.json", { cache: "no-cache" });
export const loadData = () => fetchJson<DataPage>("data.json", { cache: "no-cache" });
export const loadSpecs = () => fetchJson<SnapshotSpec[]>("specs.json", { cache: "no-cache" });
export const loadModels = () => fetchJson<SnapshotModel[]>("models.json", { cache: "no-cache" });
/** Every used listing, fetched the first time a car page asks for a model's stock. */
export const loadUsed = () => fetchJson<SnapshotUsed[]>("used.json", { cache: "no-cache" });
/** Per-car detail, fetched the first time a car page needs it. */
export const loadDetails = () => fetchJson<Record<string, Omit<CarDetails, "id">>>("details.json", { cache: "no-cache" });
export const loadRequirements = () =>
  fetchJson<Requirements>("requirements.json", { cache: "no-cache" });
