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

/**
 * 신입학/편입학. 편입생은 1·2학년 커리큘럼을 밟지 않아 로드맵과 내 정보 화면을
 * "입학 전 인정 학점 + 3·4학년"으로 구성한다.
 */
export type AdmissionType = "freshman" | "transfer";

/** 편입생이 편성되는 학년. 부산대는 3학년 편입이 표준이라 하나로 고정한다. */
export const TRANSFER_ENTRY_GRADE = 3;

/** 이 학생의 커리큘럼이 시작되는 학년. */
export function entryGrade(admissionType: AdmissionType | null | undefined) {
  return admissionType === "transfer" ? TRANSFER_ENTRY_GRADE : 1;
}

/** 화면에 학년 슬롯으로 그려야 하는 학년 목록. */
export function visibleGrades(admissionType: AdmissionType | null | undefined) {
  const start = entryGrade(admissionType);
  return Array.from({ length: 5 - start }, (_, index) => start + index);
}

export type User = {
  id: number;
  email: string;
  name: string;
  student_id: string | null;
  department: string | null;
  major: string | null;
  academic_year: number | null;
  admission_type: AdmissionType;
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
  /** 생략하면 서버가 기존 값을 유지한다. */
  admission_type?: AdmissionType;
};

export type SignupPayload = {
  email: string;
  password: string;
  name: string;
  student_id: string;
  /** 서버에서도 선택 필드다. 회원가입 STEP 2에서 학사정보를 불러오면 채워진다. */
  academic_year?: number;
  admission_type?: AdmissionType;
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
  admissionType: AdmissionType = "freshman",
): User {
  return {
    id: 0,
    email,
    name,
    student_id: studentId.trim() || "2023662247",
    department: "의생명융합공학부",
    major: "데이터사이언스전공",
    academic_year: academicYear,
    admission_type: admissionType,
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
    return createMockUser(
      payload.student_id,
      payload.name,
      payload.email,
      payload.academic_year,
      payload.admission_type,
    );
  }

  const { data } = await apiClient.post<User>("/auth/signup", payload, {
    timeout: AUTH_REQUEST_TIMEOUT_MS,
  });
  return data;
}

/** 로그인 아이디는 부산대 웹메일. email 은 도메인까지 포함한 전체 주소를 받는다. */
/** 부산대 웹메일 도메인. 로그인·회원가입 아이디 입력에 고정 접미사로 붙는다. */
export const PNU_EMAIL_DOMAIN = "@pusan.ac.kr";

/** 아이디만 입력받아 전체 웹메일 주소로 만든다. 이미 도메인이 붙어 있으면 그대로 둔다. */
export function toPnuEmail(localPart: string) {
  const trimmed = localPart.trim().toLowerCase();
  return trimmed.includes("@") ? trimmed : `${trimmed}${PNU_EMAIL_DOMAIN}`;
}

export async function login(email: string, password: string, rememberLogin = false) {
  if (isMockAuthEnabled) {
    const mockUser = createMockUser(email.split("@")[0]);
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
      email,
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

/**
 * 재설정 링크 발송 요청. 웹메일과 이름이 모두 맞아야 발송되지만, 응답 문구는
 * 가입 여부·일치 여부와 무관하게 항상 같다(가입 여부 노출 방지).
 */
export async function requestPasswordReset(email: string, name: string) {
  const { data } = await apiClient.post<{ message: string }>(
    "/auth/password-reset/request",
    { email, name },
    { timeout: AUTH_REQUEST_TIMEOUT_MS },
  );
  return data;
}

/** 메일 링크의 토큰으로 새 비밀번호를 설정한다. */
export async function confirmPasswordReset(token: string, newPassword: string) {
  const { data } = await apiClient.post<{ message: string }>(
    "/auth/password-reset/confirm",
    { token, new_password: newPassword },
    { timeout: AUTH_REQUEST_TIMEOUT_MS },
  );
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
