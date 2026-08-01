import { recommendedActivities as activities } from "../data/recommendedActivities";

const tags = ["# 데이터분석", "# AI", "# 바이오헬스", "# SW", "# 공모전", "# 인턴십", "# 포트폴리오", "# 교내활동"];

const categories = [
  ["▦", "전체추천"],
  ["↗", "역량성장"],
  ["◫", "소통협력"],
  ["◎", "지식탐구"],
  ["⚑", "진로설계"],
  ["✺", "학습관리"],
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
