import { useEffect, useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { getActivities, getCertifications, getLanguageScores } from "../api/profile";
import type { ActivityRecord, CertificationRecord, LanguageScoreRecord } from "../api/profile";
import { getGraduationProgress } from "../api/studentInfo";
import type { CourseRecord, GraduationProgram } from "../api/studentInfo";
import { useAuth } from "../auth/AuthContext";
import {
  getDistinctProgramNames,
  normalizeAcademicYear,
  readGraduationOverride,
  readProfileOverrides,
  readStoredCourses,
  readStoredStudentRecord,
} from "../data/studentProfileStorage";

const fallbackSemesterCredits = [
  ["2025-1", "18"],
  ["2025-2", "21"],
  ["겨울계절", "4"],
  ["2026-1", "18"],
];

const fallbackCredentials = ["GTQ 1급", "컴퓨터그래픽스운용기능사", "TOEIC Speaking IM3"];
const fallbackActivities = [
  { id: -1, category: "교내 활동", title: "진행 중인 활동" },
  { id: -2, category: "외부 활동", title: "지원 완료한 활동" },
];
const CREDENTIAL_PREVIEW_LIMIT = 4;
const ACTIVITY_PREVIEW_LIMIT = 3;
const SEMESTER_PREVIEW_LIMIT = 4;

function getCurrentAcademicTerm(date = new Date()) {
  const year = date.getFullYear();
  const month = date.getMonth() + 1;

  if (month <= 2) return { year: year - 1, semester: 2 as const };
  if (month <= 8) return { year, semester: 1 as const };
  return { year, semester: 2 as const };
}

function formatCredit(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

// 백엔드는 semester를 원시값("1", "2", "1,2", "1학기", "2학기", "여름계절수업",
// "입학전성적" 등) 그대로 돌려준다. 정렬용 순서와 사용자에게 보여줄 라벨을 여기서
// 통일한다. "입학전성적"은 편입 인정 학점 lump-sum이라 학기 slot에 안 들어가고
// 별개로 취급한다 — 편입생 대시보드에서는 이 값이 다른 학기들보다 훨씬 커서
// 평균 왜곡을 만들기 때문에 학기별 표에서 제외한다.
function normalizeSemesterSlot(raw: string): { order: number; label: string } | null {
  const s = raw.trim();
  if (s === "입학전성적" || s === "편입인정") return null;
  if (s === "1" || s === "1학기") return { order: 1, label: "1학기" };
  if (s === "2" || s === "2학기") return { order: 3, label: "2학기" };
  if (s === "1,2" || s === "전학기") return { order: 5, label: "학기 무관" };
  if (s.includes("여름계절")) return { order: 2, label: "여름계절" };
  if (s.includes("겨울계절")) return { order: 4, label: "겨울계절" };
  if (s.includes("여름도약")) return { order: 2, label: "여름도약" };
  if (s.includes("겨울도약")) return { order: 4, label: "겨울도약" };
  return { order: 6, label: s };
}

function getSemesterCredits(courses: CourseRecord[]) {
  const groups = new Map<string, { label: string; credits: number; sortValue: number }>();

  courses.forEach((course) => {
    if (!course.year || !course.semester || course.credits === null) return;
    const slot = normalizeSemesterSlot(course.semester);
    if (slot === null) return; // "입학전성적" 등 학기 단위 아닌 값은 제외
    const key = `${course.year}-${slot.label}`;
    const current = groups.get(key);
    groups.set(key, {
      label: `${course.year} ${slot.label}`,
      credits: (current?.credits ?? 0) + course.credits,
      sortValue: Number(course.year) * 10 + slot.order,
    });
  });

  return [...groups.values()]
    .sort((left, right) => left.sortValue - right.sortValue)
    .map(({ label, credits }) => [label, formatCredit(credits)]);
}

export function DashboardPage() {
  const { user } = useAuth();
  const [profileOverrides] = useState(readProfileOverrides);
  const [studentRecord] = useState(readStoredStudentRecord);
  const [courses] = useState(readStoredCourses);
  const [graduation, setGraduation] = useState<GraduationProgram | null>(readGraduationOverride);
  const [activities, setActivities] = useState<ActivityRecord[] | null>(null);
  const [certifications, setCertifications] = useState<CertificationRecord[] | null>(null);
  const [languageScores, setLanguageScores] = useState<LanguageScoreRecord[] | null>(null);
  const currentTerm = useMemo(() => getCurrentAcademicTerm(), []);

  const studentId = studentRecord["학번"] ?? user?.student_id ?? "2023662247";
  const profileName = profileOverrides?.name ?? studentRecord["이름"] ?? studentRecord["성명"] ?? user?.name ?? "이도원";
  const department = profileOverrides?.department ?? studentRecord["학부"] ?? user?.department ?? "";
  const major = profileOverrides?.major ?? studentRecord["전공"] ?? user?.major ?? "";
  const academicYear = normalizeAcademicYear(profileOverrides?.academicYear) ?? 3;
  const profileProgramNames = getDistinctProgramNames(department, major);
  const careerGoal = user?.career_goal ?? "데이터 사이언티스트";
  const consultationStatusLabel = user?.advisor_consulted ? "상담 완료" : "상담예정";

  useEffect(() => {
    if (graduation) return;
    getGraduationProgress()
      .then((data) => setGraduation(data.programs.find((program) => program.program_type === "primary") ?? data.programs[0] ?? null))
      .catch(() => undefined);
  }, [graduation]);

  useEffect(() => {
    Promise.all([getActivities(), getCertifications(), getLanguageScores()])
      .then(([activityRecords, certificationRecords, scoreRecords]) => {
        setActivities(activityRecords);
        setCertifications(certificationRecords);
        setLanguageScores(scoreRecords);
      })
      .catch(() => undefined);
  }, []);

  const earnedCredits = graduation?.earned_total_credits ?? 112;
  const requiredCredits = graduation?.required_total_credits ?? 130;
  const remainingCredits = requiredCredits === null ? null : Math.max(0, requiredCredits - earnedCredits);
  const creditProgress = requiredCredits ? Math.min(100, Math.round((earnedCredits / requiredCredits) * 100)) : 0;
  const profileFacts = [
    ...(profileProgramNames.length === 1
      ? [[department.trim() ? "학과" : "전공", profileProgramNames[0]]]
      : [["학부", department], ["전공", major]]),
    ["학년", `${academicYear}학년`],
    ["진로", careerGoal],
  ];
  const storedSemesterCredits = useMemo(() => getSemesterCredits(courses), [courses]);
  const semesterCredits = storedSemesterCredits.length > 0 ? storedSemesterCredits : fallbackSemesterCredits;
  const visibleSemesterCredits = semesterCredits.slice(-SEMESTER_PREVIEW_LIMIT);
  const averageCredits = semesterCredits.length > 0
    ? semesterCredits.reduce((sum, [, credit]) => sum + Number(credit), 0) / semesterCredits.length
    : 0;
  const credentials = certifications && languageScores
    ? [
        ...certifications.map((record) => record.name),
        ...languageScores.map((record) => `${record.test_name} ${record.score}`),
      ]
    : fallbackCredentials;
  const visibleCredentials = credentials.slice(0, CREDENTIAL_PREVIEW_LIMIT);
  const dashboardActivities = activities ?? fallbackActivities;
  const visibleActivities = dashboardActivities.slice(0, ACTIVITY_PREVIEW_LIMIT);

  return (
    <>
      <section className="hero-panel">
        <div className="student-card">
          <div className="student-photo">{profileName.slice(0, 1)}</div>
          <div>
            <div className="semester-pill">현재 학기 · {currentTerm.semester}학기 재학 중</div>
            <h2>
              {profileName} <span>({studentId})</span>
            </h2>
            <p>{profileProgramNames.join(" · ")}</p>
            <p>{academicYear}학년 · 졸업 요건 점검 중</p>
          </div>
        </div>

        <div className="profile-facts">
          {profileFacts.map(([label, value]) => (
            <article key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </article>
          ))}
        </div>

        <div className="program-progress" aria-label="학점 진행 현황">
          <div className="progress-line">
            <div className="progress-heading">
              <strong>들은 학점</strong>
              <span>{formatCredit(earnedCredits)} / {requiredCredits === null ? "-" : formatCredit(requiredCredits)}학점</span>
            </div>
            <div className="stellic-bar" aria-label={`들은 학점 진행률 ${creditProgress}%`}>
              <span className="earned" style={{ width: `${creditProgress}%` }} />
            </div>
          </div>
          <div className="credit-stats" aria-label="학점 숫자 요약">
            <div>
              <strong>{formatCredit(earnedCredits)}</strong>
              <span>들은 학점</span>
            </div>
            <div>
              <strong>{requiredCredits === null ? "-" : formatCredit(requiredCredits)}</strong>
              <span>졸업 요건 학점</span>
            </div>
            <div>
              <strong>{remainingCredits === null ? "-" : formatCredit(remainingCredits)}</strong>
              <span>남은 학점</span>
            </div>
          </div>
        </div>
      </section>

      <section className="overview-grid" aria-label="학업 현황">
        <article className="card advisor-card" id="advisor">
          <div className="card-title">
            <div>
              <p className="eyebrow">지도 교수</p>
              <h3>{user?.advisor_name ?? "미동기화"}</h3>
            </div>
            <span className="status blue">{consultationStatusLabel}</span>
          </div>
          <p>{currentTerm.year}년 {currentTerm.semester}학기 상담 여부만 홈에서 확인합니다.</p>
          <div className="advisor-current-status" aria-label="현재 학기 상담 상태">
            <span>{currentTerm.year}년 {currentTerm.semester}학기</span>
            <strong>{consultationStatusLabel}</strong>
          </div>
        </article>

        <article className="card activity-card dashboard-summary-card">
          <div className="card-title">
            <div>
              <p className="eyebrow">Non-Curricular</p>
              <h3>비교과 활동</h3>
            </div>
            <strong>{activities?.length ?? fallbackActivities.length}건</strong>
          </div>
          <ul className="dashboard-record-list">
            {visibleActivities.map((activity) => (
              <li key={activity.id}>
                <span>{activity.category ?? "활동"}</span>
                <strong>{activity.title}</strong>
              </li>
            ))}
            {dashboardActivities.length === 0 ? <li className="empty">등록된 활동 없음</li> : null}
          </ul>
          {dashboardActivities.length > ACTIVITY_PREVIEW_LIMIT ? (
            <Link className="dashboard-more-link" to="/info#activities">더보기 <ChevronRight size={14} aria-hidden="true" /></Link>
          ) : null}
        </article>

        <article className="card certificate-card dashboard-summary-card">
          <div className="card-title">
            <div>
              <p className="eyebrow">Certificate · Language</p>
              <h3>자격증 · 어학</h3>
            </div>
            <strong>{credentials.length}개</strong>
          </div>
          <ul className="tag-list">
            {visibleCredentials.map((credential) => <li key={credential}>{credential}</li>)}
            {credentials.length === 0 ? <li>등록된 항목 없음</li> : null}
          </ul>
          {credentials.length > CREDENTIAL_PREVIEW_LIMIT ? (
            <Link className="dashboard-more-link" to="/info#credentials">더보기 <ChevronRight size={14} aria-hidden="true" /></Link>
          ) : null}
        </article>

        <article className="card credit-chart-card dashboard-summary-card">
          <div className="card-title">
            <div>
              <p className="eyebrow">학기별 학점</p>
              <h3>최근 이수 현황</h3>
            </div>
            <span>평균 {averageCredits.toFixed(1)}학점</span>
          </div>
          <div className="credit-chart">
            {visibleSemesterCredits.map(([label, credit]) => (
              <div key={label}>
                <small>{label}</small>
                <strong>{credit}<span>학점</span></strong>
              </div>
            ))}
          </div>
          {semesterCredits.length > SEMESTER_PREVIEW_LIMIT ? (
            <Link className="dashboard-more-link" to="/info#grades">더보기 <ChevronRight size={14} aria-hidden="true" /></Link>
          ) : null}
        </article>

        <article className="card term-card">
          <div className="card-title">
            <div>
              <p className="eyebrow">현재 상태</p>
              <h3>학사 캘린더</h3>
            </div>
            <span className="status blue">1학기</span>
          </div>
          <div className="term-options" aria-label="학기 상태">
            <span className="selected">1학기</span>
            <span>2학기</span>
            <span>여름계절</span>
            <span>겨울계절</span>
            <span>여름방학</span>
            <span>휴학</span>
          </div>
        </article>
      </section>
    </>
  );
}
