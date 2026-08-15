import { apiClient } from "./client";

/**
 * AI융합트랙(SW융합트랙) — 졸업요건이 아니라 이수 시 졸업증명서에 표기되는
 * 인증 과정. 학생 주전공 학과가 대상 학과(14개)일 때만 목록이 내려온다.
 * 화면은 목록이 비어 있으면 트랙 섹션 자체를 그리지 않는다.
 */
export type AvailableTrack = {
  track_program_id: number;
  department_id: number;
  department_name: string;
  major_id: number;
  track_name: string;
  total_credits: number;
  /** {"min": N, "max": M} — 학과별 범위라 단일 값이 아니다. */
  dept_credits: { min?: number; max?: number };
  ai_common_credits: { min?: number; max?: number };
  source: string | null;
  is_enrolled: boolean;
};

export type EnrolledTrack = {
  enrollment_id: number;
  department_id: number;
  major_id: number;
  track_name: string;
  total_credits: number;
  earned_credits: number;
  remaining_credits: number;
  completed: boolean;
};

export type TrackPreview = {
  department_id: number;
  department_name: string;
  major_id: number;
  track_name: string;
  total_credits: number;
  dept_credits: { min?: number; max?: number };
  ai_common_credits: { min?: number; max?: number };
};

/**
 * 회원가입 홍보 카드용 비로그인 조회. 자동완성에서 고른 정식 학과명과
 * 완전 일치할 때만 결과가 온다 — 타이핑 중간값에는 조용히 빈 배열.
 */
export async function previewTracks(department: string) {
  const { data } = await apiClient.get<TrackPreview[]>("/tracks/preview", {
    params: { department },
  });
  return data;
}

export async function listAvailableTracks() {
  const { data } = await apiClient.get<AvailableTrack[]>("/me/tracks/available");
  return data;
}

export async function listEnrolledTracks() {
  const { data } = await apiClient.get<EnrolledTrack[]>("/me/tracks/enrolled");
  return data;
}

export async function enrollTrack(majorId: number) {
  const { data } = await apiClient.post<EnrolledTrack>("/me/tracks/enroll", {
    major_id: majorId,
  });
  return data;
}

/** 소프트 삭제(status='cancelled') — 다시 등록하면 이어서 계산된다. */
export async function cancelTrack(enrollmentId: number) {
  await apiClient.delete(`/me/tracks/${enrollmentId}`);
}
