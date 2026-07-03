import { useState } from "react";
import type { FormEvent } from "react";

const requirementCards = [
  ["전공 기초", "데이터베이스 3학점 수강 중"],
  ["전공 필수", "캡스톤, 머신러닝 남음"],
  ["전공 선택", "바이오데이터분석 추천"],
  ["교양 필수", "요건 충족 완료"],
  ["교양 선택", "3학점 추가 이수 필요"],
];

const timeline: Array<[string, string[]]> = [
  ["3학년 1학기", ["데이터베이스", "자료구조", "웹프로그래밍"]],
  ["여름방학", ["빅데이터분석기사 필기", "포트폴리오 클리닉"]],
  ["3학년 2학기", ["머신러닝", "바이오데이터분석", "교양 선택"]],
  ["4학년 1학기", ["캡스톤디자인", "인턴십", "졸업요건 최종 점검"]],
];

export function RoadmapPage() {
  const [messages, setMessages] = useState([
    ["AI", "현재 전공 필수 6학점, 교양 선택 3학점, 일반 선택 3학점이 핵심으로 남아 있어요."],
    ["나", "전공 필수부터 채우는 계획으로 바꿔줘."],
    ["AI", "좋아요. 머신러닝과 캡스톤을 우선 배치하고, 교양 선택은 부담 낮은 학기에 넣겠습니다."],
  ]);
  const [prompt, setPrompt] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = prompt.trim();
    if (!value) return;
    setMessages((current) => [
      ...current,
      ["나", value],
      ["AI", "중간보고용 목업 응답입니다. 다음 단계에서 로드맵 API와 연결할 예정이에요."],
    ]);
    setPrompt("");
  }

  return (
    <section className="roadmap-shell" data-current-tab="semester">
      <section className="roadmap-head">
        <div>
          <p className="eyebrow">남은 요건</p>
          <h2>데이터사이언스전공 로드맵</h2>
          <p>졸업 요건, 전공 심화, 진로 준비를 한 화면에서 추적합니다.</p>
        </div>
        <div className="roadmap-score">
          <span>완료율 72%</span>
          <strong>남은 학점 18</strong>
          <small>2026-1 적용</small>
        </div>
      </section>

      <div className="roadmap-tabs">
        <button className="selected" type="button">
          학기별
        </button>
        <button type="button">요건별</button>
        <button type="button">학과 이수체계도</button>
      </div>

      <section className="roadmap-layout tab-panel active" data-panel="semester">
        <div className="roadmap-main">
          <section className="requirement-strip" aria-label="전공/교양 이수 요건">
            {requirementCards.map(([title, description]) => (
              <article key={title}>
                <span>✓</span>
                <h3>{title}</h3>
                <p>{description}</p>
              </article>
            ))}
          </section>

          <section className="semester-timeline">
            {timeline.map(([term, items]) => (
              <article key={term}>
                <h3>{term}</h3>
                <ul>
                  {items.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </article>
            ))}
          </section>
        </div>

        <aside className="ai-roadmap-panel">
          <div>
            <p className="eyebrow">AI와 같이 요건 맞추기</p>
            <h3>AI와 같이 로드맵 짜기</h3>
            <p>남은 요건과 과목 후보를 보면서 바로 조정합니다.</p>
          </div>
          <div className="chat-log">
            {messages.map(([speaker, text], index) => (
              <div className={speaker === "AI" ? "ai-message" : "user-message"} key={`${speaker}-${index}`}>
                <strong>{speaker}</strong>
                <p>{text}</p>
              </div>
            ))}
          </div>
          <div className="quick-prompts">
            <button type="button">남은 요건 정리</button>
            <button type="button">필수 먼저</button>
            <button type="button">교양 추천</button>
          </div>
          <form className="ai-input" onSubmit={handleSubmit}>
            <input value={prompt} onChange={(event) => setPrompt(event.target.value)} type="text" placeholder="예: 다음 학기 6과목 추천해줘" />
            <button type="submit">↑</button>
          </form>
        </aside>
      </section>
    </section>
  );
}
