const tags = ["# 데이터분석", "# AI", "# 바이오헬스", "# SW", "# 공모전", "# 인턴십", "# 포트폴리오", "# 교내활동"];

const categories = [
  ["▦", "전체추천"],
  ["↗", "역량성장"],
  ["◫", "소통협력"],
  ["◎", "지식탐구"],
  ["⚑", "진로설계"],
  ["✺", "학습관리"],
];

const activities = [
  {
    dDay: "D-2",
    title: "SW+X 문제해결 경진대회",
    description: "실험 데이터를 분석해 문제를 해결하는 팀 챌린지",
    category: "공모전",
    reason: "데이터사이언스전공과 바이오헬스 관심 분야가 함께 반영됐어요.",
    tags: ["AI", "데이터분석", "팀프로젝트"],
  },
  {
    dDay: "D-5",
    title: "맞춤형 학습컨설팅",
    description: "전공 과목 학습 전략과 시간표 균형을 점검합니다",
    category: "교내활동",
    reason: "이번 학기 18학점 수강 계획과 전공 필수 과목 관리에 잘 맞아요.",
    tags: ["학습관리", "전공필수"],
  },
  {
    dDay: "D-7",
    title: "2026학년도 심리기술훈련 2차",
    description: "발표, 팀 프로젝트, 시험 기간 스트레스를 다룹니다",
    category: "비교과",
    reason: "캡스톤과 공모전 준비가 겹치는 학기 부담을 낮추는 활동이에요.",
    tags: ["멘탈관리", "발표"],
  },
  {
    dDay: "D-12",
    title: "바이오헬스 데이터 분석 인턴",
    description: "의생명 데이터 정제와 대시보드 제작 실무",
    category: "인턴십",
    reason: "전공 선택 과목과 포트폴리오를 동시에 강화할 수 있어요.",
    tags: ["인턴십", "바이오헬스", "Python"],
  },
  {
    dDay: "D-18",
    title: "데이터 포트폴리오 클리닉",
    description: "분석 프로젝트를 이력서용 결과물로 정리합니다",
    category: "진로설계",
    reason: "로드맵의 머신러닝, 데이터시각화 과목과 연결하기 좋아요.",
    tags: ["포트폴리오", "진로"],
  },
  {
    dDay: "D-21",
    title: "데이터사이언스 러닝서클",
    description: "데이터사이언스 스터디와 코드 리뷰 모임",
    category: "스터디",
    reason: "학기 중 전공 선택 과목을 꾸준히 따라가기 위한 보조 활동이에요.",
    tags: ["스터디", "알고리즘", "협업"],
  },
];

export function ActivitiesPage() {
  return (
    <section className="activity-page">
      <section className="activity-filter-panel" aria-label="추천 활동 검색">
        <div className="activity-breadcrumb">Home 〉 비교과활동 〉 개인별 추천</div>
        <div className="activity-filter-row">
          <button type="button">
            접수상태전체 <span>⌄</span>
          </button>
          <label>
            <span>⌕</span>
            <input type="search" placeholder="검색어를 입력하세요" />
          </label>
          <button type="button" className="detail-search">
            상세검색
          </button>
        </div>
        <div className="activity-tags" aria-label="추천 태그">
          {tags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
      </section>

      <section className="activity-category-strip" aria-label="활동 카테고리">
        {categories.map(([icon, label], index) => (
          <article className={index === 0 ? "selected" : ""} key={label}>
            <span>{icon}</span>
            <strong>{label}</strong>
          </article>
        ))}
      </section>

      <section className="activity-results">
        <div className="activity-results-head">
          <div>
            <p className="eyebrow">추천 24개</p>
            <h2>이도원 님에게 맞춘 활동</h2>
          </div>
          <div className="sort-tabs">
            <button className="selected" type="button">
              마감임박순
            </button>
            <button type="button">인기순</button>
            <button type="button">최신순</button>
          </div>
        </div>

        <div className="activity-grid">
          {activities.map((activity) => (
            <article className="activity-recommend-card" key={activity.title}>
              <div className="activity-card-top">
                <span className="deadline-pill">{activity.dDay}</span>
                <span className="activity-kind">{activity.category}</span>
              </div>
              <h3>{activity.title}</h3>
              <p>{activity.description}</p>
              <div className="recommend-reason">
                <strong>AI</strong>
                <span>{activity.reason}</span>
              </div>
              <div className="activity-card-tags">
                {activity.tags.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}
