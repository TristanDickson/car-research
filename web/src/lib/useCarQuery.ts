"use client";

import { useMemo } from "react";

import { evaluateBrief, type Brief } from "./brief";
import { carCosts, type CarCosts } from "./costs";
import { useCars, useDataPage, useRequirements, useShortlist } from "./hooks";
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
  loading: boolean;
  error: unknown;
}

/** The one result set behind the cards, the table and the specs grid. */
export function useCarQuery(): CarQueryResult {
  const [query, set] = useQuery();
  const cars = useCars();
  const reqs = useRequirements();
  const data = useDataPage();
  const shortlist = useShortlist();

  const rules = reqs.data?.hard;
  const starred = useMemo(() => new Set((shortlist.data ?? []).map((s) => s.car_id)), [shortlist.data]);
  const ctxById = useMemo(() => {
    const out = new Map<string, CarContext>();
    for (const c of cars.data ?? []) {
      const brief: Brief = evaluateBrief(rules, c);
      const costs: CarCosts = carCosts(c);
      out.set(c.id, { brief, costs, starred: starred.has(c.id) });
    }
    return out;
  }, [cars.data, rules, starred]);
  const ctxOf = (c: SnapshotCar) => ctxById.get(c.id)!;

  const rows = useMemo(() => {
    const list = (cars.data ?? []).filter((c) => matches(c, ctxById.get(c.id)!, query));
    return list.sort(compareBy(query.sort || "true", (c) => ctxById.get(c.id)!));
  }, [cars.data, ctxById, query]);

  const options = useMemo(() => queryOptions(cars.data ?? [], query), [cars.data, query]);
  const budget = reqs.data?.budget as { monthly_ceiling_gbp?: number } | undefined;

  return {
    query, set, cars: cars.data, rows, ctxOf, options,
    flagLabels: data.data?.flag_labels ?? {},
    budgetCeiling: budget?.monthly_ceiling_gbp ?? null,
    loading: !cars.data || reqs.data === undefined,
    error: cars.error ?? reqs.error ?? null,
  };
}
