import { apiClient } from "./client";

export type TimetableTime = {
  day_of_week: string | null;
  start_time: string | null;
  end_time: string | null;
  classroom: string | null;
};

export type TimetableSection = {
  item_id: number;
  course_id: number | null;
  course_code: string | null;
  course_name: string | null;
  category: string | null;
  credits: number | null;
  offering_id: number | null;
  section: string | null;
  professor: string | null;
  times: TimetableTime[];
};

export type TimetableSchedule = {
  total_credits: number;
  distinct_days: number;
  total_gap_minutes: number;
  sections: TimetableSection[];
  over_credit_cap?: boolean;
  excluded_item_ids?: number[];
};

export type UnavailableCourse = {
  item_id: number;
  course_name?: string | null;
  reason?: string | null;
};

export type ProblematicCourse = {
  item_id: number;
  course_name?: string | null;
  reason?: string | null;
};

export type TimetableRecommendation = {
  target_term: unknown;
  term_credit_cap: number | null;
  feasible_schedules: TimetableSchedule[];
  partial_schedules: TimetableSchedule[];
  over_cap_schedules?: TimetableSchedule[];
  unavailable_courses: UnavailableCourse[];
  problematic_courses: ProblematicCourse[];
  replacement_suggestions: unknown[];
  note?: string;
};

export async function recommendTimetable(roadmapId: number, year: string, semester: string) {
  const { data } = await apiClient.get<TimetableRecommendation>(
    `/me/roadmaps/${roadmapId}/timetable/recommend`,
    { params: { year, semester } },
  );
  return data;
}

export type TimetableChatTurn = { role: "user" | "assistant"; content: string };

export type SuggestedOffering = {
  offering_id: number;
  course_id: number | null;
  course_name: string | null;
  course_code: string | null;
  category: string | null;
  credits: number | null;
  section: string | null;
  professor: string | null;
  times: TimetableTime[];
};

export type TimetableChatSuggestion = {
  offering_ids: number[];
  rationale: string | null;
  /** 승인 카드에 그릴 분반 상세. offering_ids만으로는 무엇을 담는지 알 수 없다. */
  offerings: SuggestedOffering[];
  total_credits: number;
};

export type TimetableChatResponse = {
  reply: string;
  schedules: TimetableChatSuggestion[];
  iterations: number;
  tool_calls: { name: string; args: unknown }[];
};

/**
 * 시간표 전용 AI 상담. 로드맵 상담(chatWithRoadmapAgent)과 다른 엔드포인트다 —
 * 예전에는 시간표 화면도 로드맵 챗을 불러서 두 화면의 대화가 한 세션에 섞이고,
 * 시간표 화면에서 로드맵 변경안(pending change)까지 생기는 문제가 있었다.
 *
 * 서버가 대화를 저장하지 않는 스테이트리스 엔드포인트라, 히스토리는 호출부가
 * 들고 있다가 매번 넘겨준다.
 */
export async function chatWithTimetableAgent(
  year: string,
  semester: string,
  message: string,
  history: TimetableChatTurn[] = [],
) {
  const { data } = await apiClient.post<TimetableChatResponse>("/agent/timetable/recommend", {
    year,
    semester,
    message,
    history,
  });
  return data;
}

export type TimetableApplySkipped = {
  offering_id: number;
  course_id: number | null;
  course_name: string | null;
  reason: string;
};

export type TimetableApplyRemovedFromFuture = {
  item_id: number;
  course_id: number | null;
  course_name: string | null;
  planned_year: string | null;
  planned_semester: string | null;
};

export type TimetableApplyResult = {
  applied: { id: number; course_name: string | null }[];
  skipped: TimetableApplySkipped[];
  removed_from_future: TimetableApplyRemovedFromFuture[];
};

/**
 * 사용자가 승인한 분반을 로드맵에 반영한다.
 *
 * 시간표 에이전트는 DB를 쓰지 않는다 — 추천만 하고, 실제 반영은 사용자가 고른
 * offering_ids를 들고 여기로 한 번 더 와야 이뤄진다(human-in-the-loop).
 */
export async function applyTimetableToRoadmap(
  roadmapId: number,
  year: string,
  semester: string,
  offeringIds: number[],
) {
  const { data } = await apiClient.post<TimetableApplyResult>(
    `/me/roadmaps/${roadmapId}/timetable/apply`,
    { year, semester, offering_ids: offeringIds },
  );
  return data;
}
