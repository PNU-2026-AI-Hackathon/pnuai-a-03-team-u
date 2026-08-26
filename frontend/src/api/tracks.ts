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

/**
 * AI융합 공통교과목 한 줄. 특정 학과 소속이 아니라 이름 목록으로만 관리되는
 * 과목이라(department_id/major_id 없음) 로드맵 "학과 훑어보기"로는 못 찾는다 —
 * 트랙 빠른 선택에서 department/major 필터와 별도로 이 목록을 따로 받아 합친다.
 * course_id가 null이면(in_catalog=false) 카탈로그 적재가 안 된 것이라 담을 수 없다.
 */
export type AiCommonCourse = {
  course_id: number | null;
  course_name: string;
  category: string | null;
  credits: number | null;
  /** 대부분 "전학년"/"전학기"(학년·학기 제한 없음) — 실제 값이 이렇게 온다. */
  year: string | null;
  semester: string | null;
  module: number;
  summary: string;
  in_catalog: boolean;
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

/** 학생마다 다르지 않은 고정 목록이라 스코프 파라미터가 없다. */
export async function listTrackAiCommonCourses() {
  const { data } = await apiClient.get<AiCommonCourse[]>("/me/tracks/ai-common-courses");
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
