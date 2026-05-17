export type DayKey = "monday" | "tuesday" | "wednesday" | "thursday" | "friday" | "saturday";

export type LessonType = "lecture" | "practice" | "lab" | "seminar" | "other";

export type StudyForm = "full_time" | "part_time" | "correspondence";

export type Degree = "bachelor" | "specialist" | "master";

export interface Lesson {
  slot: number | null;
  time_start: string;
  time_end: string;
  subject: string;
  type: LessonType;
  teacher: string | null;
  room: string | null;
  subgroup: 1 | 2 | null;
  notes: string;
}

export type DaySchedule = Record<DayKey, Lesson[]>;

export interface WeekSchedule {
  odd_week: DaySchedule;
  even_week: DaySchedule;
}

export interface Group {
  name: string;
  year: number | null;
  form: StudyForm;
  degree: Degree;
  schedule: WeekSchedule;
}

export interface InstituteSchedule {
  institute_id: string;
  institute_name: string;
  short_name: string;
  academic_year: string;
  updated_at: string;
  parser_used: string;
  groups: Group[];
}

export interface InstituteIndexEntry {
  id: string;
  name: string;
  short_name: string;
  groups_count: number;
  updated_at: string;
  status: "ok" | "error";
  parser_used?: string;
  error?: string;
}

export interface ScheduleIndex {
  generated_at: string;
  academic_year: string;
  institutes: InstituteIndexEntry[];
}
