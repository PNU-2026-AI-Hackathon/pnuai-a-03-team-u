import type { CourseRecord, GraduationProgram } from "../api/studentInfo";

export const COURSE_RECORDS_KEY = "planUCourseRecords";
export const STUDENT_RECORD_KEY = "planUStudentRecord";
export const PROFILE_OVERRIDES_KEY = "planUProfileOverrides";
export const GRADUATION_OVERRIDE_KEY = "planUGraduationOverride";
export const STUDENT_PROFILE_UPDATED_EVENT = "plan-u:student-profile-updated";

export type ProfileOverrides = {
  name: string;
  department?: string;
  major: string;
  academicYear: number;
};

export function readStoredCourses() {
  try {
    const saved = window.sessionStorage.getItem(COURSE_RECORDS_KEY);
    return saved ? (JSON.parse(saved) as CourseRecord[]) : [];
  } catch {
    return [];
  }
}

export function readStoredStudentRecord() {
  try {
    const saved = window.sessionStorage.getItem(STUDENT_RECORD_KEY);
    return saved ? (JSON.parse(saved) as Record<string, string>) : {};
  } catch {
    return {};
  }
}

export function readProfileOverrides(): ProfileOverrides | null {
  try {
    const saved = window.sessionStorage.getItem(PROFILE_OVERRIDES_KEY);
    return saved ? (JSON.parse(saved) as ProfileOverrides) : null;
  } catch {
    return null;
  }
}

export function readGraduationOverride(): GraduationProgram | null {
  try {
    const saved = window.sessionStorage.getItem(GRADUATION_OVERRIDE_KEY);
    return saved ? (JSON.parse(saved) as GraduationProgram) : null;
  } catch {
    return null;
  }
}

export function notifyStudentProfileUpdated() {
  window.dispatchEvent(new Event(STUDENT_PROFILE_UPDATED_EVENT));
}
