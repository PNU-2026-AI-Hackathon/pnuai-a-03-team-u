import { ACCESS_TOKEN_KEY, apiClient } from "./client";

const MOCK_ACCESS_TOKEN_KEY = "planUMockAccessToken";
const MOCK_USER_KEY = "planUMockUser";
const AUTH_REQUEST_TIMEOUT_MS = 15_000;

export const isMockAuthEnabled =
  import.meta.env.DEV &&
  (import.meta.env.VITE_USE_MOCK_AUTH === "true" || import.meta.env.VITE_USE_MOCK_STUDENT_DATA === "true");

export type AcademicProgram = {
  major: string;
  program_type: "primary" | "dual" | "minor" | "interdisciplinary";
};

export type AcademicProgramInput = {
  major?: string;
  department?: string;
  program_type: "primary" | "dual" | "minor" | "interdisciplinary";
};

export type User = {
  id: number;
  email: string;
  name: string;
  student_id: string | null;
  department: string | null;
  major: string | null;
  academic_year: number | null;
  career_goal: string | null;
  advisor_name: string | null;
  advisor_consulted: boolean;
  academic_programs: AcademicProgram[];
};

export type ProfileUpdatePayload = {
  name: string;
  department: string;
  major?: string | null;
  academic_year: number;
};

export type SignupPayload = {
  email: string;
  password: string;
  name: string;
  student_id: string;
  academic_year: number;
  school?: string;
  college?: string;
  department?: string;
  career_goal?: string;
  academic_programs?: AcademicProgramInput[];
};

function createMockUser(
  studentId: string,
  name = "테스트 학생",
  email = "mock@plan-u.local",
  academicYear = 3,
): User {
  return {
    id: 0,
    email,
    name,
    student_id: studentId.trim() || "2023662247",
    department: "의생명융합공학부",
    major: "데이터사이언스전공",
    academic_year: academicYear,
    career_goal: "데이터 사이언티스트",
    advisor_name: "김도현 교수",
    advisor_consulted: false,
    academic_programs: [{ major: "데이터사이언스전공", program_type: "primary" }],
  };
}

export function hasAuthSession() {
  if (isMockAuthEnabled) {
    return Boolean(
      window.localStorage.getItem(MOCK_ACCESS_TOKEN_KEY) ??
      window.sessionStorage.getItem(MOCK_ACCESS_TOKEN_KEY),
    );
  }
  return Boolean(
    window.localStorage.getItem(ACCESS_TOKEN_KEY) ??
    window.sessionStorage.getItem(ACCESS_TOKEN_KEY),
  );
}

export async function signup(payload: SignupPayload) {
  if (isMockAuthEnabled) {
    return createMockUser(payload.student_id, payload.name, payload.email, payload.academic_year);
  }

  const { data } = await apiClient.post<User>("/auth/signup", payload, {
    timeout: AUTH_REQUEST_TIMEOUT_MS,
  });
  return data;
}

export async function login(studentId: string, password: string, rememberLogin = false) {
  if (isMockAuthEnabled) {
    const mockUser = createMockUser(studentId);
    const storage = rememberLogin ? window.localStorage : window.sessionStorage;
    const temporaryStorage = rememberLogin ? window.sessionStorage : window.localStorage;
    temporaryStorage.removeItem(MOCK_ACCESS_TOKEN_KEY);
    temporaryStorage.removeItem(MOCK_USER_KEY);
    storage.setItem(MOCK_ACCESS_TOKEN_KEY, "mock-access-token");
    storage.setItem(MOCK_USER_KEY, JSON.stringify(mockUser));
    return { access_token: "mock-access-token", token_type: "bearer" };
  }

  const { data } = await apiClient.post<{ access_token: string; token_type: string }>(
    "/auth/login",
    {
      student_id: studentId,
      password,
    },
    { timeout: AUTH_REQUEST_TIMEOUT_MS },
  );
  const storage = rememberLogin ? window.localStorage : window.sessionStorage;
  const temporaryStorage = rememberLogin ? window.sessionStorage : window.localStorage;
  temporaryStorage.removeItem(ACCESS_TOKEN_KEY);
  storage.setItem(ACCESS_TOKEN_KEY, data.access_token);
  return data;
}

export async function getMe() {
  if (isMockAuthEnabled) {
    const savedUser =
      window.localStorage.getItem(MOCK_USER_KEY) ??
      window.sessionStorage.getItem(MOCK_USER_KEY);
    if (!savedUser) throw new Error("목업 로그인 정보가 없습니다.");
    return JSON.parse(savedUser) as User;
  }

  const { data } = await apiClient.get<User>("/auth/me", {
    timeout: AUTH_REQUEST_TIMEOUT_MS,
  });
  return data;
}

function updateStoredMockUser(updates: Partial<User>) {
  const localUser = window.localStorage.getItem(MOCK_USER_KEY);
  const sessionUser = window.sessionStorage.getItem(MOCK_USER_KEY);
  const storage = localUser ? window.localStorage : window.sessionStorage;
  const saved = localUser ?? sessionUser;
  if (!saved) throw new Error("목업 로그인 정보가 없습니다.");
  const user = { ...(JSON.parse(saved) as User), ...updates };
  storage.setItem(MOCK_USER_KEY, JSON.stringify(user));
  return user;
}

export async function updateMyProfile(payload: ProfileUpdatePayload) {
  if (isMockAuthEnabled) {
    return updateStoredMockUser({
      name: payload.name,
      department: payload.department,
      major: payload.major?.trim() || null,
      academic_year: payload.academic_year,
    });
  }
  const { data } = await apiClient.patch<User>("/me/profile", payload);
  return data;
}

export async function updateAdvisorConsulted(advisorConsulted: boolean) {
  if (isMockAuthEnabled) {
    const user = updateStoredMockUser({ advisor_consulted: advisorConsulted });
    return { advisor_consulted: user.advisor_consulted };
  }
  const { data } = await apiClient.patch<{ advisor_consulted: boolean }>("/me/advisor-consulted", {
    advisor_consulted: advisorConsulted,
  });
  return data;
}

export function logout() {
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  window.sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(MOCK_ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(MOCK_USER_KEY);
  window.sessionStorage.removeItem(MOCK_ACCESS_TOKEN_KEY);
  window.sessionStorage.removeItem(MOCK_USER_KEY);
}
