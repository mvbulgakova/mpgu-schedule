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

// Лёгкий манифест института (без данных расписания)
export interface GroupMeta {
  name: string;
  file: string;        // имя файла без .json в groups/
  year: number | null;
  form: StudyForm;
  degree: Degree;
}

export interface InstituteManifest {
  version?: number;
  institute_id: string;
  institute_name: string;
  short_name: string;
  academic_year: string;
  updated_at: string;
  parser_used: string;
  groups: GroupMeta[];
}

export interface InstituteIndexEntry {
  id: string;
  name: string;
  short_name: string;
  campus?: string;
  campus_address?: string;
  campus_note?: string;
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

// ──────────────────────────────────────────────
// Exam / session types
// ──────────────────────────────────────────────

export type ExamType = "exam" | "credit" | "unknown";

export interface ExamEntry {
  date: string;          // "YYYY-MM-DD"
  time_start: string;    // "HH:MM"
  time_end: string | null;
  subject: string;
  type: ExamType;
  teacher: string | null;
  room: string | null;
  groups: string[];
}

export interface InstituteExams {
  institute_id: string;
  updated_at: string;
  entries: ExamEntry[];
}

// ──────────────────────────────────────────────
// Teacher types
// ──────────────────────────────────────────────

export interface TeacherMeta {
  id: number;
  staff_slug: string;
  full_name: string;
  last: string;
  first: string;
  patronymic: string;
  abbreviated: string;
  position: string;
  institute_id: string;
  kafedra_name: string;
  has_schedule?: boolean;
}

export interface TeachersIndex {
  generated_at: string;
  count: number;
  teachers: TeacherMeta[];
}

export interface TeacherLesson extends Omit<Lesson, "teacher"> {
  institute_id: string;
  group_name: string;
}

export type TeacherDaySchedule = Record<DayKey, TeacherLesson[]>;

export interface TeacherWeekSchedule {
  odd_week: TeacherDaySchedule;
  even_week: TeacherDaySchedule;
}

export interface TeacherScheduleDoc extends TeacherMeta {
  schedule: TeacherWeekSchedule;
}
