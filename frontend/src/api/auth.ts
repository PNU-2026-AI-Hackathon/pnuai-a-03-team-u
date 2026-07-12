import { ACCESS_TOKEN_KEY, apiClient } from "./client";

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

export async function signup(payload: SignupPayload) {
  const { data } = await apiClient.post<User>("/auth/signup", payload);
  return data;
}

export async function login(email: string, password: string) {
  const { data } = await apiClient.post<{ access_token: string; token_type: string }>("/auth/login", {
    email,
    password,
  });
  window.localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
  return data;
}

export async function getMe() {
  const { data } = await apiClient.get<User>("/auth/me");
  return data;
}

export function logout() {
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
}
