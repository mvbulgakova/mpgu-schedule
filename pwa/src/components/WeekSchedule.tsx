import { useEffect, useRef } from "react";
import type { WeekSchedule as WeekScheduleType, DayKey } from "../types/schedule";
import DayCard from "./DayCard";
import { getDay } from "date-fns";

const DAYS: DayKey[] = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];

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

  const todayRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    todayRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 p-3">
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
  );
}
