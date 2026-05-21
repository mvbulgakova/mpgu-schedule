import type { InstituteIndexEntry } from "../types/schedule";
import { useAppStore } from "../store";

interface Props {
  institutes: InstituteIndexEntry[];
}

export default function InstituteSelector({ institutes }: Props) {
  const setInstitute = useAppStore((s) => s.setInstitute);
  const selected = useAppStore((s) => s.selectedInstituteId);

  const available = institutes.filter((i) => i.status === "ok");

  return (
    <div className="p-4">
      <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 mb-3 uppercase tracking-wider">
        Выберите институт
      </h2>
      <div className="flex flex-col gap-2">
        {available.map((inst) => (
          <button
            key={inst.id}
            onClick={() => setInstitute(inst.id)}
            className={`text-left rounded-xl px-4 py-3 border transition-colors ${
              selected === inst.id
                ? "bg-indigo-700 text-white border-indigo-700"
                : "bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100 border-gray-200 dark:border-gray-700 hover:border-indigo-300 dark:hover:bg-gray-700"
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="font-medium text-sm leading-snug">{inst.name}</div>
              {inst.campus && (
                <span className={`text-xs font-mono shrink-0 rounded px-1.5 py-0.5 leading-none mt-0.5 ${
                  selected === inst.id
                    ? "bg-indigo-600 text-indigo-100"
                    : "bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400"
                }`}>
                  {inst.campus}
                </span>
              )}
            </div>
            <div className={`text-xs mt-0.5 ${selected === inst.id ? "text-indigo-200" : "text-gray-400 dark:text-gray-500"}`}>
              {inst.campus_address && <span className="mr-2">{inst.campus_address}</span>}
              {inst.groups_count} {groupsWord(inst.groups_count)}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function groupsWord(n: number): string {
  if (n % 10 === 1 && n % 100 !== 11) return "группа";
  if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return "группы";
  return "групп";
}
