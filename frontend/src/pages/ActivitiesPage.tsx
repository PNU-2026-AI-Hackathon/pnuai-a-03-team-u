import { ArrowUpRight, Flag, Flame, Hexagon, LayoutGrid, Users } from "lucide-react";
import { recommendedActivities as activities } from "../data/recommendedActivities";
import { useAuth } from "../auth/AuthContext";
import { readProfileOverrides } from "../data/studentProfileStorage";

const tags = ["# 데이터분석", "# AI", "# 바이오헬스", "# 인턴십", "# 포트폴리오", "# 교내활동"];

const categories = [
  [LayoutGrid, "전체 추천"],
  [ArrowUpRight, "역량 성장"],
  [Users, "소통 협력"],
  [Hexagon, "지식 탐구"],
  [Flag, "진로 설계"],
  [Flame, "학습 관리"],
] as const;


export function ActivitiesPage() {
  const { user } = useAuth();
  const displayName = readProfileOverrides()?.name ?? user?.name ?? "사용자";

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
            <input type="search" placeholder="로드맵, 자격증, 활동 검색" />
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
        {categories.map(([Icon, label], index) => (
          <article className={index === 0 ? "selected" : ""} key={label}>
            <span>
              <Icon size={22} aria-hidden="true" />
            </span>
            <strong>{label}</strong>
          </article>
        ))}
      </section>

      <section className="activity-results">
        <div className="activity-results-head">
          <div>
            <p className="eyebrow">추천 24개</p>
            <h2>{displayName} 님에게 맞춘 활동</h2>
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
              <div className="activity-card-top is-leading">
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
                  <span key={tag}># {tag}</span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}
