import type { ScheduleIndex, InstituteSchedule } from "../types/schedule";

declare const __DATA_BASE_URL__: string;

const BASE = __DATA_BASE_URL__;

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}/${path}`, { cache: "default" });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

export const scheduleApi = {
  fetchIndex: () => get<ScheduleIndex>("meta/index.json"),
  fetchSchedule: (id: string) => get<InstituteSchedule>(`institutes/${id}/schedule.json`),
};
