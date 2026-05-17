import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAppStore } from "./store";
import { useIndex, useInstituteSchedule } from "./hooks/useSchedule";
import { useOfflineCache } from "./hooks/useOfflineCache";
import InstituteSelector from "./components/InstituteSelector";
import GroupSelector from "./components/GroupSelector";
import WeekSchedule from "./components/WeekSchedule";
import { format, getISOWeek } from "date-fns";
import { ru } from "date-fns/locale";

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

  const { data: index, isLoading: indexLoading } = useIndex();
  const cachedIndex = useOfflineCache("index", index);

  const { data: scheduleData, isLoading: schedLoading } = useInstituteSchedule(instituteId);
  const cachedSchedule = useOfflineCache(`schedule:${instituteId}`, scheduleData);

  const group = cachedSchedule?.groups.find((g) => g.name === groupName);

  const today = new Date();
  const weekNum = getISOWeek(today);
  const isCurrentWeekEven = weekNum % 2 === 0;
  // автоматически устанавливаем текущую неделю при первом открытии
  // (это делается в useEffect, но для простоты просто показываем индикатор)

  return (
    <div className="min-h-screen bg-gray-50 font-sans max-w-2xl mx-auto">
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
            {cachedSchedule && (
              <div className="text-indigo-300 text-xs">
                {cachedSchedule.short_name || cachedSchedule.institute_name}
                {groupName && ` · ${groupName}`}
              </div>
            )}
          </div>
        </div>

        {group && (
          <button
            onClick={toggleWeek}
            className="text-xs bg-indigo-700 hover:bg-indigo-600 rounded-lg px-3 py-1.5 border border-indigo-600"
          >
            {showEvenWeek ? "Чётная" : "Нечётная"}
            <span className="text-indigo-400 ml-1">/ сменить</span>
          </button>
        )}
      </header>

      {/* Offline notice */}
      {!navigator.onLine && (
        <div className="bg-amber-50 text-amber-700 text-xs text-center py-1.5 border-b border-amber-200">
          Офлайн · показываем кешированные данные
        </div>
      )}

      {/* Content */}
      <main>
        {indexLoading && !cachedIndex && (
          <div className="flex justify-center items-center h-40 text-gray-400 text-sm">
            Загрузка...
          </div>
        )}

        {!indexLoading && !cachedIndex && (
          <div className="p-6 text-center text-gray-500 text-sm">
            Не удалось загрузить данные. Проверьте соединение.
          </div>
        )}

        {cachedIndex && !instituteId && (
          <InstituteSelector institutes={cachedIndex.institutes} />
        )}

        {cachedIndex && instituteId && !groupName && (
          <>
            {schedLoading && !cachedSchedule && (
              <div className="flex justify-center items-center h-40 text-gray-400 text-sm">
                Загрузка групп...
              </div>
            )}
            {cachedSchedule && (
              <GroupSelector groups={cachedSchedule.groups} />
            )}
          </>
        )}

        {group && (
          <>
            <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-white">
              <span className="text-xs text-gray-500">
                {format(today, "EEEE, d MMMM", { locale: ru })} · {weekNum} неделя
              </span>
              <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                showEvenWeek === isCurrentWeekEven
                  ? "bg-green-100 text-green-700"
                  : "bg-gray-100 text-gray-500"
              }`}>
                {showEvenWeek ? "чётная" : "нечётная"}{showEvenWeek === isCurrentWeekEven ? " (сейчас)" : ""}
              </span>
            </div>
            <WeekSchedule schedule={group.schedule} showEvenWeek={showEvenWeek} />
            <div className="text-center text-xs text-gray-300 py-4">
              Обновлено: {cachedSchedule?.updated_at
                ? format(new Date(cachedSchedule.updated_at), "d MMM HH:mm", { locale: ru })
                : "—"}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
