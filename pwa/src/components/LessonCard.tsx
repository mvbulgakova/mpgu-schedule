import type { Lesson } from "../types/schedule";
import clsx from "clsx";

const TYPE_COLORS: Record<string, string> = {
  lecture: "bg-blue-50 border-blue-300 text-blue-800",
  practice: "bg-green-50 border-green-300 text-green-800",
  lab: "bg-purple-50 border-purple-300 text-purple-800",
  seminar: "bg-amber-50 border-amber-300 text-amber-800",
  other: "bg-gray-50 border-gray-300 text-gray-700",
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
}

export default function LessonCard({ lesson, slot }: Props) {
  const colors = TYPE_COLORS[lesson.type] ?? TYPE_COLORS.other;

  return (
    <div className={clsx("rounded-lg border px-3 py-2 text-sm", colors)}>
      <div className="flex items-start justify-between gap-2">
        <span className="font-semibold leading-tight flex-1">{lesson.subject}</span>
        <span className="text-xs whitespace-nowrap opacity-70 mt-0.5">
          {lesson.time_start}–{lesson.time_end}
        </span>
      </div>

      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1 text-xs opacity-80">
        {lesson.type !== "other" && (
          <span>{TYPE_LABELS[lesson.type]}</span>
        )}
        {lesson.teacher && <span>{lesson.teacher}</span>}
        {lesson.room && <span>ауд. {lesson.room}</span>}
        {lesson.subgroup && <span>п/г {lesson.subgroup}</span>}
      </div>
    </div>
  );
}
