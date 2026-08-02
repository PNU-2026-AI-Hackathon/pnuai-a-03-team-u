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
