import axios from "axios";

export const ACCESS_TOKEN_KEY = "planUAccessToken";
export const AUTH_EXPIRED_EVENT = "plan-u:auth-expired";

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000",
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.request.use((config) => {
  const token = window.localStorage.getItem(ACCESS_TOKEN_KEY) ?? window.sessionStorage.getItem(ACCESS_TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    const requestUrl = axios.isAxiosError(error) ? error.config?.url : undefined;
    const isPortalCredentialFailure = requestUrl?.endsWith("/me/portal-sync") ?? false;
    if (axios.isAxiosError(error) && error.response?.status === 401 && !isPortalCredentialFailure) {
      const hasToken = Boolean(
        window.localStorage.getItem(ACCESS_TOKEN_KEY) ?? window.sessionStorage.getItem(ACCESS_TOKEN_KEY),
      );
      if (hasToken) window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }
    return Promise.reject(error);
  },
);

export function getApiErrorMessage(error: unknown, fallback: string) {
  if (!axios.isAxiosError(error)) return fallback;

  if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT") {
    return "요청 시간이 초과되었습니다. 백엔드 서버 상태를 확인해 주세요.";
  }

  const detail = error.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
  if (!error.response) return "백엔드 서버에 연결할 수 없습니다. 서버 실행 상태를 확인해 주세요.";
  return fallback;
}
