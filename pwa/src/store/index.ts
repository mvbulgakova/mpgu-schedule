import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AppState {
  selectedInstituteId: string | null;
  selectedGroupName: string | null;
  showEvenWeek: boolean;
  setInstitute: (id: string) => void;
  setGroup: (name: string) => void;
  toggleWeek: () => void;
  setWeek: (even: boolean) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      selectedInstituteId: null,
      selectedGroupName: null,
      showEvenWeek: false,

      setInstitute: (id) => set({ selectedInstituteId: id, selectedGroupName: null }),
      setGroup: (name) => set({ selectedGroupName: name }),
      toggleWeek: () => set((s) => ({ showEvenWeek: !s.showEvenWeek })),
      setWeek: (even) => set({ showEvenWeek: even }),
    }),
    { name: "mpgu-schedule-prefs" }
  )
);
