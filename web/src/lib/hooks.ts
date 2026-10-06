import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ensureSeeded, getDb, getRequirements, toggleShortlist } from "./db";

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

export function useDeals() {
  return useQuery({
    queryKey: ["deals"],
    queryFn: async () => {
      await ensureSeeded();
      return getDb().deals.orderBy("captured_at").toArray();
    },
    staleTime: FOREVER,
  });
}

export function useDealsForCar(carId: string | null) {
  return useQuery({
    queryKey: ["deals", "car", carId],
    queryFn: async () => {
      await ensureSeeded();
      return getDb().deals.where("car_id").equals(carId as string).toArray();
    },
    enabled: !!carId,
    staleTime: FOREVER,
  });
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
