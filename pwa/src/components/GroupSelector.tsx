import { useState, useMemo } from "react";
import type { Group } from "../types/schedule";
import { useAppStore } from "../store";

interface Props {
  groups: Group[];
}

const DEGREE_LABELS: Record<string, string> = {
  bachelor: "Бакалавриат",
  specialist: "Специалитет",
  master: "Магистратура",
};

const FORM_LABELS: Record<string, string> = {
  full_time: "Очная",
  part_time: "Очно-заочная",
  correspondence: "Заочная",
};

const DEGREE_ORDER = ["bachelor", "specialist", "master"];

export default function GroupSelector({ groups }: Props) {
  const setGroup = useAppStore((s) => s.setGroup);
  const selected = useAppStore((s) => s.selectedGroupName);
  const back = useAppStore((s) => s.setInstitute);
  const instituteId = useAppStore((s) => s.selectedInstituteId)!;

  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();

  const filtered = useMemo(
    () => (q ? groups.filter((g) => g.name.toLowerCase().includes(q)) : groups),
    [groups, q]
  );

  const byDegree = useMemo(
    () =>
      filtered.reduce<Record<string, Group[]>>((acc, g) => {
        const key = g.degree ?? "bachelor";
        (acc[key] ??= []).push(g);
        return acc;
      }, {}),
    [filtered]
  );

  const showSearch = groups.length > 8;

  return (
    <div className="p-4">
      <button
        onClick={() => back(instituteId)}
        className="text-sm text-indigo-600 mb-3 flex items-center gap-1"
      >
        ← Назад
      </button>

      {showSearch && (
        <div className="relative mb-4">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск группы…"
            className="w-full rounded-xl border border-gray-200 bg-white px-4 py-2.5 pr-9 text-sm text-gray-800 placeholder-gray-400 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
            autoFocus
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-lg leading-none"
              aria-label="Очистить"
            >
              ×
            </button>
          )}
        </div>
      )}

      {q && (
        <p className="text-xs text-gray-400 mb-3">
          {filtered.length === 0
            ? "Ничего не найдено"
            : `Найдено: ${filtered.length} из ${groups.length}`}
        </p>
      )}

      {!showSearch && (
        <h2 className="text-sm font-semibold text-gray-500 mb-3 uppercase tracking-wider">
          Выберите группу
        </h2>
      )}

      {DEGREE_ORDER.filter((d) => byDegree[d]?.length).map((degree) => (
        <div key={degree} className="mb-4">
          <div className="text-xs font-bold text-gray-400 mb-2 uppercase">
            {DEGREE_LABELS[degree] ?? degree}
          </div>
          <div className="grid grid-cols-2 gap-2">
            {byDegree[degree]
              .sort((a, b) => (a.year ?? 0) - (b.year ?? 0) || a.name.localeCompare(b.name))
              .map((g) => (
                <button
                  key={g.name}
                  onClick={() => setGroup(g.name)}
                  className={`rounded-xl px-3 py-2.5 border text-left transition-colors ${
                    selected === g.name
                      ? "bg-indigo-700 text-white border-indigo-700"
                      : "bg-white text-gray-800 border-gray-200 hover:border-indigo-300"
                  }`}
                >
                  <div className="font-semibold text-sm">{g.name}</div>
                  {(g.year || g.form !== "full_time") && (
                    <div className={`text-xs ${selected === g.name ? "text-indigo-200" : "text-gray-400"}`}>
                      {[g.year ? `${g.year} курс` : null, FORM_LABELS[g.form] ?? g.form]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                  )}
                </button>
              ))}
          </div>
        </div>
      ))}
    </div>
  );
}
