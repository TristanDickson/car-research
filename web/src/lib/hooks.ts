import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ensureComputed, ensureSeeded, getBasis, getCarDetails, getComputeStats, getDataPage, getDb, getRequirements, getSeedRequirements, getUsedForModel, resetRequirements, saveRequirements, toggleShortlist } from "./db";
import type { CarCostRow } from "./model/recompute";
import type { Requirements } from "./types";

const FOREVER = Number.POSITIVE_INFINITY;
/** Everything the cost model produced; a basis change invalidates the lot. */
const COMPUTED = ["costs", "series", "residuals", "offers", "basis", "compute"];

export function useSnapshot() {
  return useQuery({ queryKey: ["snapshot"], queryFn: ensureSeeded, staleTime: FOREVER, retry: 1 });
}

export function useCars() {
  return useQuery({
    queryKey: ["cars"],
    queryFn: async () => {
      await ensureSeeded();
      return getDb().cars.orderBy("id").toArray();
    },
    staleTime: FOREVER,
  });
}

export function useCar(id: string | null) {
  return useQuery({
    queryKey: ["car", id],
    queryFn: async () => {
      await ensureSeeded();
      return (await getDb().cars.get(id as string)) ?? null;
    },
    enabled: !!id,
    staleTime: FOREVER,
  });
}

/** What every car costs today under the reader's basis, by car id (lib/model/recompute). */
export function useCosts() {
  return useQuery({
    queryKey: ["costs"],
    queryFn: async () => {
      await ensureComputed();
      return new Map((await getDb().costs.toArray()).map((r) => [r.id, r] as [string, CarCostRow]));
    },
    staleTime: FOREVER,
  });
}

export function useCostsForCar(id: string | null | undefined) {
  return useQuery({
    queryKey: ["costs", id ?? null],
    queryFn: async () => {
      await ensureComputed();
      return (await getDb().costs.get(id as string)) ?? null;
    },
    enabled: !!id,
    staleTime: FOREVER,
  });
}

export function useBasis() {
  return useQuery({ queryKey: ["basis"], queryFn: getBasis, staleTime: FOREVER });
}

export function useComputeStats() {
  return useQuery({ queryKey: ["compute"], queryFn: getComputeStats, staleTime: FOREVER });
}

/** Every offer as derived from its spans: latest state, freshness, normalisation. */
export function useOffers() {
  return useQuery({
    queryKey: ["offers"],
    queryFn: async () => {
      await ensureComputed();
      return getDb().offers.orderBy("captured_at").toArray();
    },
    staleTime: FOREVER,
  });
}

export function useOffersForCar(carId: string | null) {
  return useQuery({
    queryKey: ["offers", "car", carId],
    queryFn: async () => {
      await ensureComputed();
      return getDb().offers.where("car_id").equals(carId as string).toArray();
    },
    enabled: !!carId,
    staleTime: FOREVER,
  });
}

export function useDataPage() {
  return useQuery({ queryKey: ["data"], queryFn: getDataPage, staleTime: FOREVER });
}

export function useRequirements() {
  return useQuery({ queryKey: ["requirements"], queryFn: getRequirements, staleTime: FOREVER });
}

export function useSeedRequirements() {
  return useQuery({ queryKey: ["requirements", "seed"], queryFn: getSeedRequirements, staleTime: FOREVER });
}

export function useSaveRequirements() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (doc: Requirements) => saveRequirements(doc),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["requirements"] }); for (const k of COMPUTED) qc.invalidateQueries({ queryKey: [k] }); },
  });
}

export function useResetRequirements() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => resetRequirements(),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["requirements"] }); for (const k of COMPUTED) qc.invalidateQueries({ queryKey: [k] }); },
  });
}

export function useCarDetails(id: string | null | undefined) {
  return useQuery({
    queryKey: ["details", id ?? null],
    queryFn: () => getCarDetails(id as string),
    enabled: !!id,
    staleTime: FOREVER,
  });
}

export function useShortlist() {
  return useQuery({
    queryKey: ["shortlist"],
    queryFn: () => getDb().shortlist.toArray(),
    staleTime: FOREVER,
  });
}

export function useToggleShortlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: toggleShortlist,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["shortlist"] }),
  });
}

export function useSpecs() {
  return useQuery({
    queryKey: ["specs"],
    queryFn: async () => {
      await ensureSeeded();
      return getDb().specs.orderBy("spec_key").toArray();
    },
    staleTime: FOREVER,
  });
}

export function useSpecsForCar(carId: string | null) {
  return useQuery({
    queryKey: ["specs", "car", carId],
    queryFn: async () => {
      await ensureSeeded();
      return getDb().specs.where("car_id").equals(carId as string).toArray();
    },
    enabled: !!carId,
    staleTime: FOREVER,
  });
}

export function useModels() {
  return useQuery({
    queryKey: ["models"],
    queryFn: async () => {
      await ensureSeeded();
      return getDb().models.orderBy("slug").toArray();
    },
    staleTime: FOREVER,
  });
}

/** A car's own series plus its model's used-stock series, computed under the reader's basis. */
export function useSeriesForCar(car: { id: string; model_key?: string } | null | undefined) {
  return useQuery({
    queryKey: ["series", "car", car?.id ?? null],
    queryFn: async () => {
      await ensureComputed();
      const subjects = [car!.id, ...(car!.model_key ? [`model:${car!.model_key}`] : [])];
      return getDb().series.where("subject").anyOf(subjects).toArray();
    },
    enabled: !!car,
    staleTime: FOREVER,
  });
}

export function useResidualsForModel(modelKey: string | null | undefined) {
  return useQuery({
    queryKey: ["residuals", modelKey ?? null],
    queryFn: async () => {
      await ensureComputed();
      return getDb().residuals.where("model").equals(modelKey as string).toArray();
    },
    enabled: !!modelKey,
    staleTime: FOREVER,
  });
}

export function useUsedForModel(modelKey: string | null | undefined) {
  return useQuery({
    queryKey: ["used", modelKey ?? null],
    queryFn: () => getUsedForModel(modelKey as string),
    enabled: !!modelKey,
    staleTime: FOREVER,
  });
}
