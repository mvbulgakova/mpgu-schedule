import { useMemo } from "react";
import type { TeacherEntry, DayKey } from "../types/schedule";
import LessonCard from "./LessonCard";

const DAY_ORDER: DayKey[] = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];

const DAY_NAMES: Record<DayKey, string> = {
  monday: "Понедельник",
  tuesday: "Вторник",
  wednesday: "Среда",
  thursday: "Четверг",
  friday: "Пятница",
  saturday: "Суббота",
};

interface DayBlock {
  day: DayKey;
  lessons: Array<{
    week: "odd_week" | "even_week" | "both";
    group: string;
    instituteShort: string;
    slot: number | null;
    ts: string;
    te: string;
    subject: string;
    type: string;
    room: string | null;
    subgroup: 1 | 2 | null;
  }>;
}

interface Props {
  teacher: TeacherEntry;
  showEvenWeek: boolean;
}

export default function TeacherSchedule({ teacher, showEvenWeek }: Props) {
  const week = showEvenWeek ? "even_week" : "odd_week";
  const otherWeek = showEvenWeek ? "odd_week" : "even_week";

  const dayBlocks: DayBlock[] = useMemo(() => {
    // Build a map: day → list of lessons for the current week
    const byDay = new Map<DayKey, DayBlock["lessons"]>();
    DAY_ORDER.forEach((d) => byDay.set(d, []));

    // Collect current-week lessons, annotate if same slot exists in other week
    const currentLessons = teacher.lessons.filter((l) => l.w === week);
    const otherKeys = new Set(
      teacher.lessons
        .filter((l) => l.w === otherWeek)
        .map((l) => `${l.d}|${l.sl}|${l.ts}|${l.s}|${l.g}`)
    );

    currentLessons.forEach((l) => {
      const key = `${l.d}|${l.sl}|${l.ts}|${l.s}|${l.g}`;
      const weekLabel = otherKeys.has(key) ? "both" : week;
      byDay.get(l.d)?.push({
        week: weekLabel,
        group: l.g,
        instituteShort: l.is,
        slot: l.sl,
        ts: l.ts,
        te: l.te,
        subject: l.s,
        type: l.t,
        room: l.r,
        subgroup: l.sg,
      });
    });

    return DAY_ORDER.map((day) => ({
      day,
      lessons: (byDay.get(day) ?? []).sort((a, b) => {
        const slotDiff = (a.slot ?? 99) - (b.slot ?? 99);
        if (slotDiff !== 0) return slotDiff;
        return a.ts.localeCompare(b.ts);
      }),
    })).filter((block) => block.lessons.length > 0);
  }, [teacher, week, otherWeek]);

  if (dayBlocks.length === 0) {
    return (
      <div className="text-sm text-gray-400 dark:text-gray-500 text-center py-10">
        Нет занятий на {showEvenWeek ? "чётной" : "нечётной"} неделе
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      {dayBlocks.map(({ day, lessons }) => (
        <div key={day}>
          <div className="text-xs font-bold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-2">
            {DAY_NAMES[day]}
          </div>
          <div className="flex flex-col gap-2">
            {lessons.map((l, i) => (
              <div key={i} className="flex gap-2 items-start">
                <LessonCard
                  lesson={{
                    slot: l.slot,
                    time_start: l.ts,
                    time_end: l.te,
                    subject: l.subject,
                    type: l.type as never,
                    teacher: null,
                    room: l.room,
                    subgroup: l.subgroup,
                    notes: l.week === "both" ? "" : l.week === "odd_week" ? "нечётная неделя" : "чётная неделя",
                  }}
                  slot={l.slot ?? i + 1}
                  isNow={false}
                  badge={
                    <span className="text-xs text-indigo-600 dark:text-indigo-400 font-medium">
                      {l.group}
                      {l.subgroup ? ` (п/г ${l.subgroup})` : ""}
                      {" · "}
                      <span className="text-gray-400 dark:text-gray-500">{l.instituteShort}</span>
                    </span>
                  }
                />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
