import type { WeekSchedule as WeekScheduleType, DayKey } from "../types/schedule";
import DayCard from "./DayCard";
import { getDay } from "date-fns";

const DAYS: DayKey[] = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];

interface Props {
  schedule: WeekScheduleType;
  showEvenWeek: boolean;
}

export default function WeekSchedule({ schedule, showEvenWeek }: Props) {
  const week = showEvenWeek ? schedule.even_week : schedule.odd_week;

  const todayJsDay = getDay(new Date()); // 0=Sun, 1=Mon...
  const todayIndex = todayJsDay === 0 ? -1 : todayJsDay - 1; // -1 в воскресенье

  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 p-3">
      {DAYS.map((day, i) => (
        <DayCard
          key={day}
          day={day}
          lessons={week[day] ?? []}
          isToday={i === todayIndex}
        />
      ))}
    </div>
  );
}
