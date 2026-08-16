import type { CourseRecord, GraduationProgram } from "../api/studentInfo";

export const COURSE_RECORDS_KEY = "planUCourseRecords";
export const STUDENT_RECORD_KEY = "planUStudentRecord";
export const PROFILE_OVERRIDES_KEY = "planUProfileOverrides";
export const GRADUATION_OVERRIDE_KEY = "planUGraduationOverride";
export const STUDENT_PROFILE_UPDATED_EVENT = "plan-u:student-profile-updated";

/** 동기화 직후 사용자에게 보여줄 경고를 **페이지 리로드 너머로** 전달하는 자리.
 *
 * `InfoPage.handleSync`는 동기화가 끝나면 `window.location.reload()`로 화면 전체를
 * 다시 그린다(파생 상태가 많아 부분 갱신보다 안전하다는 기존 선택). 그래서 경고를
 * React state에만 담으면 리로드와 함께 사라진다 — my.pusan이 실패해도 사용자는
 * "동기화 완료"만 보게 된다. 리로드 직전에 여기 적고, 다시 뜬 화면이 읽어서 띄운 뒤
 * 지운다(1회성).
 */
export const SYNC_WARNING_KEY = "planUSyncWarning";

export type ProfileOverrides = {
  name: string;
  department?: string;
  major: string;
  academicYear: number;
};

export function normalizeAcademicYear(value: unknown) {
  const numericValue = typeof value === "string"
    ? Number(value.replaceAll("학년", "").trim())
    : Number(value);
  if (!Number.isInteger(numericValue) || numericValue < 1 || numericValue > 6) return null;
  return numericValue;
}

export function getDistinctProgramNames(department?: string | null, major?: string | null) {
  const names = [department, major]
    .map((value) => value?.trim())
    .filter((value): value is string => Boolean(value));

  return names.filter((name, index) => (
    names.findIndex((candidate) => candidate.localeCompare(name, "ko", { sensitivity: "base" }) === 0) === index
  ));
}

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
    if (!saved) return null;

    const parsed = JSON.parse(saved) as Partial<ProfileOverrides> & { academicYear?: unknown };
    const academicYear = normalizeAcademicYear(parsed.academicYear);
    if (typeof parsed.name !== "string" || academicYear === null) {
      return null;
    }

    return {
      name: parsed.name,
      department: typeof parsed.department === "string" ? parsed.department : undefined,
      major: typeof parsed.major === "string" ? parsed.major : "",
      academicYear,
    };
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
