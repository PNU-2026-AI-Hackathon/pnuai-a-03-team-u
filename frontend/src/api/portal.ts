import { apiClient } from "./client";

export type PortalAcademicProgram = {
  program_type: string;
  major: string | null;
};

export type PortalSyncResult = {
  student_record: Record<string, string>;
  courses: { credits: number | null }[];
  academic_programs: PortalAcademicProgram[];
  graduation_table_count: number;
};

/** 학생지원시스템에서 학적·이수 정보를 끌어온다. 회원가입 STEP 2에서 쓴다. */
export async function syncFromPortal(loginId: string, password: string) {
  const { data } = await apiClient.post<PortalSyncResult>("/me/portal-sync", {
    login_id: loginId,
    password,
  });
  return data;
}

/** 미리보기 카드에 쓸 값만 추려낸다. */
export function summarizePortalSync(result: PortalSyncResult) {
  const record = result.student_record ?? {};
  const primary = result.academic_programs.find((program) => program.program_type === "primary");
  const totalCredits = result.courses.reduce((sum, course) => sum + (course.credits ?? 0), 0);

  return {
    name: record.name ?? null,
    studentId: record.student_id ?? null,
    affiliation: [record.department, primary?.major].filter(Boolean).join(" · ") || null,
    courseCount: result.courses.length,
    totalCredits,
    academicStatus: [record.academic_year, record.status].filter(Boolean).join(" ") || null,
    graduationTableCount: result.graduation_table_count,
  };
}
