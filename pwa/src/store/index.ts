import { create } from "zustand";
import { persist } from "zustand/middleware";

export type NotifyMinutes = 5 | 10 | 15 | 30;

interface AppState {
  selectedInstituteId: string | null;
  selectedGroupName: string | null;
  showEvenWeek: boolean;
  darkMode: boolean;
  pinnedGroups: string[];
  notificationsEnabled: boolean;
  notifyMinutesBefore: NotifyMinutes;
  setInstitute: (id: string) => void;
  setGroup: (name: string) => void;
  toggleWeek: () => void;
  setWeek: (even: boolean) => void;
  toggleDarkMode: () => void;
  togglePin: (groupName: string) => void;
  setNotificationsEnabled: (enabled: boolean) => void;
  setNotifyMinutesBefore: (minutes: NotifyMinutes) => void;
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
      notificationsEnabled: false,
      notifyMinutesBefore: 10,

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
      setNotificationsEnabled: (enabled) => set({ notificationsEnabled: enabled }),
      setNotifyMinutesBefore: (minutes) => set({ notifyMinutesBefore: minutes }),
    }),
    { name: "mpgu-schedule-prefs" }
  )
);
