import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAppStore } from "./store";
import { useIndex, useInstituteManifest, useGroupSchedule } from "./hooks/useSchedule";
import { useOfflineCache } from "./hooks/useOfflineCache";
import { useNotifications } from "./hooks/useNotifications";
import InstituteSelector from "./components/InstituteSelector";
import GroupSelector from "./components/GroupSelector";
import WeekSchedule from "./components/WeekSchedule";
import NotificationSettings from "./components/NotificationSettings";
import { format, getISOWeek } from "date-fns";
import { ru } from "date-fns/locale";

const SUPPORTED_MANIFEST_VERSION = 1;

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 2 } },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ScheduleApp />
    </QueryClientProvider>
  );
}

function ScheduleApp() {
  const instituteId = useAppStore((s) => s.selectedInstituteId);
  const groupName = useAppStore((s) => s.selectedGroupName);
  const showEvenWeek = useAppStore((s) => s.showEvenWeek);
  const toggleWeek = useAppStore((s) => s.toggleWeek);
  const setInstitute = useAppStore((s) => s.setInstitute);
  const setGroup = useAppStore((s) => s.setGroup);
  const darkMode = useAppStore((s) => s.darkMode);
  const toggleDarkMode = useAppStore((s) => s.toggleDarkMode);

  const { data: index, isLoading: indexLoading, isError: indexError, refetch: refetchIndex } = useIndex();
  const cachedIndex = useOfflineCache("index", index);

  const {
    data: manifestData,
    isLoading: manifestLoading,
    isError: manifestError,
    refetch: refetchManifest,
  } = useInstituteManifest(instituteId);
  const cachedManifest = useOfflineCache(`manifest:${instituteId}`, manifestData);

  const groupMeta = cachedManifest?.groups.find((g) => g.name === groupName);

  const {
    data: groupData,
    isLoading: groupLoading,
    isError: groupError,
    refetch: refetchGroup,
  } = useGroupSchedule(instituteId, groupMeta?.file ?? null);
  const cachedGroup = useOfflineCache(`group:${instituteId}:${groupName}`, groupData);

  const setWeek = useAppStore((s) => s.setWeek);

  const [showNotifSettings, setShowNotifSettings] = useState(false);

  useNotifications(cachedGroup?.schedule);

  const today = new Date();
  const weekNum = getISOWeek(today);
  const isCurrentWeekEven = weekNum % 2 === 0;

  // Устанавливаем текущую неделю при каждом открытии приложения
  useEffect(() => {
    setWeek(isCurrentWeekEven);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Применяем/убираем класс dark на documentElement
  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [darkMode]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 font-sans max-w-2xl mx-auto">
      {/* Header */}
      <header className="bg-indigo-800 text-white px-4 py-3 flex items-center justify-between sticky top-0 z-10 shadow-md">
        <div className="flex items-center gap-2">
          {(instituteId || groupName) && (
            <button
              onClick={() => groupName ? setGroup("") : setInstitute("")}
              className="text-indigo-200 hover:text-white text-lg leading-none mr-1"
            >
              ←
            </button>
          )}
          <div>
            <div className="font-bold text-base leading-tight">Расписание МПГУ</div>
            {cachedManifest && (
              <div className="text-indigo-300 text-xs">
                {cachedManifest.short_name || cachedManifest.institute_name}
                {groupName && ` · ${groupName}`}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={toggleDarkMode}
            className="text-xs bg-indigo-700 hover:bg-indigo-600 rounded-lg px-2.5 py-1.5 border border-indigo-600"
            aria-label="Переключить тему"
          >
            {darkMode ? "☀️" : "🌙"}
          </button>

          {groupMeta && (
            <>
              <button
                onClick={() => setShowNotifSettings(true)}
                className="text-xs bg-indigo-700 hover:bg-indigo-600 rounded-lg px-2.5 py-1.5 border border-indigo-600"
                aria-label="Настройки уведомлений"
              >
                🔔
              </button>
              <button
                onClick={toggleWeek}
                className="text-xs bg-indigo-700 hover:bg-indigo-600 rounded-lg px-3 py-1.5 border border-indigo-600"
              >
                {showEvenWeek ? "Чётная" : "Нечётная"}
                <span className="text-indigo-400 ml-1">/ сменить</span>
              </button>
            </>
          )}
        </div>
      </header>

      {showNotifSettings && (
        <NotificationSettings onClose={() => setShowNotifSettings(false)} />
      )}

      {/* Offline notice */}
      {!navigator.onLine && (
        <div className="bg-amber-50 text-amber-700 text-xs text-center py-1.5 border-b border-amber-200">
          Офлайн · показываем кешированные данные
        </div>
      )}

      {/* Version upgrade notice */}
      {cachedManifest && typeof cachedManifest.version === "number" && cachedManifest.version > SUPPORTED_MANIFEST_VERSION && (
        <div className="bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 text-xs text-center py-1.5 border-b border-blue-200 dark:border-blue-800">
          Доступен новый формат данных. Обновите приложение.
        </div>
      )}

      {/* Content */}
      <main>
        {indexLoading && !cachedIndex && (
          <div className="flex justify-center items-center h-40 text-gray-400 dark:text-gray-500 text-sm">
            Загрузка...
          </div>
        )}

        {!indexLoading && !cachedIndex && (
          <div className="p-8 flex flex-col items-center gap-4 text-center">
            <div className="text-gray-400 dark:text-gray-500 text-sm">
              {indexError
                ? "Не удалось загрузить данные. Проверьте соединение."
                : "Нет данных."}
            </div>
            {indexError && (
              <button
                onClick={() => refetchIndex()}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors"
              >
                Попробовать снова
              </button>
            )}
          </div>
        )}

        {cachedIndex && !instituteId && (
          <InstituteSelector institutes={cachedIndex.institutes} />
        )}

        {cachedIndex && instituteId && !groupName && (
          <>
            {manifestLoading && !cachedManifest && (
              <div className="flex justify-center items-center h-40 text-gray-400 dark:text-gray-500 text-sm">
                Загрузка групп...
              </div>
            )}
            {!manifestLoading && manifestError && !cachedManifest && (
              <div className="p-8 flex flex-col items-center gap-4 text-center">
                <div className="text-gray-400 dark:text-gray-500 text-sm">
                  Не удалось загрузить список групп.
                </div>
                <button
                  onClick={() => refetchManifest()}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors"
                >
                  Попробовать снова
                </button>
              </div>
            )}
            {cachedManifest && (
              <GroupSelector groups={cachedManifest.groups} />
            )}
          </>
        )}

        {groupMeta && (
          <>
            {groupLoading && !cachedGroup && (
              <div className="flex justify-center items-center h-40 text-gray-400 dark:text-gray-500 text-sm">
                Загрузка расписания...
              </div>
            )}
            {!groupLoading && groupError && !cachedGroup && (
              <div className="p-8 flex flex-col items-center gap-4 text-center">
                <div className="text-gray-400 dark:text-gray-500 text-sm">
                  Не удалось загрузить расписание группы.
                </div>
                <button
                  onClick={() => refetchGroup()}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors"
                >
                  Попробовать снова
                </button>
              </div>
            )}
            {cachedGroup && (
              <>
                <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {format(today, "EEEE, d MMMM", { locale: ru })} · {weekNum} неделя
                  </span>
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                    showEvenWeek === isCurrentWeekEven
                      ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400"
                      : "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400"
                  }`}>
                    {showEvenWeek ? "чётная" : "нечётная"}{showEvenWeek === isCurrentWeekEven ? " (сейчас)" : ""}
                  </span>
                </div>
                <WeekSchedule schedule={cachedGroup.schedule} showEvenWeek={showEvenWeek} />
                <div className="text-center text-xs text-gray-300 dark:text-gray-600 py-4">
                  Обновлено: {cachedManifest?.updated_at
                    ? format(new Date(cachedManifest.updated_at), "d MMM HH:mm", { locale: ru })
                    : "—"}
                </div>
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}
