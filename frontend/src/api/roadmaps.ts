import { apiClient } from "./client";

export type CourseSearchResult = {
  id: number;
  course_name: string;
  course_code: string | null;
  department_id: number | null;
  major_id: number | null;
  major_name: string | null;
  category: string | null;
  credits: number | null;
  year: string | null;
  semester: string | null;
};

export type RoadmapItem = {
  id: number;
  course_id: number | null;
  planned_grade: number | null;
  // 달력 학기 — 성적표·개설 강좌와 같은 기준. "2026년 1학기".
  planned_year: string | null;
  planned_semester: string | null;
  // 커리큘럼 학기 — 로드맵의 학년 슬롯 기준. "3학년 2학기"의 2학기.
  // 휴학·편입이 있으면 달력 학기와 다르다. 계절수업/입학전성적은 null.
  curriculum_semester: string | null;
  course_name: string | null;
  department_name: string | null;
  major_name: string | null;
  category: string | null;
  credits: number | null;
  status: string;
  is_confirmed: boolean;
  reason: string | null;
  source: string;
};

export type Roadmap = {
  id: number;
  title: string | null;
  start_year: string | null;
  target_graduation_year: string | null;
  status: string;
  summary: string | null;
  items: RoadmapItem[];
};

/**
 * 학년 슬롯에 과목을 놓을 때는 planned_grade + curriculum_semester만 보내면 된다.
 * 달력 학기는 서버가 이수 기록에서 환산해 채운다(roadmaps.py의 _fill_missing_term_axis).
 */
export type RoadmapUpdatePayload = {
  title?: string | null;
  target_graduation_year?: string | null;
  summary?: string | null;
};

/** 로드맵 문서 자체의 메타(제목·목표 졸업연도 등)를 고친다. 항목과는 무관. */
export async function updateRoadmap(roadmapId: number, payload: RoadmapUpdatePayload) {
  const { data } = await apiClient.patch<Roadmap>(`/me/roadmaps/${roadmapId}`, payload);
  return data;
}

export type RoadmapItemPayload = {
  course_id: number;
  planned_grade?: number | null;
  planned_year?: string | null;
  planned_semester?: string | null;
  curriculum_semester?: string | null;
  reason?: string | null;
};

export type RoadmapItemUpdatePayload = {
  course_id?: number;
  planned_grade?: number | null;
  planned_year?: string | null;
  planned_semester?: string | null;
  curriculum_semester?: string | null;
  status?: string;
  is_confirmed?: boolean;
  reason?: string | null;
};

export type PendingRoadmapChange = {
  change_id: number;
  action: "create" | "update" | "delete";
  item_id: number | null;
  course_id: number | null;
  course_name: string | null;
  planned_year: string | null;
  planned_semester: string | null;
  planned_grade: number | null;
  before_snapshot: Record<string, unknown> | null;
  reason: string | null;
};

export type RoadmapChatResponse = {
  reply: string;
  session_id: number;
  pending_changes: PendingRoadmapChange[];
  suggested_actions: SuggestedAction[];
};

/** 같은 로드맵 안에서 독립된 대화 스레드 하나. */
export type RoadmapChatSession = {
  session_id: number;
  title: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
};

export type SuggestedAction = {
  label: string;
  prompt: string;
};

export type RoadmapChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

export type RoadmapConversation = {
  messages: RoadmapChatMessage[];
  pending_changes: PendingRoadmapChange[];
  suggested_actions: SuggestedAction[];
};

export type CurriculumCourse = {
  id: number;
  course_name: string;
  course_code: string | null;
  category: string | null;
  credits: number | null;
  semester: string | null;
  description: string | null;
  status: "done" | "planned" | "available";
};

export type CurriculumGroup = {
  grade: string;
  title: string;
  courses: CurriculumCourse[];
};

export type Curriculum = {
  department: string | null;
  major: string | null;
  curriculum_year: string | null;
  groups: CurriculumGroup[];
};

export async function getCurrentRoadmap() {
  const { data } = await apiClient.get<Roadmap>("/me/roadmaps/current");
  return data;
}

export type CourseBrowseFilters = {
  departmentId?: number | null;
  major?: string | null;
  category?: string | null;
  limit?: number;
};

export async function searchCourses(query: string, limit = 8) {
  const { data } = await apiClient.get<CourseSearchResult[]>("/courses/search", {
    params: { q: query, limit },
  });
  return data;
}

/** 학과를 골라 그 학과 과목을 쭉 훑어본다. query 없이 departmentId만으로도 결과가 온다. */
export async function browseCourses(query: string, filters: CourseBrowseFilters = {}) {
  const { data } = await apiClient.get<CourseSearchResult[]>("/courses/search", {
    params: {
      q: query,
      department_id: filters.departmentId ?? undefined,
      major: filters.major || undefined,
      category: filters.category || undefined,
      limit: filters.limit ?? 40,
    },
  });
  return data;
}

export async function createRoadmapItem(roadmapId: number, payload: RoadmapItemPayload) {
  const { data } = await apiClient.post<RoadmapItem>(`/me/roadmaps/${roadmapId}/items`, payload);
  return data;
}

export async function updateRoadmapItem(
  roadmapId: number,
  itemId: number,
  payload: RoadmapItemUpdatePayload,
) {
  const { data } = await apiClient.patch<RoadmapItem>(`/me/roadmaps/${roadmapId}/items/${itemId}`, payload);
  return data;
}

export async function deleteRoadmapItem(roadmapId: number, itemId: number) {
  await apiClient.delete(`/me/roadmaps/${roadmapId}/items/${itemId}`);
}

export async function chatWithRoadmapAgent(
  roadmapId: number,
  message: string,
  sessionId?: number,
) {
  const { data } = await apiClient.post<RoadmapChatResponse>(`/me/roadmaps/${roadmapId}/agent/chat`, {
    message,
    session_id: sessionId ?? null,
  });
  return data;
}

export async function listRoadmapSessions(roadmapId: number) {
  const { data } = await apiClient.get<RoadmapChatSession[]>(
    `/me/roadmaps/${roadmapId}/agent/sessions`,
  );
  return data;
}

export async function createRoadmapSession(roadmapId: number, title?: string) {
  const { data } = await apiClient.post<RoadmapChatSession>(
    `/me/roadmaps/${roadmapId}/agent/sessions`,
    { title: title ?? null },
  );
  return data;
}

export async function deleteRoadmapSession(roadmapId: number, sessionId: number) {
  await apiClient.delete(`/me/roadmaps/${roadmapId}/agent/sessions/${sessionId}`);
}

export async function confirmRoadmapChanges(
  roadmapId: number,
  approved: number[],
  rejected: number[],
) {
  const { data } = await apiClient.post<{ applied: number[]; rejected: number[] }>(
    `/me/roadmaps/${roadmapId}/agent/confirm`,
    { approved, rejected },
  );
  return data;
}

export async function resetRoadmapAgentSession(roadmapId: number) {
  const { data } = await apiClient.post<{ deleted_messages: number; deleted_pending: number }>(
    `/me/roadmaps/${roadmapId}/agent/reset`,
  );
  return data;
}

/**
 * 대화 기록을 읽는다. sessionId를 주면 그 스레드만, 생략하면 로드맵의 모든
 * 메시지가 섞여서 온다 — 세션을 다루는 화면은 반드시 sessionId를 넘길 것.
 */
export async function getRoadmapConversation(roadmapId: number, sessionId?: number) {
  const { data } = await apiClient.get<RoadmapConversation>(
    `/me/roadmaps/${roadmapId}/agent/messages`,
    { params: sessionId ? { session_id: sessionId } : undefined },
  );
  return data;
}

/** sessionId를 주면 그 스레드만 비운다(세션 자체와 pending change는 남는다). */
export async function clearRoadmapConversation(roadmapId: number, sessionId?: number) {
  await apiClient.delete(`/me/roadmaps/${roadmapId}/agent/messages`, {
    params: sessionId ? { session_id: sessionId } : undefined,
  });
}

export async function getMyCurriculum() {
  const { data } = await apiClient.get<Curriculum>("/me/curriculum");
  return data;
}
