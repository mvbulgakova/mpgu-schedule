/**
 * MPGU Schedule — Service Worker: фоновые уведомления о занятиях.
 *
 * Импортируется в сгенерированный Workbox SW через importScripts.
 * Получает расписание через postMessage, устанавливает таймеры,
 * показывает уведомления даже когда вкладка свёрнута.
 */

const _timers = [];

function _clearTimers() {
  _timers.forEach((t) => clearTimeout(t));
  _timers.length = 0;
}

function _scheduleForDay(lessons, minutesBefore) {
  _clearTimers();

  const now = Date.now();
  for (const lesson of lessons) {
    const [h, m] = lesson.time_start.split(":").map(Number);
    const lessonMs = new Date().setHours(h, m, 0, 0);
    const notifyMs = lessonMs - minutesBefore * 60_000;
    const delay = notifyMs - now;

    if (delay <= 0) continue;

    const timer = setTimeout(() => {
      const parts = [lesson.teacher, lesson.room].filter(Boolean);
      self.registration.showNotification(
        `Через ${minutesBefore} мин: ${lesson.subject}`,
        {
          body: parts.length ? parts.join(" · ") : "Занятие начинается",
          icon: "icons/192.png",
          badge: "icons/192.png",
          tag: `mpgu-${lesson.time_start}`,
          renotify: false,
          data: { time_start: lesson.time_start },
        }
      );
    }, delay);

    _timers.push(timer);
  }
}

self.addEventListener("message", (event) => {
  if (!event.data) return;
  const { type, lessons, minutesBefore } = event.data;

  if (type === "SCHEDULE_LESSONS") {
    if (lessons && lessons.length > 0) {
      _scheduleForDay(lessons, minutesBefore ?? 10);
    } else {
      _clearTimers();
    }
  }

  if (type === "CLEAR_NOTIFICATIONS") {
    _clearTimers();
  }
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((list) => {
        const existing = list.find((c) => c.url && c.focus);
        if (existing) return existing.focus();
        return clients.openWindow(self.location.origin);
      })
  );
});
