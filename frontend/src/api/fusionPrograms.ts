import { apiClient } from "./client";

export type ParticipatingDepartment = { id: number; name: string };

/**
 * 학생 소속 학과 과목이 인정 과목 풀에 포함되는 융합전공/연계전공/AI(SW)융합트랙.
 * 학생 학과가 참여 학과가 아니면 서버가 그 프로그램을 아예 빼고 준다.
 * 목록이 비면 화면은 "AI융합 가능" 버튼 자체를 그리지 않는다.
 */
export type FusionProgramOption = {
  program_id: number;
  department_id: number;
  department_name: string;
  major_id: number | null;
  program_name: string;
  kind: "track" | "linked" | "convergence";
  kind_label: string;
  program_type: string | null;
  program_type_label: string | null;
  total_credits: number | null;
  curriculum_year: string | null;
  participating_departments: ParticipatingDepartment[];
};

export async function listAvailableFusionPrograms() {
  const { data } = await apiClient.get<FusionProgramOption[]>(
    "/me/fusion-programs/available",
  );
  return data;
}
