import { apiClient } from "./client";

export type CourseSearchResult = {
  id: number;
  course_name: string;
  course_code: string | null;
  department_id: number | null;
  major_id: number | null;
  category: string | null;
  credits: number | null;
};

export type RoadmapItem = {
  id: number;
  course_id: number | null;
  planned_grade: number | null;
  planned_year: string | null;
  planned_semester: string | null;
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

export type RoadmapItemPayload = {
  course_id: number;
  planned_grade?: number | null;
  planned_year?: string | null;
  planned_semester?: string | null;
  reason?: string | null;
};

export type RoadmapItemUpdatePayload = {
  course_id?: number;
  planned_grade?: number | null;
  planned_year?: string | null;
  planned_semester?: string | null;
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

export async function searchCourses(query: string, limit = 8) {
  const { data } = await apiClient.get<CourseSearchResult[]>("/courses/search", {
    params: { q: query, limit },
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
