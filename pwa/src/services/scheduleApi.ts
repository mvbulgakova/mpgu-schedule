import type { ScheduleIndex, InstituteSchedule } from "../types/schedule";

declare const __DATA_BASE_URL__: string;
declare const __DATA_FALLBACK_URL__: string;

const PRIMARY = __DATA_BASE_URL__;
// Fallback пустая строка означает, что резервный URL не настроен
const FALLBACK = __DATA_FALLBACK_URL__;

async function fetchUrl(url: string): Promise<Response> {
  const res = await fetch(url, { cache: "default" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res;
}

async function get<T>(path: string): Promise<T> {
  const primaryUrl = `${PRIMARY}/${path}`;

  try {
    const res = await fetchUrl(primaryUrl);
    return res.json() as Promise<T>;
  } catch (primaryErr) {
    if (!FALLBACK || FALLBACK === PRIMARY) {
      throw new Error(`Не удалось загрузить ${path}: ${primaryErr}`);
    }

    // Пробуем резервный URL (напрямую raw.githubusercontent.com)
    try {
      const res = await fetchUrl(`${FALLBACK}/${path}`);
      return res.json() as Promise<T>;
    } catch (fallbackErr) {
      throw new Error(
        `Не удалось загрузить ${path}. Прокси: ${primaryErr}. Резерв: ${fallbackErr}`
      );
    }
  }
}

export const scheduleApi = {
  fetchIndex: () => get<ScheduleIndex>("meta/index.json"),
  fetchSchedule: (id: string) =>
    get<InstituteSchedule>(`institutes/${id}/schedule.json`),
};
