import { useState, useMemo } from "react";
import type { TeacherMeta } from "../types/schedule";

interface Props {
  teachers: TeacherMeta[];
  onSelect: (teacher: TeacherMeta) => void;
}

export default function TeacherSearch({ teachers, onSelect }: Props) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return teachers
      .filter((t) => t.has_schedule !== false)
      .filter((t) =>
        t.full_name.toLowerCase().includes(q) ||
        t.last.toLowerCase().includes(q) ||
        t.abbreviated.toLowerCase().includes(q)
      )
      .slice(0, 20);
  }, [query, teachers]);

  return (
    <div className="p-4">
      <div className="relative mb-2">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">🔍</span>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Фамилия преподавателя…"
          autoFocus
          className="w-full pl-9 pr-4 py-2.5 rounded-xl border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
      </div>

      {query.trim() && filtered.length === 0 && (
        <p className="text-center text-sm text-gray-400 dark:text-gray-500 py-8">
          Не найдено
        </p>
      )}

      {!query.trim() && (
        <p className="text-center text-sm text-gray-400 dark:text-gray-500 py-8">
          Начните вводить фамилию
        </p>
      )}

      <ul className="divide-y divide-gray-100 dark:divide-gray-700">
        {filtered.map((t) => (
          <li key={t.staff_slug}>
            <button
              onClick={() => onSelect(t)}
              className="w-full text-left px-2 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors rounded-lg"
            >
              <div className="font-medium text-sm text-gray-900 dark:text-gray-100">
                {t.full_name || t.abbreviated}
              </div>
              {(t.position || t.kafedra_name) && (
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate">
                  {[t.position, t.kafedra_name].filter(Boolean).join(" · ")}
                </div>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
