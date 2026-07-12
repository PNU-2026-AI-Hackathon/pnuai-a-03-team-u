import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { isAxiosError } from "axios";
import { Check, X } from "lucide-react";
import { getGraduationProgress, isMockStudentDataEnabled, syncPortalData } from "../api/studentInfo";
import type { CourseRecord, GraduationProgram } from "../api/studentInfo";
import { useAuth } from "../auth/AuthContext";

const COURSE_RECORDS_KEY = "planUCourseRecords";
const STUDENT_RECORD_KEY = "planUStudentRecord";
const ACTIVITY_LINKS_KEY = "planUActivityLinks";

const activityItems = [
  { id: "google-dsc", title: "Google DSC Core Member", description: "데이터 분석 스터디 운영, 팀 프로젝트 코드 리뷰, 세미나 발표를 진행했습니다.", addLabel: "활동 기록 추가/보기" },
  { id: "sw-x-competition", title: "SW+X 문제해결 경진대회", description: "바이오 데이터를 활용해 문제를 정의하고 분석 모델을 설계하는 팀 경진대회입니다.", addLabel: "공고 링크 추가" },
  { id: "sql-project", title: "SQL 분석 미니 프로젝트", description: "수강 과목과 연계해 데이터베이스 설계, SQL 쿼리 분석, 시각화 결과물을 정리합니다.", addLabel: "GitHub 링크 추가" },
];

function readStoredCourses() {
  try {
    const saved = window.sessionStorage.getItem(COURSE_RECORDS_KEY);
    return saved ? (JSON.parse(saved) as CourseRecord[]) : [];
  } catch {
    return [];
  }
}

function readStoredStudentRecord() {
  try {
    const saved = window.sessionStorage.getItem(STUDENT_RECORD_KEY);
    return saved ? (JSON.parse(saved) as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function readStoredActivityLinks() {
  try {
    const saved = window.sessionStorage.getItem(ACTIVITY_LINKS_KEY);
    return saved ? (JSON.parse(saved) as Record<string, string[]>) : {};
  } catch {
    return {};
  }
}

function normalizeLink(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return null;

  const candidate = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    return new URL(candidate).toString();
  } catch {
    return null;
  }
}

function getErrorMessage(error: unknown) {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
  }
  return "교과 활동을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
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

export function InfoPage() {
  const { user, isAuthenticated, refreshUser } = useAuth();
  const [loginId, setLoginId] = useState("");
  const [portalPassword, setPortalPassword] = useState("");
  const [courses] = useState<CourseRecord[]>(readStoredCourses);
  const [studentRecord] = useState<Record<string, string>>(readStoredStudentRecord);
  const [graduation, setGraduation] = useState<GraduationProgram | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isGraduationLoading, setIsGraduationLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [activityLinks, setActivityLinks] = useState<Record<string, string[]>>(readStoredActivityLinks);
  const [editingActivityId, setEditingActivityId] = useState<string | null>(null);
  const [draftLink, setDraftLink] = useState("");
  const [linkError, setLinkError] = useState("");

  useEffect(() => {
    if (!isAuthenticated && !isMockStudentDataEnabled) return;

    setIsGraduationLoading(true);
    getGraduationProgress()
      .then((data) => setGraduation(data.programs.find((program) => program.program_type === "primary") ?? data.programs[0] ?? null))
      .catch(() => setGraduation(null))
      .finally(() => setIsGraduationLoading(false));
  }, [isAuthenticated]);

  useEffect(() => {
    window.localStorage.removeItem(ACTIVITY_LINKS_KEY);
    window.sessionStorage.setItem(ACTIVITY_LINKS_KEY, JSON.stringify(activityLinks));
  }, [activityLinks]);

  const gradeTerms = useMemo(() => groupCoursesByTerm(courses), [courses]);
  const syncedName = studentRecord["이름"] ?? studentRecord["성명"];
  const syncedStudentId = studentRecord["학번"];
  const profileName = isMockStudentDataEnabled ? syncedName ?? user?.name : user?.name ?? syncedName;
  const profileStudentId = isMockStudentDataEnabled ? syncedStudentId ?? user?.student_id : user?.student_id ?? syncedStudentId;
  const profileMajor = isMockStudentDataEnabled
    ? studentRecord["전공"] ?? user?.major
    : user?.major ?? studentRecord["전공"] ?? user?.academic_programs.find((program) => program.program_type === "primary")?.major;
  const profileDepartment = isMockStudentDataEnabled ? studentRecord["학부"] ?? user?.department : user?.department ?? studentRecord["학부"];
  const academicYear = isMockStudentDataEnabled ? 3 : getAcademicYear(profileStudentId ?? null);
  const totalCredits = graduation?.required_total_credits;

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
      window.sessionStorage.setItem(COURSE_RECORDS_KEY, JSON.stringify(result.courses));
      window.sessionStorage.setItem(STUDENT_RECORD_KEY, JSON.stringify(result.student_record));
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

  function openLinkEditor(activityId: string) {
    setEditingActivityId(activityId);
    setDraftLink("");
    setLinkError("");
  }

  function closeLinkEditor() {
    setEditingActivityId(null);
    setDraftLink("");
    setLinkError("");
  }

  function handleAddLink(event: FormEvent<HTMLFormElement>, activityId: string) {
    event.preventDefault();
    const normalizedLink = normalizeLink(draftLink);
    if (!normalizedLink) {
      setLinkError("올바른 링크를 입력해 주세요.");
      return;
    }

    setActivityLinks((current) => ({
      ...current,
      [activityId]: [...(current[activityId] ?? []), normalizedLink],
    }));
    closeLinkEditor();
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
          <div className="student-photo">{profileName?.slice(0, 1) ?? "?"}</div>
          <h2>{profileName ?? "이름 정보 없음"}</h2>
          <p className="profile-program">
            {profileDepartment || profileMajor ? (
              <>
                {profileDepartment ? <span>{profileDepartment}</span> : null}
                {profileMajor ? <span>{profileMajor}</span> : null}
              </>
            ) : (
              <span>학적 정보를 불러오면 표시됩니다.</span>
            )}
          </p>
          <p>{academicYear ? `${academicYear}학년` : "학년 정보 없음"}</p>
          <button type="button">편집하기</button>
          <button type="button">저장하기</button>
        </aside>

        <div className="info-content-stack">
          <article className="card info-section-card">
            <div className="card-title">
              <div>
                <p className="eyebrow">Graduation</p>
                <h3>졸업요건</h3>
              </div>
              <strong>
                {graduation && totalCredits !== null && totalCredits !== undefined
                  ? `${formatCredit(graduation.earned_total_credits)} / ${totalCredits}`
                  : "동기화 필요"}
              </strong>
            </div>
            {isGraduationLoading ? <p className="info-state">졸업요건을 불러오는 중입니다.</p> : null}
            {!isGraduationLoading && !graduation ? <p className="info-state">교과 활동을 불러오면 졸업요건을 확인할 수 있습니다.</p> : null}
            {graduation ? (
              <div className="graduation-list">
                {graduation.categories.map((category) => {
                  const percentage = category.required_credits ? Math.min(100, (category.earned_credits / category.required_credits) * 100) : 0;
                  return (
                    <div key={category.category_code}>
                      <span>{category.category_name}</span>
                      <strong>{category.required_credits === null ? "기준 없음" : `${formatCredit(category.earned_credits)} / ${formatCredit(category.required_credits)}`}</strong>
                      <div className="stellic-bar">
                        <span className="earned" style={{ width: `${percentage}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}
            {graduation?.warnings.map((warning) => <p className="graduation-warning" key={warning}>{warning}</p>)}
          </article>

          <article className="card info-section-card">
            <div className="card-title">
              <div>
                <p className="eyebrow">Grades</p>
                <h3>학기별 성적</h3>
              </div>
            </div>
            {gradeTerms.length === 0 ? <p className="info-state">교과 활동을 불러오면 학기별 수강 과목이 표시됩니다.</p> : null}
            <div className="grade-term-list">
              {gradeTerms.map(([term, termCourses]) => (
                <section key={term}>
                  <h4>{term}</h4>
                  <div className="grade-table-wrap">
                    <table className="grade-table">
                      <thead>
                        <tr>
                          <th scope="col">과목명</th>
                          <th scope="col">이수구분</th>
                          <th scope="col">학점</th>
                          <th scope="col">성적</th>
                        </tr>
                      </thead>
                      <tbody>
                        {termCourses.map((course, index) => (
                          <tr key={`${course.course_name}-${index}`}>
                            <td>{course.course_name}</td>
                            <td>{course.category ?? "-"}</td>
                            <td>{course.credits === null ? "-" : formatCredit(course.credits)}</td>
                            <td><strong>{course.grade ?? "-"}</strong></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ))}
            </div>
          </article>

          <article className="card info-section-card">
            <div className="card-title">
              <div>
                <p className="eyebrow">Non-Curricular</p>
                <h3>비교과 활동</h3>
              </div>
            </div>
            <div className="evidence-list">
              {activityItems.map((activity) => {
                const links = activityLinks[activity.id] ?? [];
                const isEditingLink = editingActivityId === activity.id;
                return (
                <article key={activity.id}>
                  <h4>{activity.title}</h4>
                  <div><span>기관명</span><strong>부산대학교</strong></div>
                  <div><span>설명</span><p>{activity.description}</p></div>
                  <div className="evidence-link-row">
                    <span>링크</span>
                    <div className="activity-link-controls">
                      {links.length > 0 ? (
                        <ul className="activity-link-list">
                          {links.map((link, index) => (
                            <li key={`${link}-${index}`}>
                              <a href={link} target="_blank" rel="noreferrer">{link}</a>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {isEditingLink ? (
                        <form className="activity-link-form" onSubmit={(event) => handleAddLink(event, activity.id)}>
                          <input
                            type="text"
                            inputMode="url"
                            value={draftLink}
                            onChange={(event) => {
                              setDraftLink(event.target.value);
                              setLinkError("");
                            }}
                            aria-label={`${activity.title} 링크`}
                            placeholder="https://"
                            autoFocus
                          />
                          <button type="submit"><Check size={16} aria-hidden="true" />확인</button>
                          <button type="button" className="cancel" onClick={closeLinkEditor} aria-label="링크 입력 취소"><X size={16} aria-hidden="true" /></button>
                          {linkError ? <p role="alert">{linkError}</p> : null}
                        </form>
                      ) : null}
                      <button
                        className="add-activity-link"
                        type="button"
                        onClick={() => openLinkEditor(activity.id)}
                        disabled={isEditingLink}
                      >
                        {activity.addLabel}
                      </button>
                    </div>
                  </div>
                </article>
                );
              })}
            </div>
          </article>

          <article className="card info-section-card">
            <div className="card-title"><div><p className="eyebrow">Certificate</p><h3>자격증</h3></div></div>
            <div className="tag-list"><li>GTQ 1급</li><li>빅데이터분석기사 필기</li></div>
          </article>

          <article className="card info-section-card">
            <div className="card-title"><div><p className="eyebrow">Language</p><h3>어학 성적</h3></div></div>
            <div className="tag-list"><li>TOEIC Speaking IM3</li><li>OPIc IM2</li></div>
          </article>
        </div>
      </section>
    </section>
  );
}
