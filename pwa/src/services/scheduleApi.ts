import type {
  ScheduleIndex,
  InstituteManifest,
  Group,
  TeachersIndex,
  TeacherScheduleDoc,
  InstituteExams,
} from "../types/schedule";

declare const __DATA_BASE_URL__: string;
declare const __DATA_FALLBACK_URL__: string;

const PRIMARY = __DATA_BASE_URL__;
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
  fetchManifest: (id: string) =>
    get<InstituteManifest>(`institutes/${id}/schedule.json`),
  fetchGroup: (id: string, file: string) =>
    get<Group>(`institutes/${id}/groups/${file}.json`),
  fetchTeachersIndex: () => get<TeachersIndex>("meta/teachers.json"),
  fetchTeacherSchedule: (slug: string) =>
    get<TeacherScheduleDoc>(`teachers/${slug}.json`),
  fetchExams: (id: string) =>
    get<InstituteExams>(`institutes/${id}/exams.json`),
};

/** Имя файла .ics из кода группы — должно совпадать с _safe() в build_ical.py. */
function safeIcalName(groupName: string): string {
  return groupName.trim().replace(/[^\p{L}\p{N}_-]/gu, "_");
}

/** webcal:// ссылка для подписки на расписание группы в календаре. */
export function groupIcalUrl(instituteId: string, groupName: string): string {
  const httpUrl = `${PRIMARY}/ical/${instituteId}/${safeIcalName(groupName)}.ics`;
  return httpUrl.replace(/^https?:\/\//, "webcal://");
}

