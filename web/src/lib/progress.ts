// What the browser is doing with the data right now, for a bar on the page:
// downloading and storing a new snapshot, or costing every sighting under the
// reader's basis and storing the results. lib/db.ts reports; the banner and the
// Loading placeholder read. Null when idle.
import { useSyncExternalStore } from "react";

export interface Progress {
  label: string;
  /** Steps done of total; a bar is drawn from them. */
  done: number;
  total: number;
}

let state: Progress | null = null;
const listeners = new Set<() => void>();

export function setProgress(p: Progress | null): void {
  state = p;
  for (const l of listeners) l();
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => { listeners.delete(l); };
}

export function useProgress(): Progress | null {
  return useSyncExternalStore(subscribe, () => state, () => null);
}
