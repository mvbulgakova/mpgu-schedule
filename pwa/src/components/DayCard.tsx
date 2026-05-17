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
}

export default function DayCard({ day, lessons, isToday }: Props) {
  const hasLessons = lessons.length > 0;

  return (
    <div className="min-w-0">
      <div className={`text-xs font-bold uppercase tracking-wider mb-2 ${
        isToday ? "text-indigo-700" : "text-gray-400"
      }`}>
        <span className="sm:hidden">{DAY_NAMES[day]}</span>
        <span className="hidden sm:inline">{DAY_NAMES_FULL[day]}</span>
        {isToday && <span className="ml-1 text-indigo-500">●</span>}
      </div>

      {hasLessons ? (
        <div className="flex flex-col gap-2">
          {lessons
            .sort((a, b) => (a.slot ?? 9) - (b.slot ?? 9))
            .map((lesson, i) => (
              <LessonCard key={i} lesson={lesson} slot={lesson.slot ?? i + 1} />
            ))}
        </div>
      ) : (
        <div className="text-xs text-gray-300 text-center py-4">—</div>
      )}
    </div>
  );
}
