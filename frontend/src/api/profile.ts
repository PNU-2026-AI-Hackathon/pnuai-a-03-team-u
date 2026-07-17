import { apiClient } from "./client";
import { isMockStudentDataEnabled } from "./studentInfo";

export type ActivityRecord = {
  id: number;
  title: string;
  organization: string | null;
  category: string | null;
  role: string | null;
  award: string | null;
  description: string | null;
  url: string | null;
  start_date: string | null;
  end_date: string | null;
};

export type ActivityPayload = Omit<ActivityRecord, "id">;

export type CertificationRecord = {
  id: number;
  name: string;
  expires_at: string | null;
};

export type CertificationPayload = Omit<CertificationRecord, "id">;

export type LanguageScoreRecord = {
  id: number;
  test_name: string;
  score: string;
  expires_at: string | null;
};

export type LanguageScorePayload = Omit<LanguageScoreRecord, "id">;

type MockProfileData = {
  activities: ActivityRecord[];
  certifications: CertificationRecord[];
  languageScores: LanguageScoreRecord[];
};

const MOCK_PROFILE_KEY = "planUMockProfileRecords";

const initialMockProfile: MockProfileData = {
  activities: [
    {
      id: 1,
      title: "Google DSC Core Member",
      organization: "부산대학교",
      category: "동아리",
      role: "Core Member",
      award: null,
      description: "데이터 분석 스터디 운영, 팀 프로젝트 코드 리뷰, 세미나 발표를 진행했습니다.",
      url: null,
      start_date: "2025-03-01",
      end_date: "2025-12-31",
    },
    {
      id: 2,
      title: "SW+X 문제해결 경진대회",
      organization: "부산대학교",
      category: "공모전",
      role: "팀원",
      award: null,
      description: "바이오 데이터를 활용해 문제를 정의하고 분석 모델을 설계했습니다.",
      url: null,
      start_date: "2025-09-01",
      end_date: "2025-11-15",
    },
    {
      id: 3,
      title: "SQL 분석 미니 프로젝트",
      organization: "부산대학교",
      category: "프로젝트",
      role: "개인 프로젝트",
      award: null,
      description: "데이터베이스 설계, SQL 쿼리 분석, 시각화 결과물을 정리했습니다.",
      url: null,
      start_date: "2026-03-10",
      end_date: null,
    },
  ],
  certifications: [
    { id: 1, name: "GTQ 1급", expires_at: null },
    { id: 2, name: "빅데이터분석기사 필기", expires_at: null },
  ],
  languageScores: [
    { id: 1, test_name: "TOEIC Speaking", score: "IM3", expires_at: "2027-05-20" },
    { id: 2, test_name: "OPIc", score: "IM2", expires_at: "2027-02-14" },
  ],
};

function cloneInitialMockProfile(): MockProfileData {
  return JSON.parse(JSON.stringify(initialMockProfile)) as MockProfileData;
}

function readMockProfile(): MockProfileData {
  try {
    const saved = window.sessionStorage.getItem(MOCK_PROFILE_KEY);
    return saved ? (JSON.parse(saved) as MockProfileData) : cloneInitialMockProfile();
  } catch {
    return cloneInitialMockProfile();
  }
}

function writeMockProfile(data: MockProfileData) {
  window.sessionStorage.setItem(MOCK_PROFILE_KEY, JSON.stringify(data));
}

function nextId(records: Array<{ id: number }>) {
  return records.reduce((highest, record) => Math.max(highest, record.id), 0) + 1;
}

export async function getActivities() {
  if (isMockStudentDataEnabled) return readMockProfile().activities;
  const { data } = await apiClient.get<ActivityRecord[]>("/me/activities");
  return data;
}

export async function createActivity(payload: ActivityPayload) {
  if (isMockStudentDataEnabled) {
    const profile = readMockProfile();
    const created = { id: nextId(profile.activities), ...payload };
    profile.activities = [created, ...profile.activities];
    writeMockProfile(profile);
    return created;
  }
  const { data } = await apiClient.post<ActivityRecord>("/me/activities", payload);
  return data;
}

export async function updateActivity(id: number, payload: ActivityPayload) {
  if (isMockStudentDataEnabled) {
    const profile = readMockProfile();
    const updated = { id, ...payload };
    profile.activities = profile.activities.map((record) => (record.id === id ? updated : record));
    writeMockProfile(profile);
    return updated;
  }
  const { data } = await apiClient.patch<ActivityRecord>(`/me/activities/${id}`, payload);
  return data;
}

export async function deleteActivity(id: number) {
  if (isMockStudentDataEnabled) {
    const profile = readMockProfile();
    profile.activities = profile.activities.filter((record) => record.id !== id);
    writeMockProfile(profile);
    return;
  }
  await apiClient.delete(`/me/activities/${id}`);
}

export async function getCertifications() {
  if (isMockStudentDataEnabled) return readMockProfile().certifications;
  const { data } = await apiClient.get<CertificationRecord[]>("/me/certifications");
  return data;
}

export async function createCertification(payload: CertificationPayload) {
  if (isMockStudentDataEnabled) {
    const profile = readMockProfile();
    const created = { id: nextId(profile.certifications), ...payload };
    profile.certifications = [created, ...profile.certifications];
    writeMockProfile(profile);
    return created;
  }
  const { data } = await apiClient.post<CertificationRecord>("/me/certifications", payload);
  return data;
}

export async function updateCertification(id: number, payload: CertificationPayload) {
  if (isMockStudentDataEnabled) {
    const profile = readMockProfile();
    const updated = { id, ...payload };
    profile.certifications = profile.certifications.map((record) => (record.id === id ? updated : record));
    writeMockProfile(profile);
    return updated;
  }
  const { data } = await apiClient.patch<CertificationRecord>(`/me/certifications/${id}`, payload);
  return data;
}

export async function deleteCertification(id: number) {
  if (isMockStudentDataEnabled) {
    const profile = readMockProfile();
    profile.certifications = profile.certifications.filter((record) => record.id !== id);
    writeMockProfile(profile);
    return;
  }
  await apiClient.delete(`/me/certifications/${id}`);
}

export async function getLanguageScores() {
  if (isMockStudentDataEnabled) return readMockProfile().languageScores;
  const { data } = await apiClient.get<LanguageScoreRecord[]>("/me/language-scores");
  return data;
}

export async function createLanguageScore(payload: LanguageScorePayload) {
  if (isMockStudentDataEnabled) {
    const profile = readMockProfile();
    const created = { id: nextId(profile.languageScores), ...payload };
    profile.languageScores = [created, ...profile.languageScores];
    writeMockProfile(profile);
    return created;
  }
  const { data } = await apiClient.post<LanguageScoreRecord>("/me/language-scores", payload);
  return data;
}

export async function updateLanguageScore(id: number, payload: LanguageScorePayload) {
  if (isMockStudentDataEnabled) {
    const profile = readMockProfile();
    const updated = { id, ...payload };
    profile.languageScores = profile.languageScores.map((record) => (record.id === id ? updated : record));
    writeMockProfile(profile);
    return updated;
  }
  const { data } = await apiClient.patch<LanguageScoreRecord>(`/me/language-scores/${id}`, payload);
  return data;
}

export async function deleteLanguageScore(id: number) {
  if (isMockStudentDataEnabled) {
    const profile = readMockProfile();
    profile.languageScores = profile.languageScores.filter((record) => record.id !== id);
    writeMockProfile(profile);
    return;
  }
  await apiClient.delete(`/me/language-scores/${id}`);
}
