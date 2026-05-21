import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AppState {
  selectedInstituteId: string | null;
  selectedGroupName: string | null;
  showEvenWeek: boolean;
  darkMode: boolean;
  pinnedGroups: string[];
  teacherMode: boolean;
  selectedTeacher: string | null;
  setInstitute: (id: string) => void;
  setGroup: (name: string) => void;
  toggleWeek: () => void;
  setWeek: (even: boolean) => void;
  toggleDarkMode: () => void;
  togglePin: (groupName: string) => void;
  openTeacherSearch: () => void;
  closeTeacherSearch: () => void;
  setTeacher: (name: string | null) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      selectedInstituteId: null,
      selectedGroupName: null,
      showEvenWeek: false,
      darkMode:
        typeof window !== "undefined"
          ? window.matchMedia("(prefers-color-scheme: dark)").matches
          : false,
      pinnedGroups: [],
      teacherMode: false,
      selectedTeacher: null,

      setInstitute: (id) => set({ selectedInstituteId: id, selectedGroupName: null }),
      setGroup: (name) => set({ selectedGroupName: name }),
      toggleWeek: () => set((s) => ({ showEvenWeek: !s.showEvenWeek })),
      setWeek: (even) => set({ showEvenWeek: even }),
      toggleDarkMode: () => set((s) => ({ darkMode: !s.darkMode })),
      togglePin: (groupName) =>
        set((s) => ({
          pinnedGroups: s.pinnedGroups.includes(groupName)
            ? s.pinnedGroups.filter((n) => n !== groupName)
            : [...s.pinnedGroups, groupName],
        })),
      openTeacherSearch: () => set({ teacherMode: true, selectedTeacher: null }),
      closeTeacherSearch: () => set({ teacherMode: false, selectedTeacher: null }),
      setTeacher: (name) => set({ selectedTeacher: name }),
    }),
    { name: "mpgu-schedule-prefs" }
  )
);
