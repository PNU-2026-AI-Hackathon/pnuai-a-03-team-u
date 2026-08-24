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

export type TimetableChatSession = {
  session_id: number;
  year: string;
  semester: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
};

export type TimetableChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

/** 시간표 챗 세션. (user, year, semester) 단위로 여러 스레드가 병존한다. */
export async function listTimetableChatSessions(year: string, semester: string) {
  const { data } = await apiClient.get<TimetableChatSession[]>("/agent/timetable/sessions", {
    params: { year, semester },
  });
  return data;
}

export async function createTimetableChatSession(year: string, semester: string, title?: string) {
  const { data } = await apiClient.post<TimetableChatSession>("/agent/timetable/sessions", {
    year,
    semester,
    title: title ?? null,
  });
  return data;
}

export async function getTimetableChatMessages(sessionId: number) {
  const { data } = await apiClient.get<TimetableChatMessage[]>(
    `/agent/timetable/sessions/${sessionId}/messages`,
  );
  return data;
}

export async function deleteTimetableChatSession(sessionId: number) {
  await apiClient.delete(`/agent/timetable/sessions/${sessionId}`);
}

/** 세션(제목·학기 맥락)은 남기고 메시지만 비운다 — '이 대화 비우기'. */
export async function clearTimetableChatMessages(sessionId: number) {
  const { data } = await apiClient.delete<{ deleted_messages: number }>(
    `/agent/timetable/sessions/${sessionId}/messages`,
  );
  return data;
}

export type SuggestedOffering = {
  offering_id: number;
  course_id: number | null;
  course_name: string | null;
  course_code: string | null;
  category: string | null;
  credits: number | null;
  section: string | null;
  professor: string | null;
  /**
   * 학부만 고르고 전공을 안 고르면 그 학부의 모든 전공 과목이 함께 나온다.
   * 어느 전공 과목인지 줄마다 보여주려고 받는다(전공 미지정이면 null).
   * 시간표 챗 추천(TimetableChatSuggestion.offerings)에는 없어서 optional.
   */
  major_name?: string | null;
  /** 효원균형·창의교양 세부영역(사상과역사 등). 그 갈래가 아니면 null. */
  general_education_area?: string | null;
  times: TimetableTime[];
};

export type TimetableChatSuggestion = {
  offering_ids: number[];
  rationale: string | null;
  /** 승인 카드에 그릴 분반 상세. offering_ids만으로는 무엇을 담는지 알 수 없다. */
  offerings: SuggestedOffering[];
  total_credits: number;
  /**
   * offering_ids = 이미 담아둔 것 + 이번에 새로 추가되는 것. 추천은 사용자가 담아둔
   * 시간표 위에 얹히므로, 승인 카드에서 "새로 들어가는 건 이것"을 구분하려면 이 둘이
   * 필요하다. 담기 API는 멱등이라 전체를 그대로 적용해도 안전하다.
   */
  locked_offering_ids: number[];
  added_offering_ids: number[];
};

export type TimetableChatResponse = {
  reply: string;
  schedules: TimetableChatSuggestion[];
  iterations: number;
  tool_calls: { name: string; args: unknown }[];
  session_id: number;
};

/**
 * 시간표 전용 AI 상담. 대화는 세션 단위로 서버에 저장된다(#120에서 스테이트리스
 * → 저장형 전환). session_id 없이 보내면 이 학기의 최근 세션을 이어 쓰거나
 * 새로 만들고, 응답의 session_id로 어느 세션에 붙었는지 알려준다.
 */
export async function chatWithTimetableAgent(
  year: string,
  semester: string,
  message: string,
  sessionId?: number,
  planId?: number,
) {
  const { data } = await apiClient.post<TimetableChatResponse>("/agent/timetable/recommend", {
    year,
    semester,
    message,
    session_id: sessionId ?? null,
    // 지금 화면에 열어둔 시간표. 서버는 여기 담긴 강좌를 고정해 놓고 그 위에 얹어
    // 추천한다. 안 보내면 그 학기의 "가장 최근 수정한" 시간표로 폴백하는데, 시간표를
    // 여러 개 만들어 비교하는 중이면 보고 있지 않은 쪽이 잡힐 수 있다.
    plan_id: planId ?? null,
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

export type OfferingSearchParams = {
  year: string;
  semester: string;
  departmentId?: number | null;
  major?: string | null;
  /** 화면의 한 갈래가 DB 이수구분 여러 개일 수 있어 배열로 받는다. */
  categories?: string[];
  /** 효원균형·창의교양 세부영역(사상과역사 등)으로 한 번 더 좁힐 때만 채운다. */
  generalEducationArea?: string | null;
  q?: string;
  limit?: number;
};

/**
 * 대상 학기에 실제로 개설된 강좌를 학부/전공으로 좁혀 찾는다.
 *
 * 시간표 "과목 추가"가 쓰던 목록은 로드맵에 이미 담긴 과목에서 파생된 것이라,
 * 아직 계획에 없는 과목은 아예 보이지 않았다. 다른 학부 과목을 담으려면 이쪽을 쓴다.
 */
export async function searchOfferings({
  year,
  semester,
  departmentId,
  major,
  categories,
  generalEducationArea,
  q = "",
  limit = 50,
}: OfferingSearchParams) {
  const { data } = await apiClient.get<SuggestedOffering[]>("/courses/offerings", {
    params: {
      year,
      semester,
      department_id: departmentId ?? undefined,
      major: major || undefined,
      category: categories?.length ? categories : undefined,
      general_education_area: generalEducationArea || undefined,
      q,
      limit,
    },
    // 배열을 category=a&category=b로 보낸다. axios 기본값은 category[]=a라
    // FastAPI의 list[str] 쿼리 파라미터가 못 받고 조용히 무시된다.
    paramsSerializer: { indexes: null },
  });
  return data;
}

// --- 시간표(수강계획) CRUD ---------------------------------------------------

export type TimetableSummary = {
  id: number;
  title: string;
  year: string | null;
  semester: string | null;
  item_count: number;
  total_credits: number;
};

export type TimetableDetail = TimetableSummary & {
  offerings: SuggestedOffering[];
};

/** 이름 붙인 시간표 문서. 여기 담긴 건 계획일 뿐, 로드맵 반영은 apply가 따로 한다. */
export async function listTimetables(year: string, semester: string) {
  const { data } = await apiClient.get<TimetableSummary[]>("/me/timetables", {
    params: { year, semester },
  });
  return data;
}

export async function createTimetable(year: string, semester: string, title?: string) {
  const { data } = await apiClient.post<TimetableDetail>("/me/timetables", {
    year,
    semester,
    title: title ?? null,
  });
  return data;
}

export async function getTimetable(id: number) {
  const { data } = await apiClient.get<TimetableDetail>(`/me/timetables/${id}`);
  return data;
}

export async function renameTimetable(id: number, title: string) {
  const { data } = await apiClient.patch<TimetableDetail>(`/me/timetables/${id}`, { title });
  return data;
}

export async function deleteTimetable(id: number) {
  await apiClient.delete(`/me/timetables/${id}`);
}

/** 이미 담긴 분반은 서버가 조용히 건너뛴다(멱등). */
export async function addTimetableItems(id: number, offeringIds: number[]) {
  const { data } = await apiClient.post<TimetableDetail>(`/me/timetables/${id}/items`, {
    offering_ids: offeringIds,
  });
  return data;
}

export async function removeTimetableItem(id: number, offeringId: number) {
  const { data } = await apiClient.delete<TimetableDetail>(
    `/me/timetables/${id}/items/${offeringId}`,
  );
  return data;
}
