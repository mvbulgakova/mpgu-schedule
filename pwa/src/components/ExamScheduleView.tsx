import { useMemo } from "react";
import type { ExamEntry } from "../types/schedule";
import { differenceInCalendarDays, parseISO, format } from "date-fns";
import { ru } from "date-fns/locale";

interface Props {
  entries: ExamEntry[];
  groupName: string;
}

function countdownLabel(date: string): { label: string; urgent: boolean } {
  const days = differenceInCalendarDays(parseISO(date), new Date());
  if (days < 0) return { label: "прошло", urgent: false };
  if (days === 0) return { label: "сегодня", urgent: true };
  if (days === 1) return { label: "завтра", urgent: true };
  if (days <= 7) return { label: `через ${days} дн.`, urgent: true };
  return { label: `через ${days} дн.`, urgent: false };
}

function typeLabel(type: string): string {
  if (type === "exam") return "Экзамен";
  if (type === "credit") return "Зачёт";
  return "Занятие";
}

function typeColor(type: string): string {
  if (type === "exam") return "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400";
  if (type === "credit") return "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400";
  return "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400";
}

export default function ExamScheduleView({ entries, groupName }: Props) {
  const filtered = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return entries
      .filter((e) => e.groups.includes(groupName))
      .sort((a, b) => {
        const d = a.date.localeCompare(b.date);
        return d !== 0 ? d : a.time_start.localeCompare(b.time_start);
      });
  }, [entries, groupName]);

  if (filtered.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-40 text-gray-400 dark:text-gray-500 text-sm gap-2">
        <span className="text-3xl">📭</span>
        <span>Нет данных о сессии для этой группы</span>
      </div>
    );
  }

  // Group by date
  const byDate = new Map<string, ExamEntry[]>();
  for (const e of filtered) {
    if (!byDate.has(e.date)) byDate.set(e.date, []);
    byDate.get(e.date)!.push(e);
  }

  return (
    <div className="divide-y divide-gray-100 dark:divide-gray-800">
      {[...byDate.entries()].map(([date, dayEntries]) => {
        const parsed = parseISO(date);
        const dayStr = format(parsed, "d MMMM, EEEE", { locale: ru });
        const { label: cdLabel, urgent: cdUrgent } = countdownLabel(date);
        const isPast = differenceInCalendarDays(parsed, new Date()) < 0;

        return (
          <div key={date} className={isPast ? "opacity-50" : ""}>
            {/* Date header */}
            <div className="flex items-center justify-between px-4 py-2 bg-gray-50 dark:bg-gray-800/60">
              <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 capitalize">
                {dayStr}
              </span>
              <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                isPast
                  ? "bg-gray-100 text-gray-400 dark:bg-gray-700 dark:text-gray-500"
                  : cdUrgent
                  ? "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-400"
                  : "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400"
              }`}>
                {cdLabel}
              </span>
            </div>

            {/* Entries for this date */}
            {dayEntries.map((e, i) => (
              <div
                key={i}
                className="px-4 py-3 bg-white dark:bg-gray-900 flex flex-col gap-1"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium text-gray-900 dark:text-gray-100 leading-snug flex-1">
                    {e.subject}
                  </span>
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full shrink-0 ${typeColor(e.type)}`}>
                    {typeLabel(e.type)}
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-gray-500 dark:text-gray-400">
                  <span className="font-medium text-gray-700 dark:text-gray-300">
                    {e.time_start}{e.time_end ? `–${e.time_end}` : ""}
                  </span>
                  {e.teacher && <span>{e.teacher}</span>}
                  {e.room && (
                    <span className="flex items-center gap-0.5">
                      <span className="text-gray-400">📍</span>
                      {e.room}
                    </span>
                  )}
                </div>

                {e.groups.length > 1 && (
                  <div className="flex flex-wrap gap-1 mt-0.5">
                    {e.groups.map((g) => (
                      <span
                        key={g}
                        className={`text-xs px-1.5 py-0.5 rounded ${
                          g === groupName
                            ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-400 font-medium"
                            : "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400"
                        }`}
                      >
                        {g}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
