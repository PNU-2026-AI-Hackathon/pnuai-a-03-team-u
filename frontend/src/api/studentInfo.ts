import { apiClient } from "./client";

export const isMockStudentDataEnabled =
  import.meta.env.DEV && import.meta.env.VITE_USE_MOCK_STUDENT_DATA === "true";

export type CourseRecord = {
  course_name: string;
  category: string | null;
  credits: number | null;
  year: string | null;
  semester: string | null;
  grade: string | null;
  match_status: string;
};

export type PortalSyncResponse = {
  student_record: Record<string, string>;
  courses: CourseRecord[];
  academic_programs: Array<{
    program_type: string;
    major: string | null;
  }>;
  graduation_table_count: number;
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
  { course_name: "데이터베이스", category: "전공필수", credits: 3, year: "2026", semester: "1", grade: "A+", match_status: "matched" },
  { course_name: "자료구조", category: "전공필수", credits: 3, year: "2026", semester: "1", grade: "A0", match_status: "matched" },
  { course_name: "선형대수", category: "전공선택", credits: 3, year: "2026", semester: "1", grade: "B+", match_status: "matched" },
  { course_name: "웹프로그래밍", category: "전공선택", credits: 3, year: "2026", semester: "1", grade: "A+", match_status: "matched" },
  { course_name: "교양 선택", category: "교양선택", credits: 3, year: "2026", semester: "1", grade: "A0", match_status: "matched" },
  { course_name: "Python Programming", category: "전공기초", credits: 3, year: "2025", semester: "2", grade: "A+", match_status: "matched" },
  { course_name: "확률및통계 II", category: "전공기초", credits: 3, year: "2025", semester: "2", grade: "A0", match_status: "matched" },
  { course_name: "인공지능과 디지털 사고", category: "교양필수", credits: 3, year: "2025", semester: "2", grade: "A+", match_status: "matched" },
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
