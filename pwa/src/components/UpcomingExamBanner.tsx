import { useMemo } from "react";
import type { ExamEntry } from "../types/schedule";
import { differenceInCalendarDays, parseISO } from "date-fns";

interface Props {
  entries: ExamEntry[];
  groupName: string;
  onViewExams: () => void;
}

export default function UpcomingExamBanner({ entries, groupName, onViewExams }: Props) {
  const next = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return entries
      .filter((e) => e.groups.includes(groupName))
      .map((e) => ({ ...e, days: differenceInCalendarDays(parseISO(e.date), today) }))
      .filter((e) => e.days >= 0)
      .sort((a, b) => a.days - b.days || a.time_start.localeCompare(b.time_start))[0] ?? null;
  }, [entries, groupName]);

  if (!next || next.days > 30) return null;

  const label =
    next.days === 0 ? "сегодня" :
    next.days === 1 ? "завтра" :
    `через ${next.days} дн.`;

  const isUrgent = next.days <= 3;
  const typeWord = next.type === "exam" ? "Экзамен" : next.type === "credit" ? "Зачёт" : "Занятие";

  return (
    <button
      onClick={onViewExams}
      className={`w-full text-left px-4 py-2.5 flex items-center justify-between gap-3 border-b transition-colors ${
        isUrgent
          ? "bg-orange-50 dark:bg-orange-900/20 border-orange-200 dark:border-orange-800 hover:bg-orange-100 dark:hover:bg-orange-900/30"
          : "bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 hover:bg-blue-100 dark:hover:bg-blue-900/30"
      }`}
    >
      <div className="min-w-0">
        <div className={`text-xs font-semibold truncate ${
          isUrgent ? "text-orange-700 dark:text-orange-400" : "text-blue-700 dark:text-blue-400"
        }`}>
          {typeWord} · {label}
        </div>
        <div className="text-xs text-gray-600 dark:text-gray-300 truncate mt-0.5">
          {next.subject}
        </div>
      </div>
      <span className={`text-xs shrink-0 ${
        isUrgent ? "text-orange-500 dark:text-orange-400" : "text-blue-400 dark:text-blue-500"
      }`}>
        Сессия →
      </span>
    </button>
  );
}
