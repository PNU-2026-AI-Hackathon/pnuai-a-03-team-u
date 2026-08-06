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

export type TimetableChatSuggestion = {
  offering_ids: number[];
  rationale: string | null;
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
