import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { ArrowUp, Check, Plus, Search } from "lucide-react";
import {
  recommendTimetable,
  type TimetableRecommendation,
  type TimetableSection,
} from "../api/timetable";
import { chatWithRoadmapAgent, getCurrentRoadmap } from "../api/roadmaps";
import { getApiErrorMessage } from "../api/client";
import { BrandMark } from "../components/layout/BrandMark";

/** 시간표를 만들 대상 학기. 로드맵의 다음 학기를 본다. */
const TARGET_YEAR = "2026";
const TARGET_SEMESTER = "2학기";

const DAYS = ["월", "화", "수", "목", "금"];
const HOURS = [9, 10, 11, 12, 13, 14, 15, 16, 17];

const CATEGORY_FILTERS = [
  { key: "전필", match: "전공 필수" },
  { key: "전선", match: "전공 선택" },
  { key: "교양", match: "교양" },
];

const LEGEND = [
  { label: "전공 기초", tone: "base" },
  { label: "전공 필수", tone: "required" },
  { label: "전공 선택", tone: "elective" },
  { label: "일반 선택", tone: "general" },
  { label: "교양", tone: "liberal" },
];

const QUICK_PROMPTS = ["공강 만들기", "오전 수업 줄이기", "졸업요건 우선"];

type ChatEntry = { key: string; role: "user" | "assistant"; content: string };

/** 카테고리 문자열을 시안의 색상 토큰에 맞춘다. */
function categoryTone(category: string | null) {
  if (!category) return "general";
  if (category.includes("기초")) return "base";
  if (category.includes("필수")) return "required";
  if (category.includes("교양")) return "liberal";
  if (category.includes("선택") && category.includes("전공")) return "elective";
  return "general";
}

function toMinutes(value: string | null) {
  if (!value) return null;
  const [hour, minute] = value.split(":").map(Number);
  if (Number.isNaN(hour) || Number.isNaN(minute)) return null;
  return hour * 60 + minute;
}

/** 한 과목의 요약 줄. "전공 필수 3학점 · 월 10:00-11:15 · 김태완 교수" */
function sectionSummary(section: TimetableSection) {
  const slot = section.times.find((time) => time.day_of_week && time.start_time);
  return [
    [section.category, section.credits ? `${section.credits}학점` : null].filter(Boolean).join(" "),
    slot ? `${slot.day_of_week} ${slot.start_time}-${slot.end_time}` : null,
    section.professor ? `${section.professor} 교수` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function TimetablePage() {
  const [roadmapId, setRoadmapId] = useState<number | null>(null);
  const [data, setData] = useState<TimetableRecommendation | null>(null);
  const [scheduleIndex, setScheduleIndex] = useState(0);
  const [excludedIds, setExcludedIds] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  const [chat, setChat] = useState<ChatEntry[]>([]);
  const [prompt, setPrompt] = useState("");
  const [isSending, setIsSending] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const roadmap = await getCurrentRoadmap();
        const result = await recommendTimetable(roadmap.id, TARGET_YEAR, TARGET_SEMESTER);
        if (cancelled) return;
        setRoadmapId(roadmap.id);
        setData(result);
      } catch (caught) {
        if (!cancelled) setError(getApiErrorMessage(caught, "시간표 후보를 불러오지 못했습니다."));
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const candidates = useMemo(() => {
    if (!data) return [];
    return [...data.feasible_schedules, ...data.partial_schedules];
  }, [data]);

  const schedule = candidates[scheduleIndex] ?? null;
  const sections = schedule?.sections ?? [];
  const placedSections = sections.filter((section) => !excludedIds.has(section.item_id));

  const totalCredits = placedSections.reduce((sum, section) => sum + (section.credits ?? 0), 0);
  const conflictCount = data?.problematic_courses.length ?? 0;

  const visibleSections = sections.filter((section) => {
    const keyword = search.trim();
    if (keyword && !`${section.course_name ?? ""}${section.professor ?? ""}`.includes(keyword)) {
      return false;
    }
    if (activeFilter) {
      const filter = CATEGORY_FILTERS.find((item) => item.key === activeFilter);
      if (filter && !(section.category ?? "").includes(filter.match)) return false;
    }
    return true;
  });

  function toggleSection(itemId: number) {
    setExcludedIds((current) => {
      const next = new Set(current);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }

  async function sendPrompt(text: string) {
    const message = text.trim();
    if (!message || roadmapId === null || isSending) return;

    setPrompt("");
    setIsSending(true);
    setChat((current) => [...current, { key: `u-${current.length}`, role: "user", content: message }]);
    try {
      const response = await chatWithRoadmapAgent(roadmapId, message);
      setChat((current) => [
        ...current,
        { key: `a-${current.length}`, role: "assistant", content: response.reply },
      ]);
    } catch (caught) {
      setChat((current) => [
        ...current,
        {
          key: `a-${current.length}`,
          role: "assistant",
          content: getApiErrorMessage(caught, "답변을 받지 못했습니다. 잠시 후 다시 시도해 주세요."),
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void sendPrompt(prompt);
  }

  /** 요일·시각에 걸린 블록을 grid-row로 배치한다. */
  const blocks = placedSections.flatMap((section) =>
    section.times.flatMap((time) => {
      const dayIndex = DAYS.indexOf(time.day_of_week ?? "");
      const start = toMinutes(time.start_time);
      const end = toMinutes(time.end_time);
      if (dayIndex < 0 || start === null || end === null) return [];
      const startRow = (start - HOURS[0] * 60) / 60;
      const span = Math.max((end - start) / 60, 0.5);
      return [
        {
          key: `${section.item_id}-${time.day_of_week}-${time.start_time}`,
          name: section.course_name ?? "과목",
          classroom: time.classroom,
          tone: categoryTone(section.category),
          dayIndex,
          startRow,
          span,
        },
      ];
    }),
  );

  return (
    <section className="timetable-page">
      <header className="timetable-head">
        <div>
          <p className="eyebrow">시간표</p>
          <h2>
            {TARGET_YEAR}-{TARGET_SEMESTER.replace("학기", "")} 시간표{" "}
            {String.fromCharCode(65 + scheduleIndex)}
          </h2>
          <p>로드맵의 다음 학기 계획 과목을 기준으로 시간표 후보를 만듭니다.</p>
        </div>
        <div className="timetable-head-actions">
          <label className="timetable-select">
            <span className="sr-only">시간표 후보 선택</span>
            <select
              value={scheduleIndex}
              onChange={(event) => {
                setScheduleIndex(Number(event.target.value));
                setExcludedIds(new Set());
              }}
              disabled={candidates.length === 0}
            >
              {candidates.length === 0 ? (
                <option value={0}>후보 없음</option>
              ) : (
                candidates.map((candidate, index) => (
                  <option key={index} value={index}>
                    시간표 {String.fromCharCode(65 + index)} · {candidate.total_credits}학점
                  </option>
                ))
              )}
            </select>
          </label>
          <button type="button" className="timetable-save" disabled title="시간표 저장 API가 아직 없습니다">
            저장
          </button>
        </div>
      </header>

      {error ? (
        <p className="timetable-error" role="alert">
          {error}
        </p>
      ) : null}
      {!error && !isLoading && candidates.length === 0 ? (
        <p className="timetable-error">
          {data?.note ?? "이 학기에 배치할 로드맵 과목이 없어 시간표 후보를 만들지 못했습니다."}
        </p>
      ) : null}

      <div className="timetable-columns">
        <section className="timetable-panel">
          <h3>과목 추가</h3>
          <label className="timetable-search">
            <Search size={18} aria-hidden="true" />
            <input
              type="search"
              placeholder="과목명, 교수명 검색"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>

          <div className="timetable-filters">
            {CATEGORY_FILTERS.map((filter) => (
              <button
                key={filter.key}
                type="button"
                className={activeFilter === filter.key ? "selected" : ""}
                onClick={() => setActiveFilter((current) => (current === filter.key ? null : filter.key))}
              >
                {filter.key}
              </button>
            ))}
          </div>

          <ul className="timetable-course-list">
            {isLoading ? <li className="timetable-empty">불러오는 중입니다…</li> : null}
            {!isLoading && visibleSections.length === 0 ? (
              <li className="timetable-empty">표시할 과목이 없습니다.</li>
            ) : null}

            {visibleSections.map((section) => {
              const placed = !excludedIds.has(section.item_id);
              return (
                <li className="timetable-course" key={section.item_id}>
                  <div>
                    <strong>{section.course_name ?? "과목"}</strong>
                    <p>{sectionSummary(section)}</p>
                  </div>
                  <button
                    type="button"
                    className={placed ? "is-placed" : ""}
                    onClick={() => toggleSection(section.item_id)}
                  >
                    {placed ? <Check size={14} aria-hidden="true" /> : <Plus size={14} aria-hidden="true" />}
                    {placed ? "담기 완료" : "담기"}
                  </button>
                </li>
              );
            })}

            {data?.problematic_courses.map((course) => (
              <li className="timetable-course is-conflict" key={`conflict-${course.item_id}`}>
                <div>
                  <strong>{course.course_name ?? `항목 ${course.item_id}`}</strong>
                  <p>{course.reason ?? "다른 과목과 시간이 겹칩니다"}</p>
                </div>
                <span className="timetable-conflict-badge">충돌</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="timetable-panel">
          <div className="timetable-grid-head">
            <h3>주간 시간표</h3>
            <span className="timetable-badge">담은 학점 {totalCredits}</span>
            {conflictCount > 0 ? (
              <span className="timetable-badge is-warn">시간 충돌 {conflictCount}</span>
            ) : null}
          </div>
          <p className="timetable-hint">담기 버튼으로 과목을 넣고 빼면서 후보를 비교하세요</p>

          <div className="timetable-grid">
            <div className="timetable-grid-corner" />
            {DAYS.map((day) => (
              <div className="timetable-grid-day" key={day}>
                {day}
              </div>
            ))}

            {HOURS.map((hour, index) => (
              <div className="timetable-grid-hour" key={hour} style={{ gridRow: index + 2 }}>
                {hour}
              </div>
            ))}

            {HOURS.map((hour, rowIndex) =>
              DAYS.map((day, colIndex) => (
                <div
                  className="timetable-grid-cell"
                  key={`${day}-${hour}`}
                  style={{ gridRow: rowIndex + 2, gridColumn: colIndex + 2 }}
                />
              )),
            )}

            {blocks.map((block) => (
              <div
                className={`timetable-block tone-${block.tone}`}
                key={block.key}
                style={{
                  gridColumn: block.dayIndex + 2,
                  gridRow: `${Math.floor(block.startRow) + 2} / span ${Math.max(Math.round(block.span), 1)}`,
                }}
              >
                <strong>{block.name}</strong>
                {block.classroom ? <span>{block.classroom}</span> : null}
              </div>
            ))}
          </div>

          <ul className="timetable-legend">
            {LEGEND.map((item) => (
              <li key={item.label}>
                <span className={`legend-dot tone-${item.tone}`} aria-hidden="true" />
                {item.label}
              </li>
            ))}
          </ul>
        </section>

        <section className="timetable-panel timetable-ai">
          <header>
            <span className="timetable-ai-face">
              <BrandMark id="plan-u-face-timetable" />
            </span>
            <div>
              <h3>AI와 같이 시간표 짜기</h3>
              <p>담은 과목과 남은 학점으로 시간표를 작성합니다.</p>
            </div>
          </header>

          <div className="timetable-chat" aria-live="polite">
            {chat.length === 0 ? (
              <p className="timetable-empty">
                남은 요건이나 원하는 조건을 말하면 로드맵 기준으로 답해드립니다.
              </p>
            ) : (
              chat.map((entry) => (
                <div className={`timetable-chat-row ${entry.role}`} key={entry.key}>
                  <span className="timetable-chat-who">{entry.role === "user" ? "나" : "AI"}</span>
                  <p>{entry.content}</p>
                </div>
              ))
            )}
            {isSending ? <p className="timetable-empty">답변을 작성하고 있습니다…</p> : null}
          </div>

          <div className="timetable-quick">
            {QUICK_PROMPTS.map((item) => (
              <button key={item} type="button" onClick={() => void sendPrompt(item)} disabled={isSending}>
                {item}
              </button>
            ))}
          </div>

          <form className="timetable-composer" onSubmit={handleSubmit}>
            <input
              aria-label="AI에게 메시지 보내기"
              placeholder="예 : 남은 요건으로 시간표 짜줘"
              value={prompt}
              disabled={roadmapId === null || isSending}
              onChange={(event) => setPrompt(event.target.value)}
            />
            <button type="submit" aria-label="메시지 전송" disabled={!prompt.trim() || isSending}>
              <ArrowUp size={18} aria-hidden="true" />
            </button>
          </form>
        </section>
      </div>
    </section>
  );
}
