import { useEffect, useRef, useState } from "react";
import type { TeacherWeekSchedule, TeacherLesson, DayKey } from "../types/schedule";
import clsx from "clsx";
import { getDay } from "date-fns";

const DAYS: DayKey[] = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const DAY_ABBR = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];
const DAY_FULL: Record<DayKey, string> = {
  monday: "Понедельник",
  tuesday: "Вторник",
  wednesday: "Среда",
  thursday: "Четверг",
  friday: "Пятница",
  saturday: "Суббота",
};

const TYPE_COLORS: Record<string, string> = {
  lecture:
    "bg-blue-50 dark:bg-blue-900/30 border-blue-300 dark:border-blue-700 text-blue-800 dark:text-blue-200",
  practice:
    "bg-green-50 dark:bg-green-900/30 border-green-300 dark:border-green-700 text-green-800 dark:text-green-200",
  lab:
    "bg-purple-50 dark:bg-purple-900/30 border-purple-300 dark:border-purple-700 text-purple-800 dark:text-purple-200",
  seminar:
    "bg-amber-50 dark:bg-amber-900/30 border-amber-300 dark:border-amber-700 text-amber-800 dark:text-amber-200",
  other:
    "bg-gray-50 dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300",
};

const TYPE_LABELS: Record<string, string> = {
  lecture: "Лекция",
  practice: "Практика",
  lab: "Лабораторная",
  seminar: "Семинар",
  other: "",
};

function nowTime(): string {
  const d = new Date();
  return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

function TeacherLessonCard({ lesson, isNow }: { lesson: TeacherLesson; isNow?: boolean }) {
  const colors = isNow
    ? "bg-indigo-50 dark:bg-indigo-900/40 border-indigo-400 dark:border-indigo-600 text-indigo-900 dark:text-indigo-100 ring-2 ring-indigo-300 dark:ring-indigo-700"
    : (TYPE_COLORS[lesson.type] ?? TYPE_COLORS.other);

  return (
    <div className={clsx("rounded-lg border px-3 py-2 text-sm", colors)}>
      <div className="flex items-start justify-between gap-2">
        <span className="font-semibold leading-tight flex-1">{lesson.subject}</span>
        <div className="flex flex-col items-end gap-0.5 shrink-0">
          {isNow && (
            <span className="text-xs font-bold bg-indigo-600 text-white rounded px-1.5 py-0.5 leading-none">
              Сейчас
            </span>
          )}
          <span className="text-xs whitespace-nowrap opacity-70">
            {lesson.time_start}–{lesson.time_end}
          </span>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1 text-xs opacity-80">
        {lesson.type !== "other" && <span>{TYPE_LABELS[lesson.type]}</span>}
        <span className="font-medium">{lesson.group_name}</span>
        {lesson.room && (
          /^https?:\/\/|zoom\.us|teams\.microsoft|meet\.|webex\./.test(lesson.room) ? (
            <a
              href={lesson.room.startsWith("http") ? lesson.room : `https://${lesson.room}`}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2"
            >
              🔗 онлайн
            </a>
          ) : (
            <span>ауд. {lesson.room}</span>
          )
        )}
        {lesson.subgroup && <span>п/г {lesson.subgroup}</span>}
      </div>
    </div>
  );
}

function TeacherDayColumn({
  day,
  lessons,
  isToday,
  currentTime,
  showFullName,
}: {
  day: DayKey;
  lessons: TeacherLesson[];
  isToday?: boolean;
  currentTime?: string;
  showFullName?: boolean;
}) {
  const sorted = lessons
    .slice()
    .sort((a, b) => (a.slot ?? 99) - (b.slot ?? 99) || a.time_start.localeCompare(b.time_start));

  return (
    <div className="min-w-0">
      <div
        className={`text-xs font-bold uppercase tracking-wider mb-2 ${
          isToday ? "text-indigo-700 dark:text-indigo-400" : "text-gray-400 dark:text-gray-500"
        }`}
      >
        {showFullName ? (
          <span>{DAY_FULL[day]}</span>
        ) : (
          <>
            <span className="sm:hidden">{DAY_ABBR[DAYS.indexOf(day)]}</span>
            <span className="hidden sm:inline">{DAY_FULL[day]}</span>
          </>
        )}
        {isToday && <span className="ml-1 text-indigo-500 dark:text-indigo-400">●</span>}
      </div>

      {sorted.length > 0 ? (
        <div className="flex flex-col gap-2">
          {sorted.map((lesson, i) => (
            <TeacherLessonCard
              key={i}
              lesson={lesson}
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

interface Props {
  schedule: TeacherWeekSchedule;
  showEvenWeek: boolean;
}

export default function TeacherScheduleView({ schedule, showEvenWeek }: Props) {
  const week = showEvenWeek ? schedule.even_week : schedule.odd_week;
  const todayIdx = (() => {
    const d = getDay(new Date());
    return d === 0 ? -1 : d - 1;
  })();
  const currentTime = nowTime();

  const [selectedDayIdx, setSelectedDayIdx] = useState(todayIdx >= 0 ? todayIdx : 0);
  const todayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    todayRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  return (
    <>
      {/* Mobile: tab bar + single day */}
      <div className="sm:hidden">
        <div className="flex overflow-x-auto border-b border-gray-200 dark:border-gray-700 px-3">
          {DAYS.map((day, i) => (
            <button
              key={day}
              onClick={() => setSelectedDayIdx(i)}
              className={`flex-shrink-0 px-4 py-2 text-sm font-semibold transition-colors ${
                selectedDayIdx === i
                  ? "text-indigo-600 dark:text-indigo-400 border-b-2 border-indigo-600 dark:border-indigo-400"
                  : i === todayIdx
                  ? "text-indigo-400 dark:text-indigo-500"
                  : "text-gray-400 dark:text-gray-500"
              }`}
            >
              {DAY_ABBR[i]}
            </button>
          ))}
        </div>
        <div className="p-3">
          <TeacherDayColumn
            day={DAYS[selectedDayIdx]}
            lessons={week[DAYS[selectedDayIdx]] ?? []}
            isToday={selectedDayIdx === todayIdx}
            currentTime={selectedDayIdx === todayIdx ? currentTime : undefined}
            showFullName
          />
        </div>
      </div>

      {/* Desktop: 6-column grid */}
      <div className="hidden sm:grid sm:grid-cols-6 gap-3 p-3">
        {DAYS.map((day, i) => (
          <div key={day} ref={i === todayIdx ? todayRef : undefined}>
            <TeacherDayColumn
              day={day}
              lessons={week[day] ?? []}
              isToday={i === todayIdx}
              currentTime={i === todayIdx ? currentTime : undefined}
            />
          </div>
        ))}
      </div>
    </>
  );
}
