import { useState, useMemo } from "react";
import { useTeachers } from "../hooks/useSchedule";
import { useAppStore } from "../store";

export default function TeacherSearch() {
  const [query, setQuery] = useState("");
  const { data, isLoading, isError } = useTeachers();
  const setTeacher = useAppStore((s) => s.setTeacher);

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    if (!q) return data.teachers;
    return data.teachers.filter((t) => t.name.toLowerCase().includes(q));
  }, [data, query]);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-40 gap-2 text-gray-400 dark:text-gray-500 text-sm">
        <div className="w-5 h-5 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
        Загрузка базы преподавателей...
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="p-6 text-center text-sm text-gray-500 dark:text-gray-400">
        Не удалось загрузить список преподавателей.
        <br />
        <span className="text-xs">Данные появятся после ближайшего обновления расписания.</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <div className="sticky top-[56px] z-10 bg-white dark:bg-gray-900 px-4 py-3 border-b border-gray-200 dark:border-gray-700">
        <input
          autoFocus
          type="search"
          placeholder="Фамилия преподавателя..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600
                     bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                     placeholder-gray-400 dark:placeholder-gray-500
                     focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm"
        />
        {query && (
          <div className="text-xs text-gray-400 dark:text-gray-500 mt-1.5">
            {filtered.length === 0
              ? "Не найдено"
              : `${filtered.length} преп${filtered.length === 1 ? "одаватель" : "одавателей"}`}
          </div>
        )}
      </div>

      <ul>
        {filtered.map((teacher) => {
          const institutes = [...new Set(teacher.lessons.map((l) => l.is))];
          return (
            <li key={teacher.name}>
              <button
                onClick={() => setTeacher(teacher.name)}
                className="w-full text-left px-4 py-3 border-b border-gray-100 dark:border-gray-800
                           hover:bg-indigo-50 dark:hover:bg-indigo-900/20 transition-colors"
              >
                <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
                  {teacher.name}
                </div>
                <div className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                  {institutes.join(", ")}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
