import type { Lesson, DayKey } from "../types/schedule";
import LessonCard from "./LessonCard";

const DAY_NAMES: Record<DayKey, string> = {
  monday: "Пн",
  tuesday: "Вт",
  wednesday: "Ср",
  thursday: "Чт",
  friday: "Пт",
  saturday: "Сб",
};

const DAY_NAMES_FULL: Record<DayKey, string> = {
  monday: "Понедельник",
  tuesday: "Вторник",
  wednesday: "Среда",
  thursday: "Четверг",
  friday: "Пятница",
  saturday: "Суббота",
};

interface Props {
  day: DayKey;
  lessons: Lesson[];
  isToday?: boolean;
  currentTime?: string; // "HH:MM", передаётся только для сегодняшнего дня
  showFullName?: boolean; // force full day name (used in mobile single-day view)
}

export default function DayCard({ day, lessons, isToday, currentTime, showFullName }: Props) {
  const hasLessons = lessons.length > 0;

  return (
    <div className="min-w-0">
      <div className={`text-xs font-bold uppercase tracking-wider mb-2 ${
        isToday ? "text-indigo-700 dark:text-indigo-400" : "text-gray-400 dark:text-gray-500"
      }`}>
        {showFullName ? (
          <span>{DAY_NAMES_FULL[day]}</span>
        ) : (
          <>
            <span className="sm:hidden">{DAY_NAMES[day]}</span>
            <span className="hidden sm:inline">{DAY_NAMES_FULL[day]}</span>
          </>
        )}
        {isToday && <span className="ml-1 text-indigo-500 dark:text-indigo-400">●</span>}
      </div>

      {hasLessons ? (
        <div className="flex flex-col gap-2">
          {lessons
            .filter((lesson) => lesson.subject?.trim())
            .slice()
            .sort((a, b) => {
              const slotDiff = (a.slot ?? 99) - (b.slot ?? 99);
              if (slotDiff !== 0) return slotDiff;
              return (a.time_start ?? "").localeCompare(b.time_start ?? "");
            })
            .map((lesson, i) => (
              <LessonCard
                key={i}
                lesson={lesson}
                slot={lesson.slot ?? i + 1}
                isNow={
                  currentTime !== undefined &&
                  lesson.time_start <= currentTime &&
                  currentTime < lesson.time_end
                }
              />
            ))}
        </div>
      ) : (
        <div className="text-xs text-gray-300 dark:text-gray-600 text-center py-4">—</div>
      )}
    </div>
  );
}
