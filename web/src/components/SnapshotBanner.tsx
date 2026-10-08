"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { ProgressBar } from "@/components/ui";
import { checkForUpdate } from "@/lib/db";
import { useSnapshot } from "@/lib/hooks";
import { dateLabel } from "@/lib/format";
import { useProgress } from "@/lib/progress";
import { SUPPORTED_SCHEMA_VERSION } from "@/lib/snapshot";

// The data the app is showing: the snapshot stored in this browser, read with no
// network at all. Once it is up, the site is asked in the background for a newer
// snapshot, which is downloaded and swapped in when there is one (and again when the
// browser comes back online); offline, the stored one is simply what the app shows.
export function SnapshotBanner() {
  const { data: manifest, error } = useSnapshot();
  const qc = useQueryClient();
  const progress = useProgress();
  const [msg, setMsg] = useState<string | null>(null);
  const [outdated, setOutdated] = useState(false);
  const [busy, setBusy] = useState(false);
  const checked = useRef(false);

  const check = useCallback(async (asked: boolean) => {
    setBusy(true);
    if (asked) setMsg(null);
    try {
      const r = await checkForUpdate();
      if (r === "updated") {
        await qc.invalidateQueries();
        setMsg("Updated to the latest snapshot.");
      } else if (r === "offline") {
        setMsg("Offline: showing the snapshot stored in this browser.");
      } else if (r === "app-outdated") {
        setOutdated(true);
      } else if (asked) {
        setMsg("Already on the latest snapshot.");
      } else {
        setMsg(null);
      }
    } finally {
      setBusy(false);
    }
  }, [qc]);

  useEffect(() => {
    if (manifest && !checked.current) {
      checked.current = true;
      void check(false);
    }
  }, [manifest, check]);

  useEffect(() => {
    const online = () => { if (checked.current) void check(false); };
    window.addEventListener("online", online);
    return () => window.removeEventListener("online", online);
  }, [check]);

  const mismatch = manifest != null && manifest.schema_version !== SUPPORTED_SCHEMA_VERSION;
  const offline = typeof navigator !== "undefined" && navigator.onLine === false;

  return (
    <div className="border-b border-gray-800 bg-gray-900/60">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-2 px-4 py-1.5 text-xs text-gray-400 sm:px-6">
        <span>
          {error ? (
            <span className="text-rose-300">
              {offline ? "Offline, and this browser has no stored snapshot yet: open the site once while online." : `Snapshot failed to load: ${(error as Error).message}`}
            </span>
          ) : manifest ? (
            <>
              Snapshot of {dateLabel(manifest.generated_at)} · {manifest.counts.cars} cars · {manifest.counts.offers} offers · stored in this browser, works offline
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
          {outdated && (
            <span className="ml-2 text-amber-200">
              A newer version of the app is out.{" "}
              <button onClick={() => window.location.reload()} className="underline">Reload</button>
            </span>
          )}
        </span>
        <button
          onClick={() => void check(true)}
          disabled={busy || !manifest}
          className="rounded border border-gray-700 px-2 py-0.5 text-gray-200 hover:bg-gray-800 disabled:opacity-50"
        >
          {busy ? "Checking…" : "Check for new data"}
        </button>
      </div>
      {progress && (
        <div className="mx-auto max-w-[1600px] px-4 pb-2 sm:px-6"><ProgressBar p={progress} className="max-w-xl" /></div>
      )}
    </div>
  );
}
