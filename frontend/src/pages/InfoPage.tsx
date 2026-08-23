import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { FormEvent } from "react";
import { isAxiosError } from "axios";
import { useNavigate } from "react-router-dom";
import { Check, LoaderCircle, Pencil, Plus, RotateCcw, Save, Trash2, X } from "lucide-react";
import {
  createActivity,
  createCertification,
  createLanguageScore,
  deleteAccount,
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
import { entryGrade, updateMyProfile } from "../api/auth";
import type { AdmissionType } from "../api/auth";
import {
  clearGraduationOverride,
  getCourseRecords,
  getGraduationProgress,
  isMockStudentDataEnabled,
  replaceCourseRecords,
  saveGraduationOverride,
  setCourseSubstitutions,
  syncPortalData,
} from "../api/studentInfo";
import { getMyCurriculum } from "../api/roadmaps";
import { cancelTrack, enrollTrack, listAvailableTracks, listEnrolledTracks } from "../api/tracks";
import type { AvailableTrack, EnrolledTrack } from "../api/tracks";
import type { CourseRecord, GraduationProgram } from "../api/studentInfo";
import { isMyPusanSyncFailed, myPusanSyncFailedMessage } from "../api/portal";
import { useAuth } from "../auth/AuthContext";
import {
  COURSE_RECORDS_KEY,
  GRADUATION_OVERRIDE_KEY,
  PROFILE_OVERRIDES_KEY,
  STUDENT_RECORD_KEY,
  SYNC_WARNING_KEY,
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

const programTypeLabels: Record<string, string> = {
  dual: "복수전공",
  minor: "부전공",
  interdisciplinary: "연계·융합전공",
};

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

function getErrorMessage(
  error: unknown,
  fallback = "교과 활동을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
) {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
  }
  return fallback;
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
  // "1"/"2"만 학기 번호라 접미사를 붙인다. "여름계절수업"처럼 이미 완성된 이름에
  // 붙이면 "여름계절수업학기"가 된다.
  const semesterLabel = semester === "1" || semester === "2" ? `${semester}학기` : semester ?? "";
  return `${year ?? ""}${year ? "년 " : ""}${semesterLabel}`.trim();
}

/** 편입/조기이수 인정 학점. 어느 학기에도 속하지 않는 lump-sum이라 따로 뺀다. */
/** 대체 지정 목록에 띄울 교육과정 과목 한 줄. */
type SubstitutionOption = {
  id: number;
  course_name: string;
  /** 교양 세부영역 placeholder(`ZFz…`)를 가려내는 데 쓴다. 없으면 영역 판별이 전부
   *  실패해 교양 체크박스가 통째로 안 뜬다(2026-08-20에 실제로 그랬다). */
  course_code: string | null;
  category: string | null;
  credits: number | null;
  /** 교육과정표상 권장 학년. `/me/curriculum`의 그룹 키("1"·"2"·"전학년") 그대로. */
  grade: string;
};

/** 전적대 인정 대체 후보로 띄울 전공 학년. 편입은 1~2학년 과정을 마치고 오므로
 *  인정 대상이 그 구간에 몰린다 — 3·4학년 전공까지 목록에 섞으면 실수로 고르기 쉽다.
 *  (교양은 학년이 아니라 세부영역으로 이수하므로 이 필터를 적용하지 않는다.) */
const TRANSFER_SUBSTITUTION_GRADES = new Set(["1", "2", "전학년"]);
const LIBERAL_ARTS_CATEGORY_MARK = "교양";
const MAJOR_CATEGORY_MARK = "전공";

/** One-Stop 졸업예정정보에서 내려오는 효원균형교양 세부영역.
 *
 * 백엔드는 이 값을 `student_course_records.liberal_area` 전용 컬럼에 저장한다.
 * 목록과 순서는 백엔드 `BALANCED_LIBERAL_AREAS`와 반드시 같이 유지해야 한다. */
const COMPLETED_LIBERAL_AREAS = [
  "사상과역사",
  "사회와문화",
  "문학과예술",
  "과학과기술",
  "건강과레포츠",
  "외국어",
  "융복합",
] as const;

function summarizeCompletedLiberalAreas(courses: CourseRecord[]) {
  return COMPLETED_LIBERAL_AREAS.map((area) => {
    const directMatches = courses.filter(
      (course) => course.liberal_area === area || course.category === area,
    );
    const substitutionMatches = courses.filter((course) =>
      (course.substitutes ?? []).some(
        (substitute) => substitute.course_name.replaceAll(" ", "") === area.replaceAll(" ", ""),
      ),
    );
    const courseNames = [
      ...directMatches.map((course) => course.course_name),
      ...substitutionMatches.map((course) => `${course.course_name} (대체 인정)`),
    ];

    // 입학 전 인정 학점 한 행이 여러 교양 영역을 대체할 수 있다. 그 행의 전체 학점을
    // 각 영역에 반복해서 더하면 실제보다 크게 보이므로, 영역별 학점은 학교 판정으로
    // 직접 연결된 이수기록만 합산하고 대체 지정은 완료 여부와 근거 이름에만 반영한다.
    const credits = directMatches.reduce((sum, course) => sum + (course.credits ?? 0), 0);
    return {
      area,
      completed: directMatches.length > 0 || substitutionMatches.length > 0,
      courseNames: [...new Set(courseNames.filter(Boolean))],
      credits,
    };
  });
}

/** 교양 세부영역 placeholder의 교과목코드 접두사.
 *
 * 부산대는 균형·창의교양의 **영역 자체**를 `courses`에 과목처럼 한 행씩 넣어둔다
 * (`ZFz000091 사상과역사` …). 실제 수강 과목이 아니라 "이 영역을 이수했다"를 가리키는
 * 자리표시자다. 전적대 `교양선택 15학점`처럼 뭉쳐 들어온 기록은 개별 과목이 아니라
 * **어느 영역을 채웠는지**로 대응하므로, 교양 기록에는 과목 목록 대신 영역 체크박스를 준다. */
const LIBERAL_AREA_CODE_PREFIX = "ZFz";

/** 교양 후보를 묶어 보여줄 순서. 규정 제9조 기준 균형 6영역 / 창의 3영역이고,
 *  기초교양·효원핵심교양은 영역이 아니라 실제 교과목 목록이다. */
const LIBERAL_AREA_GROUP_ORDER = ["효원균형교양", "효원창의교양", "기초교양", "효원핵심교양"];

/** 규정 제9조상 **영역** 단위로 이수하는 교양 이수구분. 여기서는 개별 과목이 아니라
 *  영역 placeholder(`ZFz…`)를 고른다. 기초교양·효원핵심교양은 과목 목록이라 제외. */
const AREA_BASED_LIBERAL_CATEGORIES = new Set(["효원균형교양", "효원창의교양"]);

/** 이 후보가 실제 과목이 아니라 교양 세부영역 placeholder인가. */
function isArea(course: SubstitutionOption) {
  return course.course_code?.startsWith(LIBERAL_AREA_CODE_PREFIX) ?? false;
}

const PRE_ADMISSION_SEMESTERS = new Set(["입학전성적", "편입인정"]);
const PRE_ADMISSION_LABEL = "입학 전 인정 학점";

/** 한 해 안에서의 학기 순서. 계절수업은 앞 학기와 뒤 학기 사이에 온다. */
const SEMESTER_RANK: Record<string, number> = {
  "1학기": 1,
  "1": 1,
  여름계절수업: 2,
  여름: 2,
  "2학기": 3,
  "2": 3,
  겨울계절수업: 4,
  겨울: 4,
};

/**
 * 이수 내역을 성적표 그대로 달력 학기로 묶는다.
 *
 * 학년(3학년 1학기)이 아니라 연도·학기로 보여준다 — 여기는 성적을 확인하는
 * 화면이라 성적표와 표기가 같아야 대조가 된다. 학년 기준 배치는 성장 로드맵이
 * 담당한다.
 *
 * 순서는 시간 축의 최신순이다. 가장 최근 학기가 맨 위에 오고, 입학 전 인정
 * 학점이 가장 오래된 것이라 맨 아래로 간다. 계절수업은 같은 해의 앞 학기와
 * 뒤 학기 사이에 들어간다.
 */
function groupCoursesByTerm(courses: CourseRecord[]) {
  const groups = new Map<string, { label: string; sortKey: number; courses: CourseRecord[] }>();

  courses.forEach((course) => {
    const isPreAdmission = Boolean(course.semester && PRE_ADMISSION_SEMESTERS.has(course.semester));
    const label = isPreAdmission ? PRE_ADMISSION_LABEL : formatTerm(course.year, course.semester);
    const sortKey = isPreAdmission
      ? Number.MIN_SAFE_INTEGER
      : (Number(course.year) || 0) * 10 + (SEMESTER_RANK[course.semester ?? ""] ?? 9);

    const existing = groups.get(label);
    if (existing) existing.courses.push(course);
    else groups.set(label, { label, sortKey, courses: [course] });
  });

  return [...groups.values()].sort((left, right) => right.sortKey - left.sortKey);
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
  const { user, isAuthenticated, refreshUser, logoutUser } = useAuth();
  const navigate = useNavigate();
  const [loginId, setLoginId] = useState("");
  const [portalPassword, setPortalPassword] = useState("");
  const [courses, setCourses] = useState<CourseRecord[]>(() => isMockStudentDataEnabled ? readStoredCourses() : []);
  const [studentRecord] = useState<Record<string, string>>(readStoredStudentRecord);
  const [graduation, setGraduation] = useState<GraduationProgram | null>(() => isMockStudentDataEnabled ? readGraduationOverride() : null);
  const [additionalGraduationPrograms, setAdditionalGraduationPrograms] = useState<GraduationProgram[]>([]);
  const [profileOverrides, setProfileOverrides] = useState<ProfileOverrides | null>(() => isMockStudentDataEnabled ? readProfileOverrides() : null);
  const [isProfileEditing, setIsProfileEditing] = useState(false);
  const [profileEditDraft, setProfileEditDraft] = useState<ProfileOverrides>({ name: "", major: "", academicYear: 1 });
  // ProfileOverrides(로컬 저장용 타입)에 넣지 않고 따로 둔다. 입학 구분은 화면
  // 표시 보정값이 아니라 서버가 들고 있어야 하는 학적 정보다.
  const [admissionDraft, setAdmissionDraft] = useState<AdmissionType>("freshman");
  const [profileEditError, setProfileEditError] = useState("");
  const [courseEditDraft, setCourseEditDraft] = useState<CourseRecord[]>([]);
  const [isAddingCourse, setIsAddingCourse] = useState(false);
  const [newCourseDraft, setNewCourseDraft] = useState<CourseDraft>(emptyCourseDraft);
  const [courseEditError, setCourseEditError] = useState("");
  // 전적대 과목 대체 지정 — 어느 이수기록의 검색창이 열려 있는지, 그 검색 상태.
  // 편입 학점 인정은 학과가 학생에게 개별 통보하는 것이라 데이터에 근거가 없다.
  // 그래서 유사도 추천 없이 학생이 검색해서 고른 과목만 저장한다.
  const [substitutionTargetId, setSubstitutionTargetId] = useState<number | null>(null);
  // 고른 것들을 모아 뒀다가 '저장'에서 한 번에 보낸다. 교양 한 줄은 여러 세부영역에
  // 걸쳐 인정받으므로 체크할 때마다 저장하면 요청이 쏟아지고, 중간 상태가 서버에
  // 남아 화면과 어긋난다.
  const [substitutionDraft, setSubstitutionDraft] = useState<number[]>([]);
  const [substitutionQuery, setSubstitutionQuery] = useState("");
  // 고를 대상은 **학생 본인 교육과정**이다(`/me/curriculum` = 학과·전공·적용연도로 좁힌
  // 과목 목록). 전교 과목을 문자열로 검색하게 하면 학과가 인정해 줄 리 없는 과목이나
  // 동명이코드 과목을 집는다 — 편입 인정은 본인 교육과정 안에서만 의미가 있다.
  const [curriculumCourses, setCurriculumCourses] = useState<SubstitutionOption[]>([]);
  const [isCurriculumLoading, setIsCurriculumLoading] = useState(false);
  const [savingSubstitutionId, setSavingSubstitutionId] = useState<number | null>(null);
  // 열려 있는 선택창의 바깥 클릭을 판정하려면 그 DOM을 알아야 한다.
  const substitutionPopoverRef = useRef<HTMLDivElement | null>(null);

  const [substitutionError, setSubstitutionError] = useState("");
  const [graduationEditDraft, setGraduationEditDraft] = useState<GraduationProgram | null>(null);
  const [hasGraduationEdited, setHasGraduationEdited] = useState(false);
  const [graduationEditError, setGraduationEditError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isGraduationLoading, setIsGraduationLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  // 직전 동기화가 남긴 1회성 경고(주로 my.pusan 실패). 리로드를 건너온 값이다.
  const [syncWarning, setSyncWarning] = useState(() => {
    try {
      const saved = window.sessionStorage.getItem(SYNC_WARNING_KEY);
      if (saved) window.sessionStorage.removeItem(SYNC_WARNING_KEY);
      return saved ?? "";
    } catch {
      return "";
    }
  });
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
  // AI융합트랙 — 학생 학과가 대상이 아니면 available이 비고, 섹션 자체를 숨긴다.
  const [availableTracks, setAvailableTracks] = useState<AvailableTrack[]>([]);
  const [enrolledTracks, setEnrolledTracks] = useState<EnrolledTrack[]>([]);
  const [isTrackSaving, setIsTrackSaving] = useState(false);
  const [trackError, setTrackError] = useState("");
  // 회원 탈퇴 — hard delete라 확인 문구 입력을 요구한다.
  const [isDeleteAccountOpen, setIsDeleteAccountOpen] = useState(false);
  const [deleteAccountConfirmText, setDeleteAccountConfirmText] = useState("");
  const [isDeletingAccount, setIsDeletingAccount] = useState(false);
  const [deleteAccountError, setDeleteAccountError] = useState("");
  const [isOverrideClearing, setIsOverrideClearing] = useState(false);

  useEffect(() => {
    if (!isAuthenticated && !isMockStudentDataEnabled) return;

    setIsGraduationLoading(true);
    Promise.all([getCourseRecords(), getGraduationProgress(true)])
      .then(([courseRecords, data]) => {
        const storedOverride = isMockStudentDataEnabled ? readGraduationOverride() : null;
        const fetchedGraduation = data.programs.find((program) => program.program_type === "primary") ?? data.programs[0] ?? null;
        setCourses(courseRecords);
        setGraduation(storedOverride ?? fetchedGraduation);
        setAdditionalGraduationPrograms(data.programs.filter((program) => program.program_type !== "primary"));
      })
      .catch(() => {
        setCourses([]);
        setGraduation(null);
        setAdditionalGraduationPrograms([]);
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

  useEffect(() => {
    if (!isAuthenticated) return;
    Promise.all([listAvailableTracks(), listEnrolledTracks()])
      .then(([available, enrolled]) => {
        setAvailableTracks(available);
        setEnrolledTracks(enrolled);
      })
      .catch(() => {
        // 트랙은 부가 정보 — 실패해도 페이지의 다른 섹션을 막지 않는다.
        setAvailableTracks([]);
        setEnrolledTracks([]);
      });
  }, [isAuthenticated]);

  // 대체 후보 = 본인 교육과정 과목. 한 번만 받아 캐시하고, 목록 안에서 이름으로
  // 걸러 쓴다 — 64과목 정도라 클라이언트에서 거르는 게 매 입력마다 서버를 때리는
  // 것보다 빠르고, 오프라인에서도 목록이 유지된다.
  useEffect(() => {
    if (!isAuthenticated) {
      setCurriculumCourses([]);
      return;
    }
    let cancelled = false;
    setIsCurriculumLoading(true);
    getMyCurriculum()
      .then((curriculum) => {
        if (cancelled) return;
        const seen = new Set<number>();
        const seenNames = new Set<string>();
        const options: SubstitutionOption[] = [];
        for (const group of curriculum.groups ?? []) {
          for (const course of group.courses ?? []) {
            // 같은 과목이 여러 그룹에 나올 수 있다. 목록에서는 한 번만.
            //
            // id뿐 아니라 **이름으로도** 한 번만이다. 수강편람은 같은 교양 과목을
            // 개설 학과별로 다른 코드로 싣는다(`공학작문및발표`가 5행, `대학영어`가
            // 3행). 학생이 고르는 건 "무슨 과목을 인정받았나"라서 그중 어느 코드인지는
            // 의미가 없고, 목록에 같은 이름이 다섯 번 뜨면 고를 수가 없다.
            if (course.id === null || seen.has(course.id)) continue;
            if (seenNames.has(course.course_name)) continue;
            seen.add(course.id);
            seenNames.add(course.course_name);
            options.push({
              id: course.id,
              course_name: course.course_name,
              course_code: course.course_code ?? null,
              category: course.category ?? null,
              credits: course.credits ?? null,
              grade: group.grade,
            });
          }
        }
        options.sort((a, b) => a.course_name.localeCompare(b.course_name, "ko"));
        setCurriculumCourses(options);
      })
      .catch(() => {
        if (!cancelled) setCurriculumCourses([]);
      })
      .finally(() => {
        if (!cancelled) setIsCurriculumLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  // 선택창 바깥을 클릭하거나 Esc를 누르면 닫는다. 팝오버는 표 위에 떠 있어서,
  // 닫는 방법이 '취소' 버튼뿐이면 다른 과목 행을 누르려다 계속 걸린다.
  useEffect(() => {
    if (substitutionTargetId === null) return;

    function handlePointerDown(event: MouseEvent | TouchEvent) {
      const card = substitutionPopoverRef.current;
      if (card && event.target instanceof Node && !card.contains(event.target)) {
        closeSubstitutionPicker();
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") closeSubstitutionPicker();
    }

    // pointerdown(=mousedown)으로 잡는다. click으로 잡으면 목록 항목을 고르는 클릭이
    // 먼저 닫기와 경쟁해서, 고른 순간 창이 닫히며 저장이 취소되는 경우가 생긴다.
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("touchstart", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("touchstart", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [substitutionTargetId]);

  /** 선택창에 띄울 후보.
   *
   * 전공은 **1~2학년만** 남긴다 — 편입 인정은 저학년 과정에 몰리고, 3·4학년 전공까지
   * 섞으면 실수로 고르기 쉽다. 교양은 학년이 아니라 세부영역 단위로 이수하므로
   * 학년으로 거르지 않는다. 입력이 있으면 그 안에서 이름으로 한 번 더 좁힌다.
   */
  const displayedCourses = isProfileEditing ? courseEditDraft : courses;

  /** 지금 열린 선택창의 대상 기록. 교양이면 영역 체크박스 모드로 간다. */
  const substitutionTarget = useMemo(
    () => displayedCourses.find((c) => c.id === substitutionTargetId) ?? null,
    [displayedCourses, substitutionTargetId],
  );
  /** 이 기록에 무엇을 고르게 할지. 이수구분이 섞이면 학생이 실수로 엉뚱한 걸 고른다 —
   *  전적대 `전공선택`은 PNU 전공 과목을, `교양선택`은 교양(세부영역·교양과목)을
   *  대체한 것이다. `일반선택`처럼 어느 쪽도 아닌 기록만 전체에서 고르게 둔다. */
  const substitutionMode: "liberal" | "major" | "any" = useMemo(() => {
    const category = substitutionTarget?.category ?? "";
    if (category.includes(LIBERAL_ARTS_CATEGORY_MARK)) return "liberal";
    if (category.includes(MAJOR_CATEGORY_MARK)) return "major";
    return "any";
  }, [substitutionTarget]);
  const isLiberalArtsTarget = substitutionMode === "liberal";

  const substitutionOptions = useMemo(() => {
    const query = substitutionQuery.trim().toLowerCase();
    return curriculumCourses.filter((course) => {
      const category = course.category ?? "";
      const isLiberal = category.includes(LIBERAL_ARTS_CATEGORY_MARK);
      const isMajor = category.includes(MAJOR_CATEGORY_MARK);
      // 전공 후보는 1~2학년만 남긴다 — 편입 인정은 저학년 과정에 몰리고, 3·4학년
      // 전공까지 섞으면 실수로 고르기 쉽다. 교양은 학년이 아니라 세부영역 단위로
      // 이수하므로 학년으로 거르지 않는다.
      if (isMajor && !TRANSFER_SUBSTITUTION_GRADES.has(course.grade)) return false;
      if (substitutionMode === "liberal" && !isLiberal) return false;
      if (substitutionMode === "major" && !isMajor) return false;
      // 균형·창의교양은 규정상 **영역** 단위로 이수한다(제9조: 균형 6영역 중 2영역,
      // 창의 3영역 중 2영역). 그래서 이 두 구분에서는 개별 과목이 아니라 영역
      // placeholder(`ZFz…`)만 고르게 한다 — 같은 영역의 실제 과목까지 늘어놓으면
      // 학생이 영역을 고르는 건지 과목을 고르는 건지 알 수 없다.
      // 기초교양·효원핵심교양은 영역 개념이 없고 과목 목록이라 그대로 둔다.
      if (AREA_BASED_LIBERAL_CATEGORIES.has(category) !== isArea(course)) return false;
      if (!query) return true;
      return course.course_name.toLowerCase().includes(query);
    });
  }, [curriculumCourses, substitutionQuery, substitutionMode]);

  /** 교양 후보를 이수구분별로 묶는다(균형 6영역 / 창의 3영역 / 기초·핵심 과목). */
  const substitutionAreaGroups = useMemo(() => {
    if (!isLiberalArtsTarget) return [];
    const byCategory = new Map<string, SubstitutionOption[]>();
    for (const option of substitutionOptions) {
      const key = option.category ?? "기타";
      const list = byCategory.get(key);
      if (list) list.push(option);
      else byCategory.set(key, [option]);
    }
    return [...byCategory.entries()].sort((a, b) => {
      const ia = LIBERAL_AREA_GROUP_ORDER.indexOf(a[0]);
      const ib = LIBERAL_AREA_GROUP_ORDER.indexOf(b[0]);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
  }, [isLiberalArtsTarget, substitutionOptions]);
  const displayedGraduation = isProfileEditing ? graduationEditDraft : graduation;
  const admissionType = user?.admission_type ?? "freshman";
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
  const profileMinorMajor = user?.academic_programs?.find((program) => program.program_type === "minor")?.major ?? "";
  const currentSemesterLabel = `${new Date().getMonth() + 1 <= 8 ? 1 : 2}학기 재학 중`;
  const totalCredits = displayedGraduation?.required_total_credits;
  const overallGpa = calculateGpa(displayedCourses);
  const overallMajorGpa = calculateGpa(displayedCourses, true);
  const graduationCategoryTotals = displayedGraduation ? getGraduationCategoryTotals(displayedGraduation) : null;
  const nonTrackAdditionalPrograms = additionalGraduationPrograms.filter((program) => (
    !program.is_ai_track
  ));
  const unselectedTracks = availableTracks.filter((track) => !track.is_enrolled);
  const liberalAreaStatuses = useMemo(
    () => summarizeCompletedLiberalAreas(displayedCourses),
    [displayedCourses],
  );
  const completedLiberalAreaCount = liberalAreaStatuses.filter((area) => area.completed).length;

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
      // 학지시(학적·성적)는 됐는데 my.pusan(비교과·자격증·어학)만 실패한 경우.
      // 백엔드가 이걸 200으로 돌려주므로, 안 보면 사용자는 전부 성공한 줄 안다.
      if (isMyPusanSyncFailed(result)) {
        try {
          window.sessionStorage.setItem(SYNC_WARNING_KEY, myPusanSyncFailedMessage(result));
        } catch {
          // 저장이 막힌 브라우저면 리로드 전에라도 보여준다.
          setSyncWarning(myPusanSyncFailedMessage(result));
        }
      }
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
    setAdmissionDraft(admissionType);
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
        admission_type: admissionDraft,
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

  function openSubstitutionPicker(course: CourseRecord) {
    setSubstitutionTargetId(course.id);
    // 이미 저장된 선택을 초안에 실어 준다. 하나 더 추가하려고 열었을 때 기존 체크가
    // 풀려 있으면, 저장하는 순간 조용히 지워진다.
    setSubstitutionDraft((course.substitutes ?? []).map((s) => s.course_id));
    setSubstitutionQuery("");
    setSubstitutionError("");
  }

  function closeSubstitutionPicker() {
    setSubstitutionTargetId(null);
    setSubstitutionDraft([]);
    setSubstitutionQuery("");
  }

  /** 체크/해제는 초안만 바꾼다. 교양 한 줄은 여러 세부영역에 걸치므로 하나 고를
   *  때마다 저장하면 요청이 쏟아지고, 실수로 켠 중간 상태까지 서버에 남는다. */
  function toggleSubstitutionDraft(courseId: number) {
    setSubstitutionError("");
    setSubstitutionDraft((current) =>
      current.includes(courseId)
        ? current.filter((id) => id !== courseId)
        : [...current, courseId],
    );
  }

  /** 대체 관계를 서버에 저장한다. 부분 갱신이 아니라 **치환**이라, 빈 배열이면 해제다.
   *
   * "내 정보 편집"의 임시 초안(courseEditDraft)에 섞지 않고 바로 서버에 보낸다 —
   * 학과 통보를 받는 시점이 성적 편집과 무관하고, 언제든 고칠 수 있어야 하기 때문이다.
   * 대신 저장 후 목록 상태 두 벌을 함께 갱신해 화면이 어긋나지 않게 한다. */
  async function applySubstitution(course: CourseRecord, courseIds: number[]) {
    setSavingSubstitutionId(course.id);
    setSubstitutionError("");
    try {
      const updated = await setCourseSubstitutions(course.id, courseIds);
      const merge = (records: CourseRecord[]) =>
        records.map((record) => (record.id === updated.id ? { ...record, ...updated } : record));
      setCourses(merge);
      setCourseEditDraft(merge);
      closeSubstitutionPicker();
    } catch (error) {
      setSubstitutionError(getErrorMessage(error, "대체 과목을 저장하지 못했습니다."));
    } finally {
      setSavingSubstitutionId(null);
    }
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

  async function reloadTracks() {
    const [available, enrolled] = await Promise.all([listAvailableTracks(), listEnrolledTracks()]);
    setAvailableTracks(available);
    setEnrolledTracks(enrolled);
  }

  async function handleTrackEnroll(track: AvailableTrack) {
    setIsTrackSaving(true);
    setTrackError("");
    try {
      await enrollTrack(track.major_id);
      await reloadTracks();
    } catch (error) {
      setTrackError(getErrorMessage(error));
    } finally {
      setIsTrackSaving(false);
    }
  }

  async function handleTrackCancel(track: EnrolledTrack) {
    setIsTrackSaving(true);
    setTrackError("");
    try {
      await cancelTrack(track.enrollment_id);
      await reloadTracks();
    } catch (error) {
      setTrackError(getErrorMessage(error));
    } finally {
      setIsTrackSaving(false);
    }
  }

  async function handleClearGraduationOverride() {
    setIsOverrideClearing(true);
    try {
      await clearGraduationOverride();
      const data = await getGraduationProgress();
      setGraduation(data.programs.find((program) => program.program_type === "primary") ?? data.programs[0] ?? null);
    } catch (error) {
      setGraduationEditError(getErrorMessage(error));
    } finally {
      setIsOverrideClearing(false);
    }
  }

  async function handleAccountDelete() {
    if (deleteAccountConfirmText.trim() !== "탈퇴") return;
    setIsDeletingAccount(true);
    setDeleteAccountError("");
    try {
      await deleteAccount();
      // 서버 세션 저장소가 없으므로 토큰을 지워야 로그아웃이 완성된다.
      logoutUser();
      navigate("/", { replace: true });
    } catch (error) {
      setDeleteAccountError(getErrorMessage(error));
      setIsDeletingAccount(false);
    }
  }

  return (
    <section className="info-page">
      <section className="info-sync-panel">
        <div>
          <p className="eyebrow">Course Activity Sync</p>
          <h2>교과 활동 자동 편집</h2>
          <p>학번과 이름을 기준으로 수강 과목, 학점, 성적같은 교과 활동만 불러옵니다.</p>
        </div>
        <form className="sync-form" onSubmit={handleSync}>
          <label>
            <span>학번</span>
            <input value={loginId} onChange={(event) => setLoginId(event.target.value)} type="text" placeholder="예: 2023662247" autoComplete="username" disabled={isLoading} />
          </label>
          <label>
            <span>비밀번호</span>
            <input value={portalPassword} onChange={(event) => setPortalPassword(event.target.value)} type="password" placeholder="학생지원시스템 비밀번호 입력" autoComplete="current-password" disabled={isLoading} />
          </label>
          <button className={isLoading ? "is-loading" : ""} type="submit" disabled={isLoading}>
            {isLoading ? "불러오는 중..." : "교과 활동 불러오기"}
          </button>
          {errorMessage ? <p className="sync-error" role="alert">{errorMessage}</p> : null}
          {syncWarning ? <p className="sync-warning" role="status">{syncWarning}</p> : null}
        </form>
        <div className="sync-hint">
          <strong>불러올 항목 예시</strong>
          <span>수강과목, 이수학점, 학기별 성적, 전공/교양 이수 구분</span>
        </div>
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
              <label>
                <span>입학 구분</span>
                <select value={admissionDraft} onChange={(event) => setAdmissionDraft(event.target.value as AdmissionType)}>
                  <option value="freshman">신입학 (1학년부터)</option>
                  <option value="transfer">편입학 (3학년부터)</option>
                </select>
              </label>
            </div>
          ) : (
            <>
              <span className="profile-term-pill">{currentSemesterLabel}</span>
              <h2>
                {profileName ?? "이름 정보 없음"}
                {profileStudentId ? <span> ({profileStudentId})</span> : null}
              </h2>
              <p className="profile-program">
                {profileProgramNames.length > 0 ? (
                  <span>
                    <em className="program-tag">전</em>
                    {profileProgramNames.join(" · ")}
                  </span>
                ) : (
                  <span>학적 정보를 불러오면 표시됩니다.</span>
                )}
                {profileMinorMajor ? (
                  <span>
                    <em className="program-tag">부</em>
                    {profileMinorMajor}
                  </span>
                ) : null}
              </p>
              <p>
                {academicYear ? `${academicYear}학년 · 졸업요건 점검 중` : "학년 정보 없음"}
                {admissionType === "transfer"
                  ? ` · 편입학 (${entryGrade(admissionType)}학년부터 이수)`
                  : null}
              </p>
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
          <article className="card info-section-card" id="graduation">
            <div className="card-title">
              <div>
                <p className="eyebrow">Graduation</p>
                <h3>졸업 요건</h3>
              </div>
              <div className="graduation-title-tools">
                {!isProfileEditing && (graduation?.warnings ?? []).some((warning) => warning.includes("보정값이 적용")) ? (
                  <button
                    className="override-clear-button"
                    type="button"
                    onClick={() => void handleClearGraduationOverride()}
                    disabled={isOverrideClearing}
                    title="수동 보정을 지우고 이수 기록 기준 자동 계산으로 되돌립니다"
                  >
                    <RotateCcw size={14} aria-hidden="true" />
                    {isOverrideClearing ? "되돌리는 중..." : "보정 해제"}
                  </button>
                ) : null}
                {!isProfileEditing ? <strong>
                  {displayedGraduation && totalCredits !== null && totalCredits !== undefined
                    ? `${formatCredit(displayedGraduation.earned_total_credits)}/${totalCredits}학점`
                    : "동기화 필요"}
                </strong> : null}
              </div>
            </div>
            {!isProfileEditing && displayedGraduation && totalCredits ? (
              <div
                className="graduation-total-bar"
                aria-label={`전체 이수 진행률 ${Math.round((displayedGraduation.earned_total_credits / totalCredits) * 100)}%`}
              >
                <span
                  style={{ width: `${Math.min(100, (displayedGraduation.earned_total_credits / totalCredits) * 100)}%` }}
                />
              </div>
            ) : null}
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
            {displayedGraduation ? (
              <section className="liberal-area-summary" aria-labelledby="liberal-area-summary-title">
                <div className="liberal-area-summary-head">
                  <div>
                    <p>교양 영역</p>
                    <h4 id="liberal-area-summary-title">효원균형교양 이수 현황</h4>
                  </div>
                  <strong>{completedLiberalAreaCount}/{COMPLETED_LIBERAL_AREAS.length}개 영역 확인</strong>
                </div>
                <ul className="liberal-area-grid">
                  {liberalAreaStatuses.map((status) => (
                    <li className={status.completed ? "is-completed" : undefined} key={status.area}>
                      <span className="liberal-area-check" aria-hidden="true">
                        {status.completed ? <Check size={12} /> : null}
                      </span>
                      <span className="liberal-area-copy">
                        <strong>{status.area}</strong>
                        <small>
                          {status.completed
                            ? `${status.courseNames.join(", ")}${status.credits > 0 ? ` · ${formatCredit(status.credits)}학점` : ""}`
                            : "이수 내역 없음"}
                        </small>
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </article>

          {nonTrackAdditionalPrograms.length > 0 || enrolledTracks.length > 0 ? (
            <article className="card info-section-card additional-program-card" id="additional-programs">
              <div className="card-title profile-section-title">
                <div>
                  <p className="eyebrow">Additional Programs</p>
                  <h3>추가 이수과정 현황</h3>
                </div>
              </div>
              <p className="track-hint">
                학생지원시스템에 등록된 부전공·복수전공과 직접 선택한 AI융합트랙의 이수 현황입니다.
              </p>
              <div className="additional-program-list">
                {nonTrackAdditionalPrograms.map((program) => {
                  const label = programTypeLabels[program.program_type] ?? "추가 전공";
                  const name = program.major_name ?? program.department_name ?? label;
                  const total = program.required_total_credits;
                  const percentage = total && total > 0
                    ? Math.min(100, (program.earned_total_credits / total) * 100)
                    : 0;
                  const visibleCategories = program.categories.filter((category) => (
                    category.required_credits !== null && category.required_credits > 0
                  ));
                  return (
                    <section className="additional-program-item" key={program.user_academic_program_id}>
                      <div className="additional-program-head">
                        <div>
                          <span className="program-type-badge">{label}</span>
                          <h4>{name}</h4>
                        </div>
                        <strong>
                          {program.requirement_found && total !== null
                            ? `${formatCredit(program.earned_total_credits)}/${formatCredit(total)}학점`
                            : "기준 확인 필요"}
                        </strong>
                      </div>
                      {program.requirement_found && total !== null ? (
                        <>
                          <div className="graduation-total-bar additional-program-progress" aria-label={`${name} 이수 진행률 ${Math.round(percentage)}%`}>
                            <span style={{ width: `${percentage}%` }} />
                          </div>
                          <p className="additional-program-remaining">
                            {program.satisfied
                              ? "이수요건을 충족했습니다."
                              : `${formatCredit(program.remaining_total_credits ?? 0)}학점 남음`}
                          </p>
                          {visibleCategories.length > 0 ? (
                            <ul className="additional-program-categories">
                              {visibleCategories.map((category) => (
                                <li key={category.category_code}>
                                  <span>{category.category_name}</span>
                                  <strong>{formatCredit(category.earned_credits)}/{formatCredit(category.required_credits ?? 0)}</strong>
                                </li>
                              ))}
                            </ul>
                          ) : null}
                        </>
                      ) : (
                        <p className="graduation-warning">등록된 학과·전공의 기준학점 데이터가 없어 진행도를 계산할 수 없습니다.</p>
                      )}
                    </section>
                  );
                })}
                {enrolledTracks.map((track) => {
                  const percentage = track.total_credits > 0
                    ? Math.min(100, (track.earned_credits / track.total_credits) * 100)
                    : 0;
                  return (
                    <section className="additional-program-item" key={`track-${track.enrollment_id}`}>
                      <div className="additional-program-head">
                        <div>
                          <span className="program-type-badge is-track">AI융합트랙</span>
                          <h4>{track.track_name}</h4>
                        </div>
                        <strong>{formatCredit(track.earned_credits)}/{formatCredit(track.total_credits)}학점</strong>
                      </div>
                      <div className="graduation-total-bar additional-program-progress" aria-label={`${track.track_name} 이수 진행률 ${Math.round(percentage)}%`}>
                        <span style={{ width: `${percentage}%` }} />
                      </div>
                      <div className="additional-program-foot">
                        <p className="additional-program-remaining">
                          {track.completed ? "이수 완료" : `${formatCredit(track.remaining_credits)}학점 남음`}
                        </p>
                        <button className="program-cancel-button" type="button" onClick={() => void handleTrackCancel(track)} disabled={isTrackSaving}>
                          이수 체크 해제
                        </button>
                      </div>
                    </section>
                  );
                })}
              </div>
            </article>
          ) : null}

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
                    <optgroup label="교양 세부영역">
                      {COMPLETED_LIBERAL_AREAS.map((area) => <option value={area} key={area}>{area}</option>)}
                    </optgroup>
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
              {gradeTerms.map(({ label: term, courses: termCourses }) => {
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
                  {/* 편입 학점 인정은 규정이 아니라 학과가 학생 개인에게 통보하는 것이라
                      우리가 알 방법이 없다. 그래서 "왜 직접 골라야 하는지"를 여기서 밝힌다. */}
                  {term === PRE_ADMISSION_LABEL && !isProfileEditing ? (
                    <p className="grade-term-note">
                      학과가 인정해 준 PNU 과목은 성적표에 안 나옵니다. 직접 지정하면 그 과목을
                      시간표·로드맵 추천에서 빼드립니다. (학점은 지금 그대로 계산됩니다.)
                    </p>
                  ) : null}
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
                            <td>
                              {course.course_name}
                              {/* 전적대(입학 전 인정) 과목에만 붙는다. 학교가 이 과목으로
                                  어느 PNU 과목을 인정했는지는 학생 본인만 알기 때문에
                                  시스템이 추측하지 않고 직접 고르게 한다. 편집 모드에서는
                                  성적 초안과 섞이지 않도록 감춘다. */}
                              {course.is_transfer_credit && !isProfileEditing ? (
                                <div className="course-substitution">
                                  {(course.substitutes ?? []).length > 0 ? (
                                    <p className="course-substitution-current">
                                      <Check size={13} aria-hidden="true" />
                                      PNU{" "}
                                      <strong>
                                        {(course.substitutes ?? []).map((s) => s.course_name).join(", ")}
                                      </strong>{" "}
                                      대체
                                    </p>
                                  ) : null}
                                  {substitutionTargetId === course.id
                                    ? createPortal(
                                        /* 표 안이 아니라 화면 중앙 모달로 띄운다.
                                           표 래퍼가 `overflow-x: auto`라 안에 두면 잘리거나
                                           카드가 밀리고, 고정 좌표로 띄우면 스크롤할 때
                                           버튼과 어긋난다. 목록에서 하나 고르는 상호작용은
                                           모달이 표준이고 위치 계산이 아예 없다. */
                                        <div className="substitution-modal-overlay" role="presentation">
                                          <div
                                            className="substitution-modal"
                                            role="dialog"
                                            aria-modal="true"
                                            aria-label={`${course.course_name}이(가) 대체한 과목 선택`}
                                            ref={substitutionPopoverRef}
                                          >
                                            <header className="substitution-modal-head">
                                              <div>
                                                <p className="substitution-modal-eyebrow">전적대 인정 과목</p>
                                                <h4>{course.course_name}</h4>
                                                <p className="substitution-modal-sub">
                                                  {course.credits === null ? "-" : formatCredit(course.credits)}학점 ·
                                                  {" "}
                                                  {substitutionMode === "liberal"
                                                    ? "이 학점으로 채운 교양 영역·과목을 모두 고르세요"
                                                    : substitutionMode === "major"
                                                      ? "이 과목으로 인정받은 PNU 전공 과목을 모두 고르세요"
                                                      : "이 학점으로 인정받은 PNU 과목을 모두 고르세요"}
                                                </p>
                                              </div>
                                              <button
                                                type="button"
                                                className="substitution-modal-close"
                                                aria-label="닫기"
                                                onClick={closeSubstitutionPicker}
                                              >
                                                <X size={16} aria-hidden="true" />
                                              </button>
                                            </header>
                                            {/* 후보는 전교 검색이 아니라 **본인 교육과정**이다.
                                                입력창은 긴 목록을 좁히는 용도일 뿐, 비워두면
                                                전체가 그대로 보인다. */}
                                            <input
                                                value={substitutionQuery}
                                                type="search"
                                                autoComplete="off"
                                                autoFocus
                                                aria-label="교육과정 과목 좁히기"
                                                placeholder="과목명으로 좁히기 (비워두면 전체)"
                                                onChange={(event) => setSubstitutionQuery(event.target.value)}
                                            />
                                            {/* 목록만 스크롤하는 고정 높이 영역.
                                                감싸지 않으면 검색으로 결과 수가 바뀔 때마다
                                                모달 자체가 커졌다 작아졌다 한다. */}
                                            <div className="substitution-modal-body">
                                            {isCurriculumLoading ? (
                                              <p className="course-search-status">
                                                <LoaderCircle size={13} aria-hidden="true" /> 교육과정 불러오는 중
                                              </p>
                                            ) : null}
                                            {!isCurriculumLoading && substitutionOptions.length === 0 ? (
                                              <p className="course-search-status">
                                                {curriculumCourses.length === 0
                                                  ? "교육과정 과목을 불러오지 못했습니다."
                                                  : "이름이 맞는 과목이 없습니다."}
                                              </p>
                                            ) : null}
                                            {isLiberalArtsTarget && substitutionAreaGroups.length > 0 ? (
                                              /* 교양은 과목이 아니라 **세부영역** 단위로 인정받는다.
                                                 전적대 `교양선택 15학점` 한 줄이 여러 영역에 걸치므로
                                                 체크박스로 여러 개를 고를 수 있어야 한다. */
                                              <div className="substitution-area-groups">
                                                {substitutionAreaGroups.map(([groupName, areas]) => (
                                                  <fieldset key={groupName} className="substitution-area-group">
                                                    <legend>
                                                      {groupName}
                                                      <span>
                                                        {areas.length}개
                                                        {AREA_BASED_LIBERAL_CATEGORIES.has(groupName)
                                                          ? " 영역"
                                                          : " 과목"}
                                                      </span>
                                                    </legend>
                                                    {areas.map((area) => (
                                                      <label key={area.id} className="substitution-area-item">
                                                        <input
                                                          type="checkbox"
                                                          checked={substitutionDraft.includes(area.id)}
                                                          disabled={savingSubstitutionId === course.id}
                                                          onChange={() => toggleSubstitutionDraft(area.id)}
                                                        />
                                                        <span>{area.course_name}</span>
                                                      </label>
                                                    ))}
                                                  </fieldset>
                                                ))}
                                              </div>
                                            ) : null}
                                            {!isLiberalArtsTarget && substitutionOptions.length > 0 ? (
                                              <div className="course-search-results">
                                                {substitutionOptions.map((option) => (
                                                  <button
                                                    type="button"
                                                    key={option.id}
                                                    // 전적대 한 과목이 PNU 여러 과목을 대체하기도 해서
                                                    // 여기도 단일 선택이 아니라 토글이다.
                                                    aria-pressed={substitutionDraft.includes(option.id)}
                                                    className={
                                                      substitutionDraft.includes(option.id) ? "is-selected" : undefined
                                                    }
                                                    disabled={savingSubstitutionId === course.id}
                                                    onClick={() => toggleSubstitutionDraft(option.id)}
                                                  >
                                                    <strong>{option.course_name}</strong>
                                                    <span>
                                                      {option.category ?? "이수구분 미정"} · {option.credits ?? 0}학점
                                                      {option.grade ? ` · ${option.grade === "전학년" ? "전학년" : `${option.grade}학년`}` : ""}
                                                    </span>
                                                  </button>
                                                ))}
                                              </div>
                                            ) : null}
                                            </div>
                                            {substitutionError ? (
                                              <p className="profile-edit-error" role="alert">{substitutionError}</p>
                                            ) : null}
                                            <div className="substitution-modal-actions">
                                              {(course.substitutes ?? []).length > 0 ? (
                                                <button
                                                  type="button"
                                                  className="is-danger"
                                                  disabled={savingSubstitutionId === course.id}
                                                  onClick={() => applySubstitution(course, [])}
                                                >
                                                  대체 해제
                                                </button>
                                              ) : null}
                                              <button type="button" onClick={closeSubstitutionPicker}>취소</button>
                                              {/* 고른 것을 한 번에 보낸다. 체크할 때마다 저장하면 요청이
                                                  쏟아지고 실수로 켠 중간 상태까지 서버에 남는다. */}
                                              <button
                                                type="button"
                                                className="is-primary"
                                                disabled={savingSubstitutionId === course.id}
                                                onClick={() => applySubstitution(course, substitutionDraft)}
                                              >
                                                {savingSubstitutionId === course.id
                                                  ? "저장 중"
                                                  : `저장 (${substitutionDraft.length}개)`}
                                              </button>
                                            </div>
                                          </div>
                                        </div>,
                                        document.body,
                                      )
                                    : (
                                    <div className="course-substitution-actions">
                                      <button
                                        type="button"
                                        disabled={savingSubstitutionId === course.id}
                                        onClick={() => openSubstitutionPicker(course)}
                                      >
                                        {(course.substitutes ?? []).length > 0
                                          ? "대체 과목 변경"
                                          : "어떤 과목을 대체했나요?"}
                                      </button>
                                      {(course.substitutes ?? []).length > 0 ? (
                                        <button
                                          type="button"
                                          disabled={savingSubstitutionId === course.id}
                                          onClick={() => applySubstitution(course, [])}
                                        >
                                          해제
                                        </button>
                                      ) : null}
                                    </div>
                                  )}
                                  {substitutionError && substitutionTargetId === course.id ? (
                                    <p className="profile-edit-error" role="alert">{substitutionError}</p>
                                  ) : null}
                                </div>
                              ) : null}
                            </td>
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

          {unselectedTracks.length > 0 ? (
            <article className="card info-section-card">
              <div className="card-title profile-section-title">
                <div><p className="eyebrow">AI Track</p><h3>AI융합트랙 선택</h3></div>
              </div>
              <p className="track-hint">
                졸업요건과 별개로, 이수하면 졸업증명서에 과정명이 표기되는 인증 과정입니다.
                이수 중인 트랙을 선택하면 추가 이수과정 카드에서 진행도를 확인할 수 있습니다.
              </p>
              {trackError ? <p className="sync-error" role="alert">{trackError}</p> : null}
              <div className="profile-record-list">
                {unselectedTracks.map((track) => (
                  <div className="profile-record-row" key={`available-${track.track_program_id}`}>
                    <div>
                      <strong>{track.track_name}</strong>
                      <span>
                        총 {track.total_credits}학점
                        {track.dept_credits?.min ? ` · 학과전공 ${track.dept_credits.min}~${track.dept_credits.max ?? track.dept_credits.min}` : ""}
                        {track.ai_common_credits?.min ? ` · AI공통 ${track.ai_common_credits.min}~${track.ai_common_credits.max ?? track.ai_common_credits.min}` : ""}
                      </span>
                    </div>
                    <button className="profile-add-button" type="button" onClick={() => void handleTrackEnroll(track)} disabled={isTrackSaving}>
                      <Plus size={15} aria-hidden="true" />이수 체크
                    </button>
                  </div>
                ))}
              </div>
            </article>
          ) : null}
        </div>
      </section>

      <section className="card account-danger-card">
        <div className="card-title">
          <div>
            <p className="eyebrow">Danger Zone</p>
            <h3>회원 탈퇴</h3>
          </div>
        </div>
        <p className="track-hint">
          계정과 함께 이수 내역, 로드맵, 시간표, 대화 기록이 모두 즉시 삭제됩니다. 되돌릴 수 없습니다.
        </p>
        {isDeleteAccountOpen ? (
          <div className="account-delete-confirm">
            <label>
              <span>계속하려면 <strong>탈퇴</strong>라고 입력하세요</span>
              <input
                value={deleteAccountConfirmText}
                onChange={(event) => setDeleteAccountConfirmText(event.target.value)}
                placeholder="탈퇴"
                disabled={isDeletingAccount}
              />
            </label>
            {deleteAccountError ? <p className="sync-error" role="alert">{deleteAccountError}</p> : null}
            <div className="profile-editor-actions">
              <button
                className="account-delete-button"
                type="button"
                onClick={() => void handleAccountDelete()}
                disabled={isDeletingAccount || deleteAccountConfirmText.trim() !== "탈퇴"}
              >
                <Trash2 size={15} aria-hidden="true" />
                {isDeletingAccount ? "삭제 중..." : "영구 삭제"}
              </button>
              <button
                className="profile-cancel-button"
                type="button"
                onClick={() => { setIsDeleteAccountOpen(false); setDeleteAccountConfirmText(""); setDeleteAccountError(""); }}
                disabled={isDeletingAccount}
              >
                <X size={15} aria-hidden="true" />취소
              </button>
            </div>
          </div>
        ) : (
          <button className="account-delete-button" type="button" onClick={() => setIsDeleteAccountOpen(true)}>
            <Trash2 size={15} aria-hidden="true" />회원 탈퇴
          </button>
        )}
      </section>
    </section>
  );
}
