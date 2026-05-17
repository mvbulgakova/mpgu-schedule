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

export default function GroupSelector({ groups }: Props) {
  const setGroup = useAppStore((s) => s.setGroup);
  const selected = useAppStore((s) => s.selectedGroupName);
  const back = useAppStore((s) => s.setInstitute);
  const instituteId = useAppStore((s) => s.selectedInstituteId)!;

  // группируем по степени
  const byDegree = groups.reduce<Record<string, Group[]>>((acc, g) => {
    const key = g.degree ?? "bachelor";
    if (!acc[key]) acc[key] = [];
    acc[key].push(g);
    return acc;
  }, {});

  return (
    <div className="p-4">
      <button
        onClick={() => back(instituteId)}
        className="text-sm text-indigo-600 mb-3 flex items-center gap-1"
      >
        ← Назад
      </button>
      <h2 className="text-sm font-semibold text-gray-500 mb-3 uppercase tracking-wider">
        Выберите группу
      </h2>

      {Object.entries(byDegree).map(([degree, gs]) => (
        <div key={degree} className="mb-4">
          <div className="text-xs font-bold text-gray-400 mb-2 uppercase">
            {DEGREE_LABELS[degree] ?? degree}
          </div>
          <div className="grid grid-cols-2 gap-2">
            {gs.sort((a, b) => (a.year ?? 0) - (b.year ?? 0) || a.name.localeCompare(b.name))
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
                  {g.year && (
                    <div className={`text-xs ${selected === g.name ? "text-indigo-200" : "text-gray-400"}`}>
                      {g.year} курс · {FORM_LABELS[g.form] ?? g.form}
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
