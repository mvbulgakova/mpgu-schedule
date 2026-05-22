import { useAppStore, type NotifyMinutes } from "../store";
import { requestNotificationPermission } from "../hooks/useNotifications";

const MINUTES_OPTIONS: { value: NotifyMinutes; label: string }[] = [
  { value: 5,  label: "за 5 мин"  },
  { value: 10, label: "за 10 мин" },
  { value: 15, label: "за 15 мин" },
  { value: 30, label: "за 30 мин" },
];

interface Props {
  onClose: () => void;
}

export default function NotificationSettings({ onClose }: Props) {
  const enabled = useAppStore((s) => s.notificationsEnabled);
  const minutesBefore = useAppStore((s) => s.notifyMinutesBefore);
  const setEnabled = useAppStore((s) => s.setNotificationsEnabled);
  const setMinutes = useAppStore((s) => s.setNotifyMinutesBefore);

  const toggle = () => {
    if (!enabled) {
      requestNotificationPermission(
        () => setEnabled(true),
        () => alert("Разрешите уведомления в настройках браузера")
      );
    } else {
      setEnabled(false);
    }
  };

  const notSupported = !("Notification" in window);

  return (
    <div className="fixed inset-0 z-20 flex items-end sm:items-center justify-center">
      {/* backdrop */}
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
      />

      <div className="relative w-full sm:max-w-sm bg-white dark:bg-gray-800 rounded-t-2xl sm:rounded-2xl p-5 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-800 dark:text-gray-100">
            Уведомления о занятиях
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xl leading-none"
          >
            ×
          </button>
        </div>

        {notSupported ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Ваш браузер не поддерживает уведомления.
          </p>
        ) : (
          <>
            {/* Toggle */}
            <div className="flex items-center justify-between py-2">
              <span className="text-sm text-gray-700 dark:text-gray-300">
                Включить уведомления
              </span>
              <button
                onClick={toggle}
                className={`relative w-11 h-6 rounded-full transition-colors ${
                  enabled ? "bg-indigo-600" : "bg-gray-300 dark:bg-gray-600"
                }`}
                aria-checked={enabled}
                role="switch"
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                    enabled ? "translate-x-5" : "translate-x-0"
                  }`}
                />
              </button>
            </div>

            {/* Minutes selector */}
            <div className={`mt-3 transition-opacity ${enabled ? "opacity-100" : "opacity-40 pointer-events-none"}`}>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                Предупреждать
              </p>
              <div className="grid grid-cols-4 gap-2">
                {MINUTES_OPTIONS.map(({ value, label }) => (
                  <button
                    key={value}
                    onClick={() => setMinutes(value)}
                    className={`py-2 rounded-xl text-sm font-medium border transition-colors ${
                      minutesBefore === value
                        ? "bg-indigo-600 text-white border-indigo-600"
                        : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-200 border-gray-200 dark:border-gray-600 hover:border-indigo-300"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <p className="mt-4 text-xs text-gray-400 dark:text-gray-500">
              Уведомления работают только для занятий сегодняшнего дня.
              Браузер должен быть открыт.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
