import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { isAxiosError } from "axios";
import { Pencil, Plus, Save, Trash2, X } from "lucide-react";
import {
  createActivity,
  createCertification,
  createLanguageScore,
  deleteActivity,
  deleteCertification,
  deleteLanguageScore,
  getActivities,
  getCertifications,
  getLanguageScores,
  updateActivity,
  updateCertification,
  updateLanguageScore,
} from "../api/profile";
import type {
  ActivityPayload,
  ActivityRecord,
  CertificationPayload,
  CertificationRecord,
  LanguageScorePayload,
  LanguageScoreRecord,
} from "../api/profile";
import { updateMyProfile } from "../api/auth";
import {
  getCourseRecords,
  getGraduationProgress,
  isMockStudentDataEnabled,
  replaceCourseRecords,
  saveGraduationOverride,
  syncPortalData,
} from "../api/studentInfo";
import type { CourseRecord, GraduationProgram } from "../api/studentInfo";
import { useAuth } from "../auth/AuthContext";
import {
  COURSE_RECORDS_KEY,
  GRADUATION_OVERRIDE_KEY,
  PROFILE_OVERRIDES_KEY,
  STUDENT_RECORD_KEY,
  getDistinctProgramNames,
  normalizeAcademicYear,
  notifyStudentProfileUpdated,
  readGraduationOverride,
  readProfileOverrides,
  readStoredCourses,
  readStoredStudentRecord,
} from "../data/studentProfileStorage";
import type { ProfileOverrides } from "../data/studentProfileStorage";

const gradePointMap: Record<string, number> = {
  "A+": 4.5,
  A0: 4.0,
  "B+": 3.5,
  B0: 3.0,
  "C+": 2.5,
  C0: 2.0,
  "D+": 1.5,
  D0: 1.0,
  F: 0,
};

const gradeOptions = ["A+", "A0", "B+", "B0", "C+", "C0", "D+", "D0", "F", "P", "S"];

const emptyActivityDraft: ActivityPayload = {
  title: "",
  organization: null,
  category: null,
  role: null,
  award: null,
  description: null,
  url: null,
  start_date: null,
  end_date: null,
};

const emptyCertificationDraft: CertificationPayload = { name: "", expires_at: null };
const emptyLanguageDraft: LanguageScorePayload = { test_name: "", score: "", expires_at: null };

type DeleteTarget = {
  kind: "activity" | "certification" | "language";
  id: number;
  label: string;
};

type CourseDraft = {
  courseName: string;
  category: string;
  credits: string;
  year: string;
  semester: string;
  grade: string;
};

const emptyCourseDraft = (): CourseDraft => ({
  courseName: "",
  category: "전공선택",
  credits: "3",
  year: String(new Date().getFullYear()),
  semester: "1",
  grade: "A0",
});

function getErrorMessage(error: unknown) {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
  }
  return "교과 활동을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

function getProfileErrorMessage(error: unknown) {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
  }
  return "프로필 정보를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

function optionalValue(value: string) {
  return value.trim() || null;
}

function formatDateRange(startDate: string | null, endDate: string | null) {
  if (!startDate && !endDate) return null;
  return `${startDate ?? "시작일 미정"} ~ ${endDate ?? "진행 중"}`;
}

function getAcademicYear(studentId: string | null) {
  const admissionYear = Number(studentId?.slice(0, 4));
  if (!Number.isFinite(admissionYear) || admissionYear < 1900) return null;
  return Math.max(1, new Date().getFullYear() - admissionYear + 1);
}

function formatCredit(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function formatTerm(year: string | null, semester: string | null) {
  if (!year && !semester) return "학기 정보 없음";
  return `${year ?? ""}${year ? "년 " : ""}${semester ?? ""}${semester ? "학기" : ""}`.trim();
}

function groupCoursesByTerm(courses: CourseRecord[]) {
  const groups = new Map<string, CourseRecord[]>();
  courses.forEach((course) => {
    const term = formatTerm(course.year, course.semester);
    groups.set(term, [...(groups.get(term) ?? []), course]);
  });
  return [...groups.entries()];
}

function calculateGpa(courses: CourseRecord[], majorOnly = false) {
  const gradedCourses = courses.filter((course) => {
    if (majorOnly && !course.category?.startsWith("전공")) return false;
    return course.credits !== null && course.credits > 0 && course.grade !== null && gradePointMap[course.grade] !== undefined;
  });
  const totalCredits = gradedCourses.reduce((sum, course) => sum + (course.credits ?? 0), 0);
  if (totalCredits === 0) return null;
  const totalPoints = gradedCourses.reduce(
    (sum, course) => sum + gradePointMap[course.grade ?? ""] * (course.credits ?? 0),
    0,
  );
  return totalPoints / totalCredits;
}

function formatGpa(value: number | null) {
  return value === null ? "-" : value.toFixed(2);
}

function cloneGraduation(program: GraduationProgram | null) {
  return program ? (JSON.parse(JSON.stringify(program)) as GraduationProgram) : null;
}

function normalizeGraduation(program: GraduationProgram) {
  const requiredTotal = program.required_total_credits;
  const earnedTotal = program.earned_total_credits;
  return {
    ...program,
    remaining_total_credits: requiredTotal === null ? null : Math.max(0, requiredTotal - earnedTotal),
    satisfied: requiredTotal === null ? null : earnedTotal >= requiredTotal,
    categories: program.categories.map((category) => ({
      ...category,
      remaining_credits: category.required_credits === null ? null : Math.max(0, category.required_credits - category.earned_credits),
      satisfied: category.required_credits === null ? null : category.earned_credits >= category.required_credits,
    })),
  };
}

function getGraduationCategoryTotals(program: GraduationProgram) {
  return program.categories.reduce(
    (totals, category) => ({
      earned: totals.earned + category.earned_credits,
      required: totals.required + (category.required_credits ?? 0),
    }),
    { earned: 0, required: 0 },
  );
}

function creditsMatch(left: number, right: number) {
  return Math.abs(left - right) < 0.001;
}

export function InfoPage() {
  const { user, isAuthenticated, refreshUser } = useAuth();
  const [loginId, setLoginId] = useState("");
  const [portalPassword, setPortalPassword] = useState("");
  const [courses, setCourses] = useState<CourseRecord[]>(() => isMockStudentDataEnabled ? readStoredCourses() : []);
  const [studentRecord] = useState<Record<string, string>>(readStoredStudentRecord);
  const [graduation, setGraduation] = useState<GraduationProgram | null>(() => isMockStudentDataEnabled ? readGraduationOverride() : null);
  const [profileOverrides, setProfileOverrides] = useState<ProfileOverrides | null>(() => isMockStudentDataEnabled ? readProfileOverrides() : null);
  const [isProfileEditing, setIsProfileEditing] = useState(false);
  const [profileEditDraft, setProfileEditDraft] = useState<ProfileOverrides>({ name: "", major: "", academicYear: 1 });
  const [profileEditError, setProfileEditError] = useState("");
  const [courseEditDraft, setCourseEditDraft] = useState<CourseRecord[]>([]);
  const [isAddingCourse, setIsAddingCourse] = useState(false);
  const [newCourseDraft, setNewCourseDraft] = useState<CourseDraft>(emptyCourseDraft);
  const [courseEditError, setCourseEditError] = useState("");
  const [graduationEditDraft, setGraduationEditDraft] = useState<GraduationProgram | null>(null);
  const [hasGraduationEdited, setHasGraduationEdited] = useState(false);
  const [graduationEditError, setGraduationEditError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isGraduationLoading, setIsGraduationLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [activities, setActivities] = useState<ActivityRecord[]>([]);
  const [certifications, setCertifications] = useState<CertificationRecord[]>([]);
  const [languageScores, setLanguageScores] = useState<LanguageScoreRecord[]>([]);
  const [isProfileLoading, setIsProfileLoading] = useState(true);
  const [profileError, setProfileError] = useState("");
  const [isProfileSaving, setIsProfileSaving] = useState(false);
  const [editingActivityId, setEditingActivityId] = useState<number | "new" | null>(null);
  const [activityDraft, setActivityDraft] = useState<ActivityPayload>(emptyActivityDraft);
  const [editingCertificationId, setEditingCertificationId] = useState<number | "new" | null>(null);
  const [certificationDraft, setCertificationDraft] = useState<CertificationPayload>(emptyCertificationDraft);
  const [editingLanguageId, setEditingLanguageId] = useState<number | "new" | null>(null);
  const [languageDraft, setLanguageDraft] = useState<LanguageScorePayload>(emptyLanguageDraft);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);

  useEffect(() => {
    if (!isAuthenticated && !isMockStudentDataEnabled) return;

    setIsGraduationLoading(true);
    Promise.all([getCourseRecords(), getGraduationProgress()])
      .then(([courseRecords, data]) => {
        const storedOverride = isMockStudentDataEnabled ? readGraduationOverride() : null;
        const fetchedGraduation = data.programs.find((program) => program.program_type === "primary") ?? data.programs[0] ?? null;
        setCourses(courseRecords);
        setGraduation(storedOverride ?? fetchedGraduation);
      })
      .catch(() => {
        setCourses([]);
        setGraduation(null);
      })
      .finally(() => setIsGraduationLoading(false));
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated) return;

    setIsProfileLoading(true);
    Promise.all([getActivities(), getCertifications(), getLanguageScores()])
      .then(([activityRecords, certificationRecords, scoreRecords]) => {
        setActivities(activityRecords);
        setCertifications(certificationRecords);
        setLanguageScores(scoreRecords);
        setProfileError("");
      })
      .catch((error) => setProfileError(getProfileErrorMessage(error)))
      .finally(() => setIsProfileLoading(false));
  }, [isAuthenticated]);

  const displayedCourses = isProfileEditing ? courseEditDraft : courses;
  const displayedGraduation = isProfileEditing ? graduationEditDraft : graduation;
  const gradeTerms = useMemo(() => groupCoursesByTerm(displayedCourses), [displayedCourses]);
  const syncedName = studentRecord["이름"] ?? studentRecord["성명"];
  const syncedStudentId = studentRecord["학번"];
  const baseProfileName = isMockStudentDataEnabled ? syncedName ?? user?.name : user?.name ?? syncedName;
  const profileStudentId = isMockStudentDataEnabled ? syncedStudentId ?? user?.student_id : user?.student_id ?? syncedStudentId;
  const baseProfileMajor = isMockStudentDataEnabled
    ? studentRecord["전공"] ?? user?.major
    : user?.major ?? studentRecord["전공"] ?? user?.academic_programs.find((program) => program.program_type === "primary")?.major;
  const baseProfileDepartment = isMockStudentDataEnabled ? studentRecord["학부"] ?? user?.department : user?.department ?? studentRecord["학부"];
  const baseAcademicYear = isMockStudentDataEnabled
    ? 3
    : normalizeAcademicYear(user?.academic_year) ?? getAcademicYear(profileStudentId ?? null);
  const profileName = profileOverrides?.name ?? baseProfileName;
  const profileDepartment = profileOverrides?.department ?? baseProfileDepartment;
  const profileMajor = profileOverrides?.major ?? baseProfileMajor;
  const academicYear = normalizeAcademicYear(profileOverrides?.academicYear) ?? baseAcademicYear;
  const profileProgramNames = getDistinctProgramNames(profileDepartment, profileMajor);
  const totalCredits = displayedGraduation?.required_total_credits;
  const overallGpa = calculateGpa(displayedCourses);
  const overallMajorGpa = calculateGpa(displayedCourses, true);
  const graduationCategoryTotals = displayedGraduation ? getGraduationCategoryTotals(displayedGraduation) : null;

  async function handleSync(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!loginId.trim() || !portalPassword) {
      setErrorMessage("학번과 학지시 비밀번호를 모두 입력해 주세요.");
      return;
    }

    setErrorMessage("");
    setIsLoading(true);
    try {
      const result = await syncPortalData(loginId.trim(), portalPassword);
      if (isMockStudentDataEnabled) {
        window.sessionStorage.setItem(COURSE_RECORDS_KEY, JSON.stringify(result.courses));
        window.sessionStorage.setItem(STUDENT_RECORD_KEY, JSON.stringify(result.student_record));
      }
      setPortalPassword("");
      if (!isMockStudentDataEnabled) await refreshUser();
      window.location.reload();
    } catch (error) {
      setPortalPassword("");
      setErrorMessage(getErrorMessage(error));
    } finally {
      setIsLoading(false);
    }
  }

  function openProfileEditor() {
    const hasDuplicateProgramName = Boolean(
      profileDepartment && profileMajor && getDistinctProgramNames(profileDepartment, profileMajor).length === 1,
    );
    setProfileEditDraft({
      name: profileName ?? "",
      department: profileDepartment ?? "",
      major: hasDuplicateProgramName ? "" : profileMajor ?? "",
      academicYear: academicYear ?? 1,
    });
    setCourseEditDraft(courses.map((course) => ({ ...course })));
    setIsAddingCourse(false);
    setNewCourseDraft(emptyCourseDraft());
    setCourseEditError("");
    setGraduationEditDraft(cloneGraduation(graduation));
    setHasGraduationEdited(false);
    setGraduationEditError("");
    setProfileEditError("");
    setIsProfileEditing(true);
  }

  function cancelProfileEditor() {
    setIsProfileEditing(false);
    setCourseEditDraft([]);
    setIsAddingCourse(false);
    setNewCourseDraft(emptyCourseDraft());
    setCourseEditError("");
    setGraduationEditDraft(null);
    setHasGraduationEdited(false);
    setGraduationEditError("");
    setProfileEditError("");
  }

  async function saveProfileEditor() {
    if (!profileEditDraft.name.trim() || (!profileEditDraft.department?.trim() && !profileEditDraft.major.trim())) {
      setProfileEditError("이름과 학부/학과 또는 전공을 입력해 주세요.");
      return;
    }

    if (hasGraduationEdited && graduationEditDraft) {
      const categoryTotals = getGraduationCategoryTotals(graduationEditDraft);
      const requiredTotal = graduationEditDraft.required_total_credits;
      const earnedMatches = creditsMatch(graduationEditDraft.earned_total_credits, categoryTotals.earned);
      const requiredMatches = requiredTotal !== null && creditsMatch(requiredTotal, categoryTotals.required);
      if (!earnedMatches || !requiredMatches) {
        setGraduationEditError("총 이수학점과 졸업 기준학점은 하위 항목의 합계와 각각 일치해야 합니다.");
        return;
      }
    }

    const nextOverrides = {
      name: profileEditDraft.name.trim(),
      department: profileEditDraft.department?.trim() ?? "",
      major: profileEditDraft.major.trim(),
      academicYear: Math.min(6, Math.max(1, profileEditDraft.academicYear)),
    };
    const nextGraduation = graduationEditDraft ? normalizeGraduation(graduationEditDraft) : null;
    setIsProfileSaving(true);
    setProfileEditError("");
    try {
      await updateMyProfile({
        name: nextOverrides.name,
        department: nextOverrides.department,
        major: nextOverrides.major || null,
        academic_year: nextOverrides.academicYear,
      });
      const savedCourses = await replaceCourseRecords(courseEditDraft);
      const graduationResult = hasGraduationEdited && nextGraduation
        ? await saveGraduationOverride(nextGraduation)
        : await getGraduationProgress();
      const savedGraduation = graduationResult.programs.find((program) => program.program_type === "primary")
        ?? graduationResult.programs[0]
        ?? null;

      setCourses(savedCourses);
      setGraduation(savedGraduation);
      if (isMockStudentDataEnabled) {
        setProfileOverrides(nextOverrides);
        window.sessionStorage.setItem(PROFILE_OVERRIDES_KEY, JSON.stringify(nextOverrides));
        window.sessionStorage.setItem(COURSE_RECORDS_KEY, JSON.stringify(savedCourses));
        if (savedGraduation) {
          window.sessionStorage.setItem(GRADUATION_OVERRIDE_KEY, JSON.stringify(savedGraduation));
        }
      } else {
        setProfileOverrides(null);
        await refreshUser();
      }
      notifyStudentProfileUpdated();
      cancelProfileEditor();
    } catch (error) {
      setProfileEditError(getProfileErrorMessage(error));
    } finally {
      setIsProfileSaving(false);
    }
  }

  function updateCourseGrade(course: CourseRecord, grade: string) {
    setCourseEditDraft((current) => current.map((record) => (record === course ? { ...record, grade: grade || null } : record)));
  }

  function addCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const credits = Number(newCourseDraft.credits);
    if (!newCourseDraft.courseName.trim() || !/^\d{4}$/.test(newCourseDraft.year) || !Number.isFinite(credits) || credits <= 0) {
      setCourseEditError("과목명, 4자리 연도, 0보다 큰 학점을 확인해 주세요.");
      return;
    }

    setCourseEditDraft((current) => [...current, {
      id: Math.min(-1, ...current.map((course) => course.id - 1)),
      course_name: newCourseDraft.courseName.trim(),
      category: newCourseDraft.category || null,
      credits,
      year: newCourseDraft.year,
      semester: newCourseDraft.semester,
      grade: newCourseDraft.grade || null,
      match_status: "manual",
      source: "manual",
    }]);
    setNewCourseDraft(emptyCourseDraft());
    setCourseEditError("");
    setIsAddingCourse(false);
  }

  function deleteCourse(course: CourseRecord) {
    setCourseEditDraft((current) => current.filter((record) => record !== course));
    setCourseEditError("");
  }

  function updateGraduationTotal(field: "earned_total_credits" | "required_total_credits", value: string) {
    setHasGraduationEdited(true);
    setGraduationEditError("");
    setGraduationEditDraft((current) => current ? {
      ...current,
      [field]: field === "required_total_credits" && value === "" ? null : Number(value || 0),
    } : current);
  }

  function updateGraduationCategory(categoryCode: string, field: "earned_credits" | "required_credits", value: string) {
    setHasGraduationEdited(true);
    setGraduationEditError("");
    setGraduationEditDraft((current) => current ? {
      ...current,
      categories: current.categories.map((category) => category.category_code === categoryCode ? {
        ...category,
        [field]: field === "required_credits" && value === "" ? null : Number(value || 0),
      } : category),
    } : current);
  }

  function closeActivityEditor() {
    setEditingActivityId(null);
    setActivityDraft(emptyActivityDraft);
    setProfileError("");
  }

  function openActivityEditor(activity?: ActivityRecord) {
    setEditingActivityId(activity?.id ?? "new");
    setActivityDraft(activity ? { ...activity } : emptyActivityDraft);
    setProfileError("");
  }

  async function handleActivitySubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activityDraft.title.trim()) {
      setProfileError("활동명을 입력해 주세요.");
      return;
    }

    const payload: ActivityPayload = {
      ...activityDraft,
      title: activityDraft.title.trim(),
      organization: optionalValue(activityDraft.organization ?? ""),
      category: optionalValue(activityDraft.category ?? ""),
      role: optionalValue(activityDraft.role ?? ""),
      award: optionalValue(activityDraft.award ?? ""),
      description: optionalValue(activityDraft.description ?? ""),
      url: optionalValue(activityDraft.url ?? ""),
    };

    setIsProfileSaving(true);
    try {
      if (editingActivityId === "new") {
        const created = await createActivity(payload);
        setActivities((current) => [created, ...current]);
      } else if (typeof editingActivityId === "number") {
        const updated = await updateActivity(editingActivityId, payload);
        setActivities((current) => current.map((record) => (record.id === updated.id ? updated : record)));
      }
      closeActivityEditor();
    } catch (error) {
      setProfileError(getProfileErrorMessage(error));
    } finally {
      setIsProfileSaving(false);
    }
  }

  async function handleActivityDelete(activity: ActivityRecord) {
    setIsProfileSaving(true);
    try {
      await deleteActivity(activity.id);
      setActivities((current) => current.filter((record) => record.id !== activity.id));
      if (editingActivityId === activity.id) closeActivityEditor();
      setDeleteTarget(null);
    } catch (error) {
      setProfileError(getProfileErrorMessage(error));
    } finally {
      setIsProfileSaving(false);
    }
  }

  function openCertificationEditor(certification?: CertificationRecord) {
    setEditingCertificationId(certification?.id ?? "new");
    setCertificationDraft(certification ? { name: certification.name, expires_at: certification.expires_at } : emptyCertificationDraft);
    setProfileError("");
  }

  function closeCertificationEditor() {
    setEditingCertificationId(null);
    setCertificationDraft(emptyCertificationDraft);
    setProfileError("");
  }

  async function handleCertificationSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!certificationDraft.name.trim()) {
      setProfileError("자격증명을 입력해 주세요.");
      return;
    }

    const payload = { ...certificationDraft, name: certificationDraft.name.trim() };
    setIsProfileSaving(true);
    try {
      if (editingCertificationId === "new") {
        const created = await createCertification(payload);
        setCertifications((current) => [created, ...current]);
      } else if (typeof editingCertificationId === "number") {
        const updated = await updateCertification(editingCertificationId, payload);
        setCertifications((current) => current.map((record) => (record.id === updated.id ? updated : record)));
      }
      closeCertificationEditor();
    } catch (error) {
      setProfileError(getProfileErrorMessage(error));
    } finally {
      setIsProfileSaving(false);
    }
  }

  async function handleCertificationDelete(certification: CertificationRecord) {
    setIsProfileSaving(true);
    try {
      await deleteCertification(certification.id);
      setCertifications((current) => current.filter((record) => record.id !== certification.id));
      if (editingCertificationId === certification.id) closeCertificationEditor();
      setDeleteTarget(null);
    } catch (error) {
      setProfileError(getProfileErrorMessage(error));
    } finally {
      setIsProfileSaving(false);
    }
  }

  function openLanguageEditor(score?: LanguageScoreRecord) {
    setEditingLanguageId(score?.id ?? "new");
    setLanguageDraft(score ? { test_name: score.test_name, score: score.score, expires_at: score.expires_at } : emptyLanguageDraft);
    setProfileError("");
  }

  function closeLanguageEditor() {
    setEditingLanguageId(null);
    setLanguageDraft(emptyLanguageDraft);
    setProfileError("");
  }

  async function handleLanguageSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!languageDraft.test_name.trim() || !languageDraft.score.trim()) {
      setProfileError("시험명과 점수를 모두 입력해 주세요.");
      return;
    }

    const payload = {
      ...languageDraft,
      test_name: languageDraft.test_name.trim(),
      score: languageDraft.score.trim(),
    };
    setIsProfileSaving(true);
    try {
      if (editingLanguageId === "new") {
        const created = await createLanguageScore(payload);
        setLanguageScores((current) => [created, ...current]);
      } else if (typeof editingLanguageId === "number") {
        const updated = await updateLanguageScore(editingLanguageId, payload);
        setLanguageScores((current) => current.map((record) => (record.id === updated.id ? updated : record)));
      }
      closeLanguageEditor();
    } catch (error) {
      setProfileError(getProfileErrorMessage(error));
    } finally {
      setIsProfileSaving(false);
    }
  }

  async function handleLanguageDelete(score: LanguageScoreRecord) {
    setIsProfileSaving(true);
    try {
      await deleteLanguageScore(score.id);
      setLanguageScores((current) => current.filter((record) => record.id !== score.id));
      if (editingLanguageId === score.id) closeLanguageEditor();
      setDeleteTarget(null);
    } catch (error) {
      setProfileError(getProfileErrorMessage(error));
    } finally {
      setIsProfileSaving(false);
    }
  }

  function confirmProfileDelete() {
    if (!deleteTarget) return;
    if (deleteTarget.kind === "activity") {
      const activity = activities.find((record) => record.id === deleteTarget.id);
      if (activity) void handleActivityDelete(activity);
    } else if (deleteTarget.kind === "certification") {
      const certification = certifications.find((record) => record.id === deleteTarget.id);
      if (certification) void handleCertificationDelete(certification);
    } else {
      const score = languageScores.find((record) => record.id === deleteTarget.id);
      if (score) void handleLanguageDelete(score);
    }
  }

  return (
    <section className="info-page">
      <section className="info-sync-panel">
        <div>
          <p className="eyebrow">Course Activity Sync</p>
          <h2>교과 활동 불러오기</h2>
          <p>학번과 학지시 비밀번호로 수강 과목, 학점, 성적 같은 교과 활동을 불러옵니다.</p>
        </div>
        <form className="sync-form" onSubmit={handleSync}>
          <label>
            <span>학번</span>
            <input value={loginId} onChange={(event) => setLoginId(event.target.value)} type="text" placeholder="예: 2023662247" autoComplete="username" disabled={isLoading} />
          </label>
          <label>
            <span>학지시 비밀번호</span>
            <input value={portalPassword} onChange={(event) => setPortalPassword(event.target.value)} type="password" autoComplete="current-password" disabled={isLoading} />
          </label>
          <button className={isLoading ? "is-loading" : ""} type="submit" disabled={isLoading}>
            {isLoading ? "불러오는 중..." : "교과 활동 불러오기"}
          </button>
          {errorMessage ? <p className="sync-error" role="alert">{errorMessage}</p> : null}
        </form>
        <p className="sync-note">수강 과목, 이수 학점, 학기별 성적, 전공/교양 이수 구분</p>
      </section>

      <section className="info-layout">
        <aside className="info-profile-card">
          <p className="eyebrow">Profile</p>
          <div className="student-photo">{(isProfileEditing ? profileEditDraft.name : profileName)?.slice(0, 1) ?? "?"}</div>
          {isProfileEditing ? (
            <div className="profile-basic-editor">
              <label>
                <span>이름</span>
                <input value={profileEditDraft.name} onChange={(event) => setProfileEditDraft((current) => ({ ...current, name: event.target.value }))} />
              </label>
              <label>
                <span>학부/학과</span>
                <input value={profileEditDraft.department ?? ""} onChange={(event) => setProfileEditDraft((current) => ({ ...current, department: event.target.value }))} />
              </label>
              <label>
                <span>전공</span>
                <input value={profileEditDraft.major} onChange={(event) => setProfileEditDraft((current) => ({ ...current, major: event.target.value }))} />
              </label>
              <label>
                <span>학년</span>
                <input type="number" min="1" max="6" value={profileEditDraft.academicYear} onChange={(event) => setProfileEditDraft((current) => ({ ...current, academicYear: Number(event.target.value || 1) }))} />
              </label>
            </div>
          ) : (
            <>
              <h2>{profileName ?? "이름 정보 없음"}</h2>
              <p className="profile-program">
                {profileProgramNames.length > 0 ? (
                  profileProgramNames.map((programName) => <span key={programName}>{programName}</span>)
                ) : (
                  <span>학적 정보를 불러오면 표시됩니다.</span>
                )}
              </p>
              <p>{academicYear ? `${academicYear}학년` : "학년 정보 없음"}</p>
            </>
          )}
          {profileEditError ? <p className="profile-edit-error" role="alert">{profileEditError}</p> : null}
          {isProfileEditing ? (
            <div className="profile-main-actions">
              <button type="button" onClick={() => void saveProfileEditor()} disabled={isProfileSaving}><Save size={15} aria-hidden="true" />{isProfileSaving ? "저장 중..." : "저장하기"}</button>
              <button type="button" onClick={cancelProfileEditor} disabled={isProfileSaving}><X size={15} aria-hidden="true" />취소</button>
            </div>
          ) : (
            <button type="button" onClick={openProfileEditor}><Pencil size={15} aria-hidden="true" />편집하기</button>
          )}
        </aside>

        <div className="info-content-stack">
          <article className="card info-section-card">
            <div className="card-title">
              <div>
                <p className="eyebrow">Graduation</p>
                <h3>졸업요건</h3>
              </div>
              {!isProfileEditing ? <strong>
                {displayedGraduation && totalCredits !== null && totalCredits !== undefined
                  ? `${formatCredit(displayedGraduation.earned_total_credits)} / ${totalCredits}`
                  : "동기화 필요"}
              </strong> : null}
            </div>
            {isGraduationLoading ? <p className="info-state">졸업요건을 불러오는 중입니다.</p> : null}
            {!isGraduationLoading && !displayedGraduation ? <p className="info-state">교과 활동을 불러오면 졸업요건을 확인할 수 있습니다.</p> : null}
            {isProfileEditing && displayedGraduation ? (
              <>
                <div className="graduation-total-editor">
                  <label>
                    <span>총 이수학점</span>
                    <input type="number" min="0" step="0.5" value={displayedGraduation.earned_total_credits} onChange={(event) => updateGraduationTotal("earned_total_credits", event.target.value)} />
                  </label>
                  <label>
                    <span>졸업 기준학점</span>
                    <input type="number" min="0" step="0.5" value={displayedGraduation.required_total_credits ?? ""} onChange={(event) => updateGraduationTotal("required_total_credits", event.target.value)} />
                  </label>
                </div>
                {graduationCategoryTotals ? (
                  <p className="graduation-category-total">
                    하위 항목 합계 <strong>{formatCredit(graduationCategoryTotals.earned)} / {formatCredit(graduationCategoryTotals.required)}</strong>
                  </p>
                ) : null}
              </>
            ) : null}
            {displayedGraduation ? (
              <div className="graduation-list">
                {displayedGraduation.categories.map((category) => {
                  const percentage = category.required_credits ? Math.min(100, (category.earned_credits / category.required_credits) * 100) : 0;
                  return (
                    <div key={category.category_code}>
                      <span>{category.category_name}</span>
                      {isProfileEditing ? (
                        <div className="graduation-credit-editor">
                          <input aria-label={`${category.category_name} 이수학점`} type="number" min="0" step="0.5" value={category.earned_credits} onChange={(event) => updateGraduationCategory(category.category_code, "earned_credits", event.target.value)} />
                          <span>/</span>
                          <input aria-label={`${category.category_name} 기준학점`} type="number" min="0" step="0.5" value={category.required_credits ?? ""} onChange={(event) => updateGraduationCategory(category.category_code, "required_credits", event.target.value)} />
                        </div>
                      ) : (
                        <strong>{category.required_credits === null ? "기준 없음" : `${formatCredit(category.earned_credits)} / ${formatCredit(category.required_credits)}`}</strong>
                      )}
                      <div className="stellic-bar">
                        <span className="earned" style={{ width: `${percentage}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}
            {graduationEditError ? <p className="profile-edit-error graduation-edit-error" role="alert">{graduationEditError}</p> : null}
            {displayedGraduation?.warnings.map((warning) => <p className="graduation-warning" key={warning}>{warning}</p>)}
          </article>

          <article className="card info-section-card" id="grades">
            <div className="card-title">
              <div>
                <p className="eyebrow">Grades</p>
                <h3>학기별 성적</h3>
              </div>
              {isProfileEditing ? (
                <button className="profile-add-button" type="button" onClick={() => {
                  setIsAddingCourse((current) => !current);
                  setCourseEditError("");
                }}>
                  {isAddingCourse ? <X size={14} aria-hidden="true" /> : <Plus size={14} aria-hidden="true" />}
                  {isAddingCourse ? "추가 취소" : "수강 과목 추가"}
                </button>
              ) : null}
            </div>
            {isProfileEditing && isAddingCourse ? (
              <form className="course-editor" onSubmit={addCourse}>
                <label className="course-name-field">
                  <span>과목명</span>
                  <input value={newCourseDraft.courseName} onChange={(event) => setNewCourseDraft((current) => ({ ...current, courseName: event.target.value }))} />
                </label>
                <label>
                  <span>이수구분</span>
                  <select value={newCourseDraft.category} onChange={(event) => setNewCourseDraft((current) => ({ ...current, category: event.target.value }))}>
                    <option value="전공기초">전공기초</option>
                    <option value="전공필수">전공필수</option>
                    <option value="전공선택">전공선택</option>
                    <option value="교양필수">교양필수</option>
                    <option value="교양선택">교양선택</option>
                    <option value="일반선택">일반선택</option>
                  </select>
                </label>
                <label>
                  <span>학점</span>
                  <input type="number" min="0.5" step="0.5" value={newCourseDraft.credits} onChange={(event) => setNewCourseDraft((current) => ({ ...current, credits: event.target.value }))} />
                </label>
                <label>
                  <span>연도</span>
                  <input type="number" min="1900" max="2100" value={newCourseDraft.year} onChange={(event) => setNewCourseDraft((current) => ({ ...current, year: event.target.value }))} />
                </label>
                <label>
                  <span>학기</span>
                  <select value={newCourseDraft.semester} onChange={(event) => setNewCourseDraft((current) => ({ ...current, semester: event.target.value }))}>
                    <option value="1">1학기</option>
                    <option value="2">2학기</option>
                    <option value="여름">여름학기</option>
                    <option value="겨울">겨울학기</option>
                  </select>
                </label>
                <label>
                  <span>성적</span>
                  <select value={newCourseDraft.grade} onChange={(event) => setNewCourseDraft((current) => ({ ...current, grade: event.target.value }))}>
                    <option value="">-</option>
                    {gradeOptions.map((grade) => <option value={grade} key={grade}>{grade}</option>)}
                  </select>
                </label>
                <button className="profile-save-button" type="submit"><Plus size={14} aria-hidden="true" />추가</button>
              </form>
            ) : null}
            {courseEditError ? <p className="profile-edit-error course-edit-error" role="alert">{courseEditError}</p> : null}
            <div className="grade-score-overview" aria-label="전체 평점 요약">
              <div><span>전체 총평점</span><strong>{formatGpa(overallGpa)}</strong><small>/ 4.50</small></div>
              <div><span>전체 전공평점</span><strong>{formatGpa(overallMajorGpa)}</strong><small>/ 4.50</small></div>
            </div>
            {gradeTerms.length === 0 ? <p className="info-state">교과 활동을 불러오면 학기별 수강 과목이 표시됩니다.</p> : null}
            <div className="grade-term-list">
              {gradeTerms.map(([term, termCourses]) => {
                const termGpa = calculateGpa(termCourses);
                const termMajorGpa = calculateGpa(termCourses, true);
                return (
                <section key={term}>
                  <div className="grade-term-head">
                    <h4>{term}</h4>
                    <div className="grade-term-scores">
                      <span>총평점 <strong>{formatGpa(termGpa)}</strong></span>
                      <span>전공평점 <strong>{formatGpa(termMajorGpa)}</strong></span>
                    </div>
                  </div>
                  <div className="grade-table-wrap">
                    <table className="grade-table">
                      <thead>
                        <tr>
                          <th scope="col">과목명</th>
                          <th scope="col">이수구분</th>
                          <th scope="col">학점</th>
                          <th scope="col">성적</th>
                          {isProfileEditing ? <th className="grade-action-column" scope="col">삭제</th> : null}
                        </tr>
                      </thead>
                      <tbody>
                        {termCourses.map((course, index) => (
                          <tr key={`${course.course_name}-${index}`}>
                            <td>{course.course_name}</td>
                            <td>{course.category ?? "-"}</td>
                            <td>{course.credits === null ? "-" : formatCredit(course.credits)}</td>
                            <td>
                              {isProfileEditing ? (
                                <select aria-label={`${term} ${course.course_name} 성적`} value={course.grade ?? ""} onChange={(event) => updateCourseGrade(course, event.target.value)}>
                                  <option value="">-</option>
                                  {gradeOptions.map((grade) => <option value={grade} key={grade}>{grade}</option>)}
                                </select>
                              ) : <strong>{course.grade ?? "-"}</strong>}
                            </td>
                            {isProfileEditing ? (
                              <td className="grade-action-column">
                                <button type="button" aria-label={`${course.course_name} 삭제`} onClick={() => deleteCourse(course)}>
                                  <Trash2 size={15} aria-hidden="true" />
                                </button>
                              </td>
                            ) : null}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
                );
              })}
            </div>
          </article>

          {profileError ? <p className="profile-feedback" role="alert">{profileError}</p> : null}
          {deleteTarget ? (
            <div className="profile-delete-confirm" role="alertdialog" aria-label="프로필 항목 삭제 확인">
              <p><strong>{deleteTarget.label}</strong> 항목을 삭제할까요?</p>
              <div>
                <button className="confirm-delete" type="button" onClick={confirmProfileDelete} disabled={isProfileSaving}><Trash2 size={15} aria-hidden="true" />삭제</button>
                <button type="button" onClick={() => setDeleteTarget(null)} disabled={isProfileSaving}>취소</button>
              </div>
            </div>
          ) : null}

          <article className="card info-section-card" id="activities">
            <div className="card-title profile-section-title">
              <div>
                <p className="eyebrow">Non-Curricular</p>
                <h3>비교과 활동</h3>
              </div>
              <button className="profile-add-button" type="button" onClick={() => openActivityEditor()} disabled={isProfileSaving || editingActivityId !== null}>
                <Plus size={15} aria-hidden="true" />활동 추가
              </button>
            </div>
            {editingActivityId !== null ? (
              <form className="profile-editor activity-editor" onSubmit={handleActivitySubmit}>
                <label className="profile-field-wide">
                  <span>활동명</span>
                  <input value={activityDraft.title} onChange={(event) => setActivityDraft((current) => ({ ...current, title: event.target.value }))} required />
                </label>
                <label>
                  <span>기관명</span>
                  <input value={activityDraft.organization ?? ""} onChange={(event) => setActivityDraft((current) => ({ ...current, organization: event.target.value }))} />
                </label>
                <label>
                  <span>분류</span>
                  <input value={activityDraft.category ?? ""} onChange={(event) => setActivityDraft((current) => ({ ...current, category: event.target.value }))} placeholder="예: 동아리, 공모전, 프로젝트" />
                </label>
                <label>
                  <span>역할</span>
                  <input value={activityDraft.role ?? ""} onChange={(event) => setActivityDraft((current) => ({ ...current, role: event.target.value }))} />
                </label>
                <label>
                  <span>수상</span>
                  <input value={activityDraft.award ?? ""} onChange={(event) => setActivityDraft((current) => ({ ...current, award: event.target.value }))} />
                </label>
                <label className="profile-field-wide">
                  <span>설명</span>
                  <textarea value={activityDraft.description ?? ""} onChange={(event) => setActivityDraft((current) => ({ ...current, description: event.target.value }))} rows={3} />
                </label>
                <label className="profile-field-wide">
                  <span>링크</span>
                  <input type="url" value={activityDraft.url ?? ""} onChange={(event) => setActivityDraft((current) => ({ ...current, url: event.target.value }))} placeholder="https://" />
                </label>
                <label>
                  <span>시작일</span>
                  <input type="date" value={activityDraft.start_date ?? ""} onChange={(event) => setActivityDraft((current) => ({ ...current, start_date: event.target.value || null }))} />
                </label>
                <label>
                  <span>종료일</span>
                  <input type="date" value={activityDraft.end_date ?? ""} onChange={(event) => setActivityDraft((current) => ({ ...current, end_date: event.target.value || null }))} />
                </label>
                <div className="profile-editor-actions profile-field-wide">
                  <button className="profile-save-button" type="submit" disabled={isProfileSaving}>
                    <Save size={15} aria-hidden="true" />{isProfileSaving ? "저장 중..." : "저장"}
                  </button>
                  <button className="profile-cancel-button" type="button" onClick={closeActivityEditor} disabled={isProfileSaving}>
                    <X size={15} aria-hidden="true" />취소
                  </button>
                </div>
              </form>
            ) : null}
            {isProfileLoading ? <p className="info-state">비교과 활동을 불러오는 중입니다.</p> : null}
            {!isProfileLoading && activities.length === 0 ? <p className="info-state">등록된 비교과 활동이 없습니다.</p> : null}
            <div className="evidence-list">
              {activities.map((activity) => (
                <article key={activity.id}>
                  <div className="profile-record-heading">
                    <div>
                      <h4>{activity.title}</h4>
                      {activity.category ? <span>{activity.category}</span> : null}
                    </div>
                    <div className="profile-record-actions">
                      <button type="button" onClick={() => openActivityEditor(activity)} disabled={isProfileSaving || editingActivityId !== null} aria-label={`${activity.title} 수정`} title="수정">
                        <Pencil size={15} aria-hidden="true" />
                      </button>
                      <button className="danger" type="button" onClick={() => setDeleteTarget({ kind: "activity", id: activity.id, label: activity.title })} disabled={isProfileSaving} aria-label={`${activity.title} 삭제`} title="삭제">
                        <Trash2 size={15} aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                  {activity.organization ? <div><span>기관명</span><strong>{activity.organization}</strong></div> : null}
                  {activity.role ? <div><span>역할</span><strong>{activity.role}</strong></div> : null}
                  {activity.award ? <div><span>수상</span><strong>{activity.award}</strong></div> : null}
                  {activity.description ? <div><span>설명</span><p>{activity.description}</p></div> : null}
                  {formatDateRange(activity.start_date, activity.end_date) ? <div><span>기간</span><p>{formatDateRange(activity.start_date, activity.end_date)}</p></div> : null}
                  {activity.url ? <div><span>링크</span><a href={activity.url} target="_blank" rel="noreferrer">{activity.url}</a></div> : null}
                </article>
              ))}
            </div>
          </article>

          <article className="card info-section-card" id="credentials">
            <div className="card-title profile-section-title">
              <div><p className="eyebrow">Certificate</p><h3>자격증</h3></div>
              <button className="profile-add-button" type="button" onClick={() => openCertificationEditor()} disabled={isProfileSaving || editingCertificationId !== null}>
                <Plus size={15} aria-hidden="true" />자격증 추가
              </button>
            </div>
            {editingCertificationId !== null ? (
              <form className="profile-editor compact" onSubmit={handleCertificationSubmit}>
                <label>
                  <span>자격증명</span>
                  <input value={certificationDraft.name} onChange={(event) => setCertificationDraft((current) => ({ ...current, name: event.target.value }))} required />
                </label>
                <label>
                  <span>유효기간</span>
                  <input type="date" value={certificationDraft.expires_at ?? ""} onChange={(event) => setCertificationDraft((current) => ({ ...current, expires_at: event.target.value || null }))} />
                </label>
                <div className="profile-editor-actions">
                  <button className="profile-save-button" type="submit" disabled={isProfileSaving}><Save size={15} aria-hidden="true" />저장</button>
                  <button className="profile-cancel-button" type="button" onClick={closeCertificationEditor} disabled={isProfileSaving}><X size={15} aria-hidden="true" />취소</button>
                </div>
              </form>
            ) : null}
            {!isProfileLoading && certifications.length === 0 ? <p className="info-state">등록된 자격증이 없습니다.</p> : null}
            <div className="profile-record-list">
              {certifications.map((certification) => (
                <div className="profile-record-row" key={certification.id}>
                  <div><strong>{certification.name}</strong><span>{certification.expires_at ? `유효기간 ${certification.expires_at}` : "유효기간 없음"}</span></div>
                  <div className="profile-record-actions">
                    <button type="button" onClick={() => openCertificationEditor(certification)} disabled={isProfileSaving || editingCertificationId !== null} aria-label={`${certification.name} 수정`} title="수정"><Pencil size={15} aria-hidden="true" /></button>
                    <button className="danger" type="button" onClick={() => setDeleteTarget({ kind: "certification", id: certification.id, label: certification.name })} disabled={isProfileSaving} aria-label={`${certification.name} 삭제`} title="삭제"><Trash2 size={15} aria-hidden="true" /></button>
                  </div>
                </div>
              ))}
            </div>
          </article>

          <article className="card info-section-card">
            <div className="card-title profile-section-title">
              <div><p className="eyebrow">Language</p><h3>어학 성적</h3></div>
              <button className="profile-add-button" type="button" onClick={() => openLanguageEditor()} disabled={isProfileSaving || editingLanguageId !== null}>
                <Plus size={15} aria-hidden="true" />어학성적 추가
              </button>
            </div>
            {editingLanguageId !== null ? (
              <form className="profile-editor compact" onSubmit={handleLanguageSubmit}>
                <label>
                  <span>시험명</span>
                  <input value={languageDraft.test_name} onChange={(event) => setLanguageDraft((current) => ({ ...current, test_name: event.target.value }))} required />
                </label>
                <label>
                  <span>점수·등급</span>
                  <input value={languageDraft.score} onChange={(event) => setLanguageDraft((current) => ({ ...current, score: event.target.value }))} required />
                </label>
                <label>
                  <span>유효기간</span>
                  <input type="date" value={languageDraft.expires_at ?? ""} onChange={(event) => setLanguageDraft((current) => ({ ...current, expires_at: event.target.value || null }))} />
                </label>
                <div className="profile-editor-actions">
                  <button className="profile-save-button" type="submit" disabled={isProfileSaving}><Save size={15} aria-hidden="true" />저장</button>
                  <button className="profile-cancel-button" type="button" onClick={closeLanguageEditor} disabled={isProfileSaving}><X size={15} aria-hidden="true" />취소</button>
                </div>
              </form>
            ) : null}
            {!isProfileLoading && languageScores.length === 0 ? <p className="info-state">등록된 어학 성적이 없습니다.</p> : null}
            <div className="profile-record-list">
              {languageScores.map((score) => (
                <div className="profile-record-row" key={score.id}>
                  <div><strong>{score.test_name}</strong><span>{score.score}{score.expires_at ? ` · 유효기간 ${score.expires_at}` : ""}</span></div>
                  <div className="profile-record-actions">
                    <button type="button" onClick={() => openLanguageEditor(score)} disabled={isProfileSaving || editingLanguageId !== null} aria-label={`${score.test_name} ${score.score} 수정`} title="수정"><Pencil size={15} aria-hidden="true" /></button>
                    <button className="danger" type="button" onClick={() => setDeleteTarget({ kind: "language", id: score.id, label: `${score.test_name} ${score.score}` })} disabled={isProfileSaving} aria-label={`${score.test_name} ${score.score} 삭제`} title="삭제"><Trash2 size={15} aria-hidden="true" /></button>
                  </div>
                </div>
              ))}
            </div>
          </article>
        </div>
      </section>
    </section>
  );
}
