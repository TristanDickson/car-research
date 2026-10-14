"use client";

import { useMemo } from "react";

import { carCosts, type CarCosts } from "./costs";
import { useCars, useCosts, useDataPage, useRequirements, useSearches } from "./hooks";
import { compareBy, matches, queryOptions, useQuery, type CarContext, type Query, type QueryOptions } from "./query";
import type { SnapshotCar } from "./types";

export interface CarQueryResult {
  query: Query;
  set: (patch: Partial<Query>) => void;
  /** Every car the snapshot holds (the bar's option lists are drawn from these). */
  cars: SnapshotCar[] | undefined;
  /** The cars the query admits, in the query's sort order. */
  rows: SnapshotCar[];
  ctxOf: (c: SnapshotCar) => CarContext;
  options: QueryOptions;
  flagLabels: Record<string, string>;
  budgetCeiling: number | null;
  /** The car the reader compares every card with (Settings), if they chose one. */
  compareWith: SnapshotCar | null;
  /** Cars left out only because no source gives a value the search bounds or requires. */
  unknownHidden: number;
  loading: boolean;
  error: unknown;
}

/** The one result set behind the cards, the table and the specs grid. A view whose URL
 * carries no search opens on the last one used, else the reader's default saved search. */
export function useCarQuery(): CarQueryResult {
  const searches = useSearches();
  const list = searches.data;
  const defaultQs = list === undefined ? undefined : list.searches.find((s) => s.id === list.default_id)?.query ?? null;
  const [query, set, ready] = useQuery(searches.error ? null : defaultQs);
  const cars = useCars();
  const costRows = useCosts();
  const reqs = useRequirements();
  const data = useDataPage();

  const names = data.data?.sources;
  const ctxById = useMemo(() => {
    const out = new Map<string, CarContext>();
    for (const c of cars.data ?? []) {
      const costs: CarCosts = carCosts(c, costRows.data?.get(c.id), names);
      out.set(c.id, { costs });
    }
    return out;
  }, [cars.data, costRows.data, names]);
  const ctxOf = (c: SnapshotCar) => ctxById.get(c.id)!;

  const rows = useMemo(() => {
    const list = (cars.data ?? []).filter((c) => matches(c, ctxById.get(c.id)!, query));
    return list.sort(compareBy(query.sort || "true", (c) => ctxById.get(c.id)!));
  }, [cars.data, ctxById, query]);

  const unknownHidden = useMemo(() => {
    if (query.keepUnknown) return 0;
    const keep = { ...query, keepUnknown: true };
    return (cars.data ?? []).filter((c) => !matches(c, ctxById.get(c.id)!, query) && matches(c, ctxById.get(c.id)!, keep)).length;
  }, [cars.data, ctxById, query]);
  const options = useMemo(() => queryOptions(cars.data ?? [], query), [cars.data, query]);
  const budget = reqs.data?.budget as { monthly_ceiling_gbp?: number } | undefined;

  return {
    query, set, cars: cars.data, rows, ctxOf, options,
    flagLabels: data.data?.flag_labels ?? {},
    budgetCeiling: budget?.monthly_ceiling_gbp ?? null,
    compareWith: (cars.data ?? []).find((c) => c.id === reqs.data?.compare_with) ?? null,
    unknownHidden,
    loading: !ready || !cars.data || reqs.data === undefined || costRows.data === undefined,
    error: cars.error ?? reqs.error ?? costRows.error ?? null,
  };
}
