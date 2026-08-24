import { useEffect, useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { getActivities, getCertifications, getLanguageScores } from "../api/profile";
import type { ActivityRecord, CertificationRecord, LanguageScoreRecord } from "../api/profile";
import { updateAdvisorConsulted } from "../api/auth";
import { getGraduationProgress, isMockStudentDataEnabled } from "../api/studentInfo";
import type { GraduationProgram } from "../api/studentInfo";
import { useAuth } from "../auth/AuthContext";
import {
  getDistinctProgramNames,
  normalizeAcademicYear,
  readGraduationOverride,
  readProfileOverrides,
  readStoredStudentRecord,
} from "../data/studentProfileStorage";

const fallbackCredentials = ["GTQ 1급", "컴퓨터그래픽스운용기능사", "TOEIC Speaking IM3"];
const fallbackActivities = [
  { id: -1, category: "교내 활동", title: "진행 중인 활동" },
  { id: -2, category: "외부 활동", title: "지원 완료한 활동" },
];
const CREDENTIAL_PREVIEW_LIMIT = 4;
const ACTIVITY_PREVIEW_LIMIT = 3;

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


export function DashboardPage() {
  const { user, refreshUser } = useAuth();
  const [profileOverrides] = useState(() => isMockStudentDataEnabled ? readProfileOverrides() : null);
  const [studentRecord] = useState(readStoredStudentRecord);
  const [graduation, setGraduation] = useState<GraduationProgram | null>(() => isMockStudentDataEnabled ? readGraduationOverride() : null);
  const [activities, setActivities] = useState<ActivityRecord[] | null>(null);
  const [certifications, setCertifications] = useState<CertificationRecord[] | null>(null);
  const [languageScores, setLanguageScores] = useState<LanguageScoreRecord[] | null>(null);
  const [advisorConsulted, setAdvisorConsulted] = useState(Boolean(user?.advisor_consulted));
  const [isAdvisorSaving, setIsAdvisorSaving] = useState(false);
  const currentTerm = useMemo(() => getCurrentAcademicTerm(), []);

  const studentId = studentRecord["학번"] ?? user?.student_id ?? "-";
  const profileName = profileOverrides?.name ?? studentRecord["이름"] ?? studentRecord["성명"] ?? user?.name ?? "사용자";
  const department = profileOverrides?.department ?? studentRecord["학부"] ?? user?.department ?? "";
  const major = profileOverrides?.major ?? studentRecord["전공"] ?? user?.major ?? "";
  const academicYear = normalizeAcademicYear(profileOverrides?.academicYear ?? user?.academic_year);
  const profileProgramNames = getDistinctProgramNames(department, major);
  const careerGoal = user?.career_goal?.trim() || "-";
  const currentConsultationStatus = advisorConsulted ? "상담 완료" : "상담예정";

  useEffect(() => {
    setAdvisorConsulted(Boolean(user?.advisor_consulted));
  }, [user?.advisor_consulted]);

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

  async function toggleAdvisorConsulted() {
    if (isAdvisorSaving) return;
    const nextValue = !advisorConsulted;
    setIsAdvisorSaving(true);
    try {
      const result = await updateAdvisorConsulted(nextValue);
      setAdvisorConsulted(result.advisor_consulted);
      await refreshUser();
    } finally {
      setIsAdvisorSaving(false);
    }
  }

  const earnedCredits = graduation?.earned_total_credits ?? (isMockStudentDataEnabled ? 112 : 0);
  const requiredCredits = graduation?.required_total_credits ?? (isMockStudentDataEnabled ? 130 : null);
  const remainingCredits = requiredCredits === null ? null : Math.max(0, requiredCredits - earnedCredits);
  const creditProgress = requiredCredits ? Math.min(100, Math.round((earnedCredits / requiredCredits) * 100)) : 0;
  const minorProgram = user?.academic_programs?.find((program) => program.program_type === "minor");
  const dualProgram = user?.academic_programs?.find((program) => program.program_type === "dual");
  const minorMajor = minorProgram?.major || minorProgram?.department || "-";
  const dualMajor = dualProgram?.major || dualProgram?.department || "-";
  const profileFacts = [
    ...(profileProgramNames.length === 1
      ? [[department.trim() ? "학과" : "전공", profileProgramNames[0]]]
      : [["학부", department], ["전공", major]]),
    ["부전공", minorMajor],
    ["학년", academicYear ? `${academicYear}학년` : "-"],
    ["진로", careerGoal],
    ["복수전공", dualMajor],
  ];
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
            <p className="student-program">
              <span className="program-tag">전</span>
              {profileProgramNames.join(" · ")}
            </p>
            {minorMajor !== "-" ? (
              <p className="student-program">
                <span className="program-tag">부</span>
                {minorMajor}
              </p>
            ) : null}
            <p>{academicYear ? `${academicYear}학년` : "학년 정보 없음"} · 졸업 요건 점검 중</p>
          </div>
        </div>

        <div className="profile-facts">
          {profileFacts.map(([label, value]) => (
            <article key={label}>
              <span>{label}</span>
              <strong>{value || "-"}</strong>
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
            <span className="status blue">{currentConsultationStatus}</span>
          </div>
          <p>{currentTerm.year}년 {currentTerm.semester}학기 상담 여부만 홈에서 확인합니다.</p>
          <div className="advisor-current-status" aria-label="현재 학기 상담 상태">
            <span>{currentTerm.year}년 {currentTerm.semester}학기</span>
            <button
              className="advisor-status-toggle"
              type="button"
              role="switch"
              aria-checked={advisorConsulted}
              disabled={isAdvisorSaving}
              onClick={() => void toggleAdvisorConsulted()}
            >
              <span aria-hidden="true" />
              <strong>{isAdvisorSaving ? "저장 중" : currentConsultationStatus}</strong>
            </button>
          </div>
        </article>

        <article className="card certificate-card dashboard-summary-card">
          <div className="card-title">
            <div>
              <p className="eyebrow">자격증 · 어학</p>
              <h3>자격증 및 어학 성적</h3>
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

        <article className="card activity-card dashboard-summary-card">
          <div className="card-title">
            <div>
              <p className="eyebrow">활동</p>
              <h3>활동 목록</h3>
            </div>
            <strong>{activities?.length ?? fallbackActivities.length}건</strong>
          </div>
          <ul className="dashboard-record-list is-bulleted">
            {visibleActivities.map((activity, index) => (
              <li key={activity.id}>
                <span className={`record-dot ${index % 2 === 0 ? "is-green" : "is-red"}`} aria-hidden="true" />
                <div>
                  <strong>{activity.title}</strong>
                  <span>{activity.category ?? "활동"}</span>
                </div>
              </li>
            ))}
            {dashboardActivities.length === 0 ? <li className="empty">등록된 활동 없음</li> : null}
          </ul>
          {dashboardActivities.length > ACTIVITY_PREVIEW_LIMIT ? (
            <Link className="dashboard-more-link" to="/info#activities">더보기 <ChevronRight size={14} aria-hidden="true" /></Link>
          ) : null}
        </article>

      </section>
    </>
  );
}
