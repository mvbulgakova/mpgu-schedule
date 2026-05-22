import type { Lesson } from "../types/schedule";
import type { ReactNode } from "react";
import clsx from "clsx";

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

interface Props {
  lesson: Lesson;
  slot: number;
  isNow?: boolean;
  badge?: ReactNode;
}

export default function LessonCard({ lesson, slot: _slot, isNow, badge }: Props) {
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

      {badge && <div className="mt-1">{badge}</div>}

      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1 text-xs opacity-80">
        {lesson.type !== "other" && (
          <span>{TYPE_LABELS[lesson.type]}</span>
        )}
        {lesson.teacher && <span>{lesson.teacher}</span>}
        {lesson.notes && <span className="italic opacity-60">{lesson.notes}</span>}
        {lesson.room && (
          /^https?:\/\/|zoom\.us|teams\.microsoft\.com|meet\.|webex\.|el\.mpgu\.su/.test(lesson.room) ? (
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
