import type { AdmissionType } from "../api/auth";

const SIGNUP_FLOW_KEY = "planUSignupFlow";

export type SignupDraft = {
  emailId: string;
  name: string;
  studentId: string;
  admissionType: AdmissionType;
  department: string;
  primaryMajor: string;
  careerGoal: string;
  minorDepartment: string;
  minorMajor: string;
  dualDepartment: string;
  dualMajor: string;
  additionalProgramsOpen: boolean;
  wantsTrack: boolean;
};

export function saveSignupFlow(draft: SignupDraft) {
  window.sessionStorage.setItem(SIGNUP_FLOW_KEY, JSON.stringify(draft));
}

export function readSignupFlow(): SignupDraft | null {
  const saved = window.sessionStorage.getItem(SIGNUP_FLOW_KEY);
  if (!saved) return null;

  try {
    return JSON.parse(saved) as SignupDraft;
  } catch {
    window.sessionStorage.removeItem(SIGNUP_FLOW_KEY);
    return null;
  }
}

export function hasActiveSignupFlow() {
  return readSignupFlow() !== null;
}

export function clearSignupFlow() {
  window.sessionStorage.removeItem(SIGNUP_FLOW_KEY);
}
