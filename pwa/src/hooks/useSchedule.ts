import { useQuery } from "@tanstack/react-query";
import { scheduleApi } from "../services/scheduleApi";

export function useIndex() {
  return useQuery({
    queryKey: ["index"],
    queryFn: scheduleApi.fetchIndex,
    staleTime: 60 * 60 * 1000,
    refetchOnReconnect: true,
  });
}

export function useInstituteManifest(instituteId: string | null) {
  return useQuery({
    queryKey: ["manifest", instituteId],
    queryFn: () => scheduleApi.fetchManifest(instituteId!),
    enabled: !!instituteId,
    staleTime: 60 * 60 * 1000,
    refetchOnReconnect: true,
  });
}

export function useGroupSchedule(
  instituteId: string | null,
  groupFile: string | null
) {
  return useQuery({
    queryKey: ["group", instituteId, groupFile],
    queryFn: () => scheduleApi.fetchGroup(instituteId!, groupFile!),
    enabled: !!instituteId && !!groupFile,
    staleTime: 6 * 60 * 60 * 1000,
    refetchOnReconnect: true,
  });
}
