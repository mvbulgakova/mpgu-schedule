import { useQuery } from "@tanstack/react-query";
import { scheduleApi } from "../services/scheduleApi";

export function useIndex() {
  return useQuery({
    queryKey: ["index"],
    queryFn: scheduleApi.fetchIndex,
    staleTime: 60 * 60 * 1000,
    refetchOnReconnect: true,   // авто-повтор при восстановлении сети
  });
}

export function useInstituteSchedule(instituteId: string | null) {
  return useQuery({
    queryKey: ["schedule", instituteId],
    queryFn: () => scheduleApi.fetchSchedule(instituteId!),
    enabled: !!instituteId,
    staleTime: 6 * 60 * 60 * 1000,
    refetchOnReconnect: true,
  });
}
