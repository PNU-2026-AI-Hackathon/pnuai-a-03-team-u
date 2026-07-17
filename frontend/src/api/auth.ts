import { ACCESS_TOKEN_KEY, apiClient } from "./client";

const MOCK_ACCESS_TOKEN_KEY = "planUMockAccessToken";
const MOCK_USER_KEY = "planUMockUser";

export const isMockAuthEnabled =
  import.meta.env.DEV &&
  (import.meta.env.VITE_USE_MOCK_AUTH === "true" || import.meta.env.VITE_USE_MOCK_STUDENT_DATA === "true");

export type AcademicProgram = {
  major: string;
  program_type: "primary" | "dual" | "minor" | "interdisciplinary";
};

export type User = {
  id: number;
  email: string;
  name: string;
  student_id: string | null;
  department: string | null;
  major: string | null;
  career_goal: string | null;
  academic_programs: AcademicProgram[];
};

export type SignupPayload = {
  email: string;
  password: string;
  name: string;
  student_id?: string;
  school?: string;
  college?: string;
  department?: string;
  career_goal?: string;
  academic_programs?: AcademicProgram[];
};

function createMockUser(identifier: string, name = "테스트 학생"): User {
  return {
    id: 0,
    email: identifier.includes("@") ? identifier : "mock@plan-u.local",
    name,
    student_id: "2023662247",
    department: "의생명융합공학부",
    major: "데이터사이언스전공",
    career_goal: "데이터 사이언티스트",
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
    return createMockUser(payload.email, payload.name);
  }

  const { data } = await apiClient.post<User>("/auth/signup", payload);
  return data;
}

export async function login(email: string, password: string, rememberLogin = false) {
  if (isMockAuthEnabled) {
    const mockUser = createMockUser(email.trim());
    const storage = rememberLogin ? window.localStorage : window.sessionStorage;
    const temporaryStorage = rememberLogin ? window.sessionStorage : window.localStorage;
    temporaryStorage.removeItem(MOCK_ACCESS_TOKEN_KEY);
    temporaryStorage.removeItem(MOCK_USER_KEY);
    storage.setItem(MOCK_ACCESS_TOKEN_KEY, "mock-access-token");
    storage.setItem(MOCK_USER_KEY, JSON.stringify(mockUser));
    return { access_token: "mock-access-token", token_type: "bearer" };
  }

  const { data } = await apiClient.post<{ access_token: string; token_type: string }>("/auth/login", {
    email,
    password,
  });
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

  const { data } = await apiClient.get<User>("/auth/me");
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
