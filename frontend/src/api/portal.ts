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

/** 미리보기 카드에 쓸 값만 추려낸다.
 *
 * `student_record`는 백엔드가 가공하지 않고 **크롤러가 읽은 그대로** 넘긴다. 키는
 * One-Stop 학적부 화면의 한글 라벨(`성명`·`학번`·`소속학과`…)이다. 예전에는 여기서
 * `record.name`/`record.student_id` 같은 영문 키를 읽어서 **항상 null**이었고, 그래서
 * 회원가입 STEP 2 미리보기 카드가 이름·학번·학적상태 없이 학점 줄만 뜨는 상태였다
 * (포털 비밀번호를 막 넘긴 직후라 "동기화가 안 됐나?"로 읽힌다).
 * 목 데이터가 `이름`을 쓰므로 그쪽도 함께 받아준다.
 */
export function summarizePortalSync(result: PortalSyncResult) {
  const record = result.student_record ?? {};
  const primary = result.academic_programs.find((program) => program.program_type === "primary");
  const totalCredits = result.courses.reduce((sum, course) => sum + (course.credits ?? 0), 0);

  // `소속학과` 원문은 "정보의생명공학대학 의생명융합공학부 데이터사이언스전공"처럼
  // 대학·학부·전공이 이미 한 문자열에 다 들어 있다. 여기에 major를 또 붙이면 전공이
  // 두 번 나오므로, 원문이 있으면 그것만 쓰고 없을 때만 major로 대체한다.
  const affiliationRaw = record["소속학과"] ?? record["학부"] ?? null;

  return {
    name: record["성명"] ?? record["이름"] ?? null,
    studentId: record["학번"] ?? null,
    affiliation: affiliationRaw ?? primary?.major ?? null,
    courseCount: result.courses.length,
    totalCredits,
    academicStatus: [record["학년"], record["학적상태"]].filter(Boolean).join(" ") || null,
    graduationTableCount: result.graduation_table_count,
  };
}
