import { useQuery } from "@tanstack/react-query";
import { scheduleApi } from "../services/scheduleApi";

export function useIndex() {
  return useQuery({
    queryKey: ["index"],
    queryFn: scheduleApi.fetchIndex,
    staleTime: 60 * 60 * 1000, // 1 час
  });
}

export function useInstituteSchedule(instituteId: string | null) {
  return useQuery({
    queryKey: ["schedule", instituteId],
    queryFn: () => scheduleApi.fetchSchedule(instituteId!),
    enabled: !!instituteId,
    staleTime: 6 * 60 * 60 * 1000, // 6 часов
  });
}
