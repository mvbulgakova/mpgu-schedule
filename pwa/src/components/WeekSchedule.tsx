import { useEffect, useRef, useState } from "react";
import type { WeekSchedule as WeekScheduleType, DayKey } from "../types/schedule";
import DayCard from "./DayCard";
import { getDay } from "date-fns";

const DAYS: DayKey[] = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const DAY_ABBR = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];

interface Props {
  schedule: WeekScheduleType;
  showEvenWeek: boolean;
}

function nowTimeStr(): string {
  const d = new Date();
  return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

export default function WeekSchedule({ schedule, showEvenWeek }: Props) {
  const week = showEvenWeek ? schedule.even_week : schedule.odd_week;

  const now = new Date();
  const todayJsDay = getDay(now); // 0=Sun, 1=Mon...
  const todayIndex = todayJsDay === 0 ? -1 : todayJsDay - 1;
  const currentTime = nowTimeStr();

  // Mobile: initial selected day is today if Mon–Sat, otherwise Monday (0)
  const [selectedDayIdx, setSelectedDayIdx] = useState<number>(
    todayIndex >= 0 ? todayIndex : 0
  );

  const todayRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    todayRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  return (
    <>
      {/* ── Mobile view: tab bar + single day ── */}
      <div className="sm:hidden">
        {/* Horizontal scrollable tab bar */}
        <div className="flex overflow-x-auto border-b border-gray-200 dark:border-gray-700 px-3">
          {DAYS.map((day, i) => {
            const isToday = i === todayIndex;
            const isSelected = i === selectedDayIdx;
            return (
              <button
                key={day}
                onClick={() => setSelectedDayIdx(i)}
                className={`flex-shrink-0 px-4 py-2 text-sm font-semibold transition-colors ${
                  isSelected
                    ? "text-indigo-600 dark:text-indigo-400 border-b-2 border-indigo-600 dark:border-indigo-400"
                    : isToday
                    ? "text-indigo-400 dark:text-indigo-500"
                    : "text-gray-400 dark:text-gray-500"
                }`}
              >
                {DAY_ABBR[i]}
              </button>
            );
          })}
        </div>

        {/* Single day content */}
        <div className="p-3">
          {(() => {
            const day = DAYS[selectedDayIdx];
            const isToday = selectedDayIdx === todayIndex;
            return (
              <DayCard
                day={day}
                lessons={week[day] ?? []}
                isToday={isToday}
                currentTime={isToday ? currentTime : undefined}
                showFullName
              />
            );
          })()}
        </div>
      </div>

      {/* ── Desktop view: 6-column grid (unchanged) ── */}
      <div className="hidden sm:grid sm:grid-cols-6 gap-3 p-3">
        {DAYS.map((day, i) => {
          const isToday = i === todayIndex;
          return (
            <div key={day} ref={isToday ? todayRef : undefined}>
              <DayCard
                day={day}
                lessons={week[day] ?? []}
                isToday={isToday}
                currentTime={isToday ? currentTime : undefined}
              />
            </div>
          );
        })}
      </div>
    </>
  );
}
