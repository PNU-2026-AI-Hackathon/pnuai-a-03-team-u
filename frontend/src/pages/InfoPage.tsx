const graduationRows = [
  ["전공기초", "18 / 18", "100%"],
  ["전공필수", "12 / 18", "67%"],
  ["전공선택", "33 / 42", "79%"],
  ["교양필수", "12 / 12", "100%"],
  ["교양선택", "15 / 18", "83%"],
];

const gradeTerms = [
  {
    term: "2026년 1학기",
    courses: ["데이터베이스", "자료구조", "선형대수", "웹프로그래밍", "교양 선택"],
  },
  {
    term: "2025년 2학기",
    courses: ["Python Programming", "확률및통계 II", "인공지능과 디지털 사고"],
  },
];

const activityItems = [
  ["Google DSC Core Member", "데이터 분석 스터디 운영, 팀 프로젝트 코드 리뷰, 세미나 발표를 진행했습니다.", "활동 기록 추가/보기"],
  ["SW+X 문제해결 경진대회", "바이오 데이터를 활용해 문제를 정의하고 분석 모델을 설계하는 팀 경진대회입니다.", "공고 링크 추가"],
  ["SQL 분석 미니 프로젝트", "수강 과목과 연계해 데이터베이스 설계, SQL 쿼리 분석, 시각화 결과물을 정리합니다.", "GitHub 링크 추가"],
];

export function InfoPage() {
  return (
    <section className="info-page">
      <section className="info-sync-panel">
        <div>
          <p className="eyebrow">Course Activity Sync</p>
          <h2>교과 활동 자동 편집</h2>
          <p>학번과 이름을 기준으로 수강 과목, 학점, 성적 같은 교과 활동만 불러옵니다.</p>
        </div>
        <div className="sync-form">
          <label>
            <span>학번</span>
            <input type="text" placeholder="예: 2023662247" />
          </label>
          <label>
            <span>이름</span>
            <input type="text" placeholder="예: 이도원" />
          </label>
          <button type="button">교과 활동 불러오기</button>
        </div>
        <p className="sync-note">수강 과목, 이수 학점, 학기별 성적, 전공/교양 이수 구분</p>
      </section>

      <section className="info-layout">
        <aside className="info-profile-card">
          <p className="eyebrow">Profile</p>
          <div className="student-photo">이</div>
          <h2>이도원</h2>
          <p>의생명융합공학부 · 데이터사이언스전공</p>
          <p>3학년 · 2026학년도 1학기 재학 중</p>
          <button type="button">편집하기</button>
          <button type="button">저장하기</button>
          <button type="button">자동 편집</button>
        </aside>

        <div className="info-content-stack">
          <article className="card info-section-card">
            <div className="card-title">
              <div>
                <p className="eyebrow">Graduation</p>
                <h3>졸업요건</h3>
              </div>
              <strong>112 / 130</strong>
            </div>
            <div className="graduation-list">
              {graduationRows.map(([label, credit, percent]) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>{credit}</strong>
                  <div className="stellic-bar">
                    <span className="earned" style={{ width: percent }} />
                  </div>
                </div>
              ))}
            </div>
          </article>

          <article className="card info-section-card">
            <div className="card-title">
              <div>
                <p className="eyebrow">Grades</p>
                <h3>학기별 성적</h3>
              </div>
            </div>
            <div className="grade-term-list">
              {gradeTerms.map((term) => (
                <section key={term.term}>
                  <h4>{term.term}</h4>
                  <ul>
                    {term.courses.map((course) => (
                      <li key={course}>{course}</li>
                    ))}
                  </ul>
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
              {activityItems.map(([title, description, link]) => (
                <article key={title}>
                  <h4>{title}</h4>
                  <div>
                    <span>기관명</span>
                    <strong>부산대학교</strong>
                  </div>
                  <div>
                    <span>설명</span>
                    <p>{description}</p>
                  </div>
                  <div>
                    <span>링크</span>
                    <a href="#evidence">{link}</a>
                  </div>
                </article>
              ))}
            </div>
          </article>

          <article className="card info-section-card">
            <div className="card-title">
              <div>
                <p className="eyebrow">Certificate</p>
                <h3>자격증</h3>
              </div>
            </div>
            <div className="tag-list">
              <li>GTQ 1급</li>
              <li>빅데이터분석기사 필기</li>
            </div>
          </article>

          <article className="card info-section-card">
            <div className="card-title">
              <div>
                <p className="eyebrow">Language</p>
                <h3>어학 성적</h3>
              </div>
            </div>
            <div className="tag-list">
              <li>TOEIC Speaking IM3</li>
              <li>OPIc IM2</li>
            </div>
          </article>
        </div>
      </section>
    </section>
  );
}
