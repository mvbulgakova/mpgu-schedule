import type { InstituteIndexEntry } from "../types/schedule";
import { useAppStore } from "../store";

interface Props {
  institutes: InstituteIndexEntry[];
}

// Preferred campus ordering. Campuses not listed here sort alphabetically after.
const CAMPUS_ORDER: Record<string, number> = {
  "КГФ": 0,
  "ИИИ": 1,
  "ИФТИС": 2,
};

function campusSortKey(campus: string | undefined): [number, string] {
  const label = campus ?? "";
  const priority = CAMPUS_ORDER[label];
  if (priority !== undefined) return [priority, ""];
  return [Object.keys(CAMPUS_ORDER).length, label];
}

interface CampusGroup {
  campus: string;
  campus_address: string;
  institutes: InstituteIndexEntry[];
}

function groupByCampus(institutes: InstituteIndexEntry[]): CampusGroup[] {
  const map = new Map<string, CampusGroup>();

  for (const inst of institutes) {
    const key = inst.campus ?? inst.campus_address ?? inst.name;
    if (!map.has(key)) {
      map.set(key, {
        campus: inst.campus ?? key,
        campus_address: inst.campus_address ?? "",
        institutes: [],
      });
    }
    map.get(key)!.institutes.push(inst);
  }

  // Sort institutes within each group alphabetically by name
  for (const group of map.values()) {
    group.institutes.sort((a, b) => a.name.localeCompare(b.name, "ru"));
  }

  // Sort groups by campus priority, then alphabetically
  return Array.from(map.values()).sort((a, b) => {
    const [pa, sa] = campusSortKey(a.campus);
    const [pb, sb] = campusSortKey(b.campus);
    if (pa !== pb) return pa - pb;
    return sa.localeCompare(sb, "ru");
  });
}

export default function InstituteSelector({ institutes }: Props) {
  const setInstitute = useAppStore((s) => s.setInstitute);
  const selected = useAppStore((s) => s.selectedInstituteId);

  const available = institutes.filter((i) => i.status === "ok");
  const groups = groupByCampus(available);

  return (
    <div className="p-4">
      <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 mb-3 uppercase tracking-wider">
        Выберите институт
      </h2>
      <div className="flex flex-col gap-4">
        {groups.map((group) => (
          <div key={group.campus}>
            <div className="text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500 mb-2 px-1">
              {group.campus}
              {group.campus_address && (
                <span className="font-normal normal-case tracking-normal ml-1">
                  · {group.campus_address}
                </span>
              )}
            </div>
            <div className="flex flex-col gap-2">
              {group.institutes.map((inst) => (
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
                  {inst.campus_note && (
                    <div className={`text-xs mt-0.5 italic ${selected === inst.id ? "text-indigo-200" : "text-gray-400 dark:text-gray-500"}`}>
                      {inst.campus_note}
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>
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
