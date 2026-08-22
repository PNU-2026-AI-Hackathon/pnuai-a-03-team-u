import { apiClient } from "./client";

export const isMockStudentDataEnabled =
  import.meta.env.DEV && import.meta.env.VITE_USE_MOCK_STUDENT_DATA === "true";

/** 전적대 이수기록이 대체한 PNU 과목 하나. 교양은 세부영역 placeholder가 온다. */
export type SubstitutedCourse = {
  course_id: number;
  course_name: string;
  category: string | null;
};

export type CourseRecord = {
  id: number;
  course_name: string;
  category: string | null;
  /** One-Stop 학교 판정에서 확인된 효원균형교양 세부영역. */
  liberal_area?: string | null;
  credits: number | null;
  year: string | null;
  semester: string | null;
  grade: string | null;
  match_status: string;
  source: string;
  /** 편입/조기이수로 "입학 전 인정"된 행인지. 서버가 판정해서 내려준다 —
   * 이 행에만 "어떤 PNU 과목을 대체했나요?" 를 띄운다. */
  is_transfer_credit?: boolean;
  /** 학생이 직접 지정한 대체 대상 PNU 과목들. 학교가 무엇을 인정했는지는 데이터에
   * 없어서 시스템이 추측하지 않는다 — 지정 전에는 빈 목록이다.
   *
   * 한 줄이 여러 개를 대체할 수 있다: 전적대 `교양선택 15학점` 한 줄은 개별 과목이
   * 아니라 교양 세부영역 여러 개를 채운 것으로 인정받는다. */
  substitutes?: SubstitutedCourse[];
};

export type PortalSyncResponse = {
  student_record: Record<string, string>;
  courses: CourseRecord[];
  academic_programs: Array<{
    program_type: string;
    major: string | null;
  }>;
  graduation_table_count: number;
  /** my.pusan.ac.kr(비교과·자격증·어학) 크롤 성공 여부. false여도 HTTP는 200이다 —
   * 학적·성적 동기화까지 실패시키지 않으려는 백엔드의 의도된 동작이다.
   * 이 값을 무시하면 "동기화 완료"라고 안내하면서 비교과는 하나도 안 들어온다. */
  my_pusan_sso_ok: boolean;
  /** sso_ok=false일 때 왜 실패했는지(서버가 채운다). 구버전 백엔드에선 없다. */
  my_pusan_error?: string | null;
  activities_created: number;
  activities_updated: number;
  certifications_created: number;
  certifications_updated: number;
  language_scores_created: number;
  language_scores_updated: number;
};

export type GraduationCategory = {
  category_code: string;
  category_name: string;
  required_credits: number | null;
  earned_credits: number;
  remaining_credits: number | null;
  satisfied: boolean | null;
};

export type GraduationProgram = {
  user_academic_program_id: number;
  program_type: string;
  curriculum_year: string | null;
  requirement_found: boolean;
  required_total_credits: number | null;
  earned_total_credits: number;
  remaining_total_credits: number | null;
  satisfied: boolean | null;
  categories: GraduationCategory[];
  warnings: string[];
};

export type GraduationProgress = {
  user_id: number;
  programs: GraduationProgram[];
};

const mockCourses: CourseRecord[] = [
  { id: 1, course_name: "데이터베이스", category: "전공필수", liberal_area: null, credits: 3, year: "2026", semester: "1", grade: "A+", match_status: "matched", source: "mock" },
  { id: 2, course_name: "자료구조", category: "전공필수", liberal_area: null, credits: 3, year: "2026", semester: "1", grade: "A0", match_status: "matched", source: "mock" },
  { id: 3, course_name: "선형대수", category: "전공선택", liberal_area: null, credits: 3, year: "2026", semester: "1", grade: "B+", match_status: "matched", source: "mock" },
  { id: 4, course_name: "웹프로그래밍", category: "전공선택", liberal_area: null, credits: 3, year: "2026", semester: "1", grade: "A+", match_status: "matched", source: "mock" },
  { id: 5, course_name: "역사의 이해", category: "교양선택", liberal_area: "사상과역사", credits: 3, year: "2026", semester: "1", grade: "A0", match_status: "matched", source: "mock" },
  { id: 6, course_name: "Python Programming", category: "전공기초", liberal_area: null, credits: 3, year: "2025", semester: "2", grade: "A+", match_status: "matched", source: "mock" },
  { id: 7, course_name: "확률및통계 II", category: "전공기초", liberal_area: null, credits: 3, year: "2025", semester: "2", grade: "A0", match_status: "matched", source: "mock" },
  { id: 8, course_name: "인공지능과 디지털 사고", category: "교양필수", liberal_area: null, credits: 3, year: "2025", semester: "2", grade: "A+", match_status: "matched", source: "mock" },
  { id: 9, course_name: "현대사회와 문화", category: "교양선택", liberal_area: "사회와문화", credits: 3, year: "2025", semester: "2", grade: "A0", match_status: "matched", source: "mock" },
];

const mockGraduationProgress: GraduationProgress = {
  user_id: 0,
  programs: [
    {
      user_academic_program_id: 0,
      program_type: "primary",
      curriculum_year: "2023",
      requirement_found: true,
      required_total_credits: 130,
      earned_total_credits: 112,
      remaining_total_credits: 18,
      satisfied: false,
      categories: [
        { category_code: "major_foundation", category_name: "전공기초", required_credits: 18, earned_credits: 18, remaining_credits: 0, satisfied: true },
        { category_code: "major_required", category_name: "전공필수", required_credits: 18, earned_credits: 12, remaining_credits: 6, satisfied: false },
        { category_code: "major_elective", category_name: "전공선택", required_credits: 42, earned_credits: 33, remaining_credits: 9, satisfied: false },
        { category_code: "general_required", category_name: "교양필수", required_credits: 12, earned_credits: 12, remaining_credits: 0, satisfied: true },
        { category_code: "general_elective", category_name: "교양선택", required_credits: 18, earned_credits: 15, remaining_credits: 3, satisfied: false },
      ],
      warnings: ["목업 데이터로 표시된 졸업요건입니다."],
    },
  ],
};

export async function syncPortalData(loginId: string, password: string) {
  if (isMockStudentDataEnabled) {
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
    return {
      student_record: {
        이름: "테스트 학생",
        학번: loginId,
        학부: "의생명융합공학부",
        전공: "데이터사이언스전공",
      },
      courses: mockCourses,
      academic_programs: [{ program_type: "primary", major: "데이터사이언스전공" }],
      graduation_table_count: 1,
      // 목은 정상 동기화를 흉내낸다. 실패 배너를 확인하려면 이 값을 false로 바꿔라.
      my_pusan_sso_ok: true,
      activities_created: 2,
      activities_updated: 0,
      certifications_created: 1,
      certifications_updated: 0,
      language_scores_created: 1,
      language_scores_updated: 0,
    } satisfies PortalSyncResponse;
  }

  const { data } = await apiClient.post<PortalSyncResponse>("/me/portal-sync", {
    login_id: loginId,
    password,
  });
  return data;
}

export async function getGraduationProgress() {
  if (isMockStudentDataEnabled) {
    return mockGraduationProgress;
  }

  const { data } = await apiClient.get<GraduationProgress>("/me/graduation");
  return data;
}

function readMockCourses() {
  try {
    const saved = window.sessionStorage.getItem("planUCourseRecords");
    if (!saved) return mockCourses;
    return (JSON.parse(saved) as Array<Partial<CourseRecord>>).map((course, index) => ({
      ...course,
      id: typeof course.id === "number" ? course.id : index + 1,
      source: course.source ?? "mock",
    })) as CourseRecord[];
  } catch {
    return mockCourses;
  }
}

export async function getCourseRecords() {
  if (isMockStudentDataEnabled) return readMockCourses();
  const { data } = await apiClient.get<CourseRecord[]>("/me/course-records");
  return data;
}

export async function replaceCourseRecords(courses: CourseRecord[]) {
  if (isMockStudentDataEnabled) {
    const normalized = courses.map((course, index) => ({
      ...course,
      id: course.id > 0 ? course.id : Date.now() + index,
      source: course.source || "mock",
    }));
    window.sessionStorage.setItem("planUCourseRecords", JSON.stringify(normalized));
    return normalized;
  }
  const { data } = await apiClient.put<CourseRecord[]>("/me/course-records", {
    courses: courses.map((course) => ({
      id: course.id > 0 ? course.id : undefined,
      course_name: course.course_name,
      category: course.category,
      liberal_area: course.liberal_area,
      credits: course.credits,
      year: course.year,
      semester: course.semester,
      grade: course.grade,
    })),
  });
  return data;
}

/** 전적대 이수기록이 대체한 PNU 과목들을 지정한다. 부분 갱신이 아니라 **치환**이라,
 * 빈 배열을 보내면 대체가 해제된다.
 *
 * 편입 학점 인정은 학과가 학생 개인에게 통보하는 것이라 데이터에 근거가 없다.
 * 그래서 자동 매핑 없이, 학생이 직접 고른 course_ids만 서버에 보낸다. */
export async function setCourseSubstitutions(recordId: number, courseIds: number[]) {
  const { data } = await apiClient.put<CourseRecord>(
    `/me/course-records/${recordId}/substitutions`,
    { course_ids: courseIds },
  );
  return data;
}

export async function saveGraduationOverride(program: GraduationProgram) {
  if (isMockStudentDataEnabled) {
    window.sessionStorage.setItem("planUGraduationOverride", JSON.stringify(program));
    return { user_id: 0, programs: [program] } satisfies GraduationProgress;
  }
  const { data } = await apiClient.patch<GraduationProgress>("/me/graduation/override", {
    required_total_credits: program.required_total_credits,
    earned_total_credits: program.earned_total_credits,
    categories: program.categories,
  });
  return data;
}

/** 수동 보정을 지우고 서버가 이수 기록으로 다시 계산한 값으로 돌아간다. */
export async function clearGraduationOverride() {
  if (isMockStudentDataEnabled) {
    window.sessionStorage.removeItem("planUGraduationOverride");
    return;
  }
  await apiClient.delete("/me/graduation/override");
}
