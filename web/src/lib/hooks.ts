import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ensureSeeded, getDataPage, getDb, getRequirements, toggleShortlist } from "./db";

const FOREVER = Number.POSITIVE_INFINITY;

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

export function useOffers() {
  return useQuery({
    queryKey: ["offers"],
    queryFn: async () => {
      await ensureSeeded();
      return getDb().offers.orderBy("captured_at").toArray();
    },
    staleTime: FOREVER,
  });
}

export function useOffersForCar(carId: string | null) {
  return useQuery({
    queryKey: ["offers", "car", carId],
    queryFn: async () => {
      await ensureSeeded();
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

/** Every series (schema 5): one per subject, route and source. */
export function useSeries() {
  return useQuery({
    queryKey: ["series"],
    queryFn: async () => {
      await ensureSeeded();
      return getDb().series.toArray();
    },
    staleTime: FOREVER,
  });
}

/** A car's own series plus its model's used-stock series. */
export function useSeriesForCar(car: { id: string; model_key?: string } | null | undefined) {
  return useQuery({
    queryKey: ["series", "car", car?.id ?? null],
    queryFn: async () => {
      await ensureSeeded();
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
      await ensureSeeded();
      return getDb().residuals.where("model").equals(modelKey as string).toArray();
    },
    enabled: !!modelKey,
    staleTime: FOREVER,
  });
}
