import { useMemo } from "react";

type ConsultationStatus = "scheduled" | "completed";

const studentId = "2023662247";

const profileFacts = [
  ["학부", "의생명융합공학부"],
  ["전공", "데이터사이언스전공"],
  ["학년", "3학년"],
  ["진로", "데이터 사이언티스트"],
];

const semesterCredits = [
  ["2025-1", "18"],
  ["2025-2", "21"],
  ["겨울계절", "4"],
  ["2026-1", "18"],
];

function getCurrentAcademicTerm(date = new Date()) {
  const year = date.getFullYear();
  const month = date.getMonth() + 1;

  if (month <= 2) {
    return { year: year - 1, semester: 2 as const };
  }

  if (month <= 8) {
    return { year, semester: 1 as const };
  }

  return { year, semester: 2 as const };
}

const statusLabels: Record<ConsultationStatus, string> = {
  scheduled: "상담예정",
  completed: "상담 완료",
};

function getConsultationStorageKey(studentNumber: string) {
  return `plan-u:advisor-consultations:${studentNumber}`;
}

function isConsultationStatus(status: string): status is ConsultationStatus {
  return status === "scheduled" || status === "completed";
}

function loadCurrentConsultationStatus(
  studentNumber: string,
  currentTerm: { year: number; semester: 1 | 2 },
): ConsultationStatus {
  try {
    const saved = window.localStorage.getItem(getConsultationStorageKey(studentNumber));
    if (!saved) return "scheduled";

    const parsed = JSON.parse(saved) as Record<string, string>;
    const status = parsed[`${currentTerm.year}-${currentTerm.semester}`];
    return status && isConsultationStatus(status) ? status : "scheduled";
  } catch {
    return "scheduled";
  }
}

export function DashboardPage() {
  const currentTerm = useMemo(() => getCurrentAcademicTerm(), []);
  const currentConsultationStatus = useMemo(
    () => loadCurrentConsultationStatus(studentId, currentTerm),
    [currentTerm],
  );

  return (
    <>
      <section className="hero-panel">
        <div className="student-card">
          <div className="student-photo">이</div>
          <div>
            <div className="semester-pill">현재 학기 · {currentTerm.semester}학기 재학 중</div>
            <h2>
              이도원 <span>({studentId})</span>
            </h2>
            <p>의생명융합공학부 · 데이터사이언스전공</p>
            <p>3학년 · 졸업 요건 점검 중</p>
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
              <span>112 / 130학점</span>
            </div>
            <div className="stellic-bar" aria-label="들은 학점 진행률 86%">
              <span className="earned" style={{ width: "86%" }} />
            </div>
          </div>
          <div className="credit-stats" aria-label="학점 숫자 요약">
            <div>
              <strong>112</strong>
              <span>들은 학점</span>
            </div>
            <div>
              <strong>130</strong>
              <span>졸업 요건 학점</span>
            </div>
            <div>
              <strong>18</strong>
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
              <h3>김도현 교수</h3>
            </div>
            <span className="status blue">{statusLabels[currentConsultationStatus]}</span>
          </div>
          <p>
            {currentTerm.year}년 {currentTerm.semester}학기 상담 여부만 홈에서 확인합니다.
          </p>
          <div className="advisor-current-status" aria-label="현재 학기 상담 상태">
            <span>{currentTerm.year}년 {currentTerm.semester}학기</span>
            <strong>{statusLabels[currentConsultationStatus]}</strong>
          </div>
        </article>

        <article className="card certificate-card">
          <div className="card-title">
            <div>
              <p className="eyebrow">자격증</p>
              <h3>현재 딴 자격증</h3>
            </div>
            <strong>3개</strong>
          </div>
          <ul className="tag-list">
            <li>GTQ 1급</li>
            <li>컴퓨터그래픽스운용기능사</li>
            <li>TOEIC Speaking IM3</li>
          </ul>
        </article>

        <article className="card activity-card">
          <div className="card-title">
            <div>
              <p className="eyebrow">활동</p>
              <h3>활동 목록</h3>
            </div>
            <strong>6건</strong>
          </div>
          <div className="activity-summary">
            <span>내부 활동 · 진행 중</span>
            <span>외부 활동 · 지원 완료</span>
          </div>
        </article>

        <article className="card credit-chart-card">
          <div className="card-title">
            <div>
              <p className="eyebrow">학기별 학점</p>
              <h3>최근 이수 현황</h3>
            </div>
            <span>평균 18.6학점</span>
          </div>
          <div className="credit-chart">
            {semesterCredits.map(([label, credit]) => (
              <div key={label}>
                <small>{label}</small>
                <strong>{credit}</strong>
              </div>
            ))}
          </div>
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
