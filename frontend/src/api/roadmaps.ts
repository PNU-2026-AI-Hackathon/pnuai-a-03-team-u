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
  pending_changes: PendingRoadmapChange[];
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

export async function chatWithRoadmapAgent(roadmapId: number, message: string) {
  const { data } = await apiClient.post<RoadmapChatResponse>(`/me/roadmaps/${roadmapId}/agent/chat`, { message });
  return data;
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
