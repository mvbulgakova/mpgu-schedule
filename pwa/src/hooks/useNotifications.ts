import { useEffect } from "react";
import type { Lesson, WeekSchedule } from "../types/schedule";
import { useAppStore } from "../store";

type DayKey = "monday" | "tuesday" | "wednesday" | "thursday" | "friday" | "saturday";

const DAY_KEYS: DayKey[] = [
  "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
];

function todayKey(): DayKey | null {
  const d = new Date().getDay(); // 0=Sun
  const idx = d === 0 ? null : d - 1;
  return idx !== null && idx < DAY_KEYS.length ? DAY_KEYS[idx] : null;
}

function todayLessons(schedule: WeekSchedule, showEven: boolean): Lesson[] {
  const day = todayKey();
  if (!day) return [];
  const week = showEven ? schedule.even_week : schedule.odd_week;
  return week[day] ?? [];
}

async function sendToSW(type: string, payload?: object) {
  if (!("serviceWorker" in navigator)) return;
  const reg = await navigator.serviceWorker.ready;
  if (!reg.active) return;
  reg.active.postMessage({ type, ...payload });
}

export function useNotifications(schedule: WeekSchedule | undefined) {
  const enabled = useAppStore((s) => s.notificationsEnabled);
  const minutesBefore = useAppStore((s) => s.notifyMinutesBefore);
  const showEvenWeek = useAppStore((s) => s.showEvenWeek);

  // Пересылаем расписание в SW при любом изменении настроек
  useEffect(() => {
    if (!enabled || !schedule) {
      sendToSW("CLEAR_NOTIFICATIONS");
      return;
    }
    const lessons = todayLessons(schedule, showEvenWeek);
    sendToSW("SCHEDULE_LESSONS", { lessons, minutesBefore });
  }, [enabled, schedule, minutesBefore, showEvenWeek]);
}

export async function requestNotificationPermission(
  onGranted: () => void,
  onDenied: () => void
) {
  if (!("Notification" in window)) {
    onDenied();
    return;
  }
  if (Notification.permission === "granted") {
    onGranted();
    return;
  }
  const result = await Notification.requestPermission();
  result === "granted" ? onGranted() : onDenied();
}
