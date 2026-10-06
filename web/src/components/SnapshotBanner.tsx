"use client";

import { useState } from "react";

import { useSnapshot } from "@/lib/hooks";
import { dateLabel } from "@/lib/format";
import { getManifest, SUPPORTED_SCHEMA_VERSION } from "@/lib/snapshot";

// Freshness of the data in the local DB, with a manual re-check against the
// published snapshot. A schema mismatch renders wrong rather than crashing, so
// it is called out loudly.
export function SnapshotBanner() {
  const { data: manifest, error } = useSnapshot();
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const mismatch = manifest != null && manifest.schema_version !== SUPPORTED_SCHEMA_VERSION;

  async function refresh() {
    setBusy(true);
    setMsg(null);
    try {
      const fresh = await getManifest();
      if (manifest && fresh.generated_at === manifest.generated_at) {
        setMsg("Already on the latest snapshot.");
      } else {
        setMsg("New snapshot found — reloading…");
        window.location.reload();
      }
    } catch (e) {
      setMsg(`Couldn't reach the snapshot: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border-b border-gray-800 bg-gray-900/60">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-2 px-6 py-1.5 text-xs text-gray-400">
        <span>
          {error ? (
            <span className="text-rose-300">Snapshot failed to load: {(error as Error).message}</span>
          ) : manifest ? (
            <>
              Snapshot generated {dateLabel(manifest.generated_at)} · {manifest.counts.cars} cars ·{" "}
              {manifest.counts.offers} offers · held in this browser&apos;s IndexedDB
              {mismatch && (
                <span className="ml-2 font-semibold text-rose-300">
                  Data format v{manifest.schema_version} but the app expects v{SUPPORTED_SCHEMA_VERSION}.
                </span>
              )}
            </>
          ) : (
            "Loading snapshot…"
          )}
          {msg && <span className="ml-2 text-gray-300">{msg}</span>}
        </span>
        <button
          onClick={refresh}
          disabled={busy}
          className="rounded border border-gray-700 px-2 py-0.5 text-gray-200 hover:bg-gray-800 disabled:opacity-50"
        >
          {busy ? "Checking…" : "Check for new data"}
        </button>
      </div>
    </div>
  );
}
