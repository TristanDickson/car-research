"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 },
        },
      }),
  );
  // The built site's service worker (scripts/build-sw.mjs) keeps the app itself in the
  // browser so it opens offline; the data is already stored in IndexedDB (lib/db.ts).
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register(`${BASE_PATH}/sw.js`, { scope: `${BASE_PATH}/`, updateViaCache: "none" }).catch(() => {
      /* no worker on this host (a dev build, or a plain static server): the app still runs online */
    });
  }, []);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
