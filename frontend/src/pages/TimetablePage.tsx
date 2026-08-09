import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { ArrowUp, Check, Plus, Search } from "lucide-react";
import {
  applyTimetableToRoadmap,
  chatWithTimetableAgent,
  recommendTimetable,
  searchOfferings,
  type SuggestedOffering,
  type TimetableApplyResult,
  type TimetableChatSuggestion,
  type TimetableChatTurn,
  type TimetableRecommendation,
} from "../api/timetable";
import { getCurrentRoadmap } from "../api/roadmaps";
import { searchDepartments } from "../api/departments";
import type { DepartmentSearchResult } from "../api/departments";
import { getApiErrorMessage } from "../api/client";
import { BrandMark } from "../components/layout/BrandMark";
import { useAuth } from "../auth/AuthContext";

/** 시간표를 만들 대상 학기. 로드맵의 다음 학기를 본다. */
const TARGET_YEAR = "2026";
const TARGET_SEMESTER = "2학기";

const DAYS = ["월", "화", "수", "목", "금"];
/**
 * 격자 한 칸의 크기(분).
 *
 * 부산대 수업은 대부분 75분(9:00~10:15)이라 1시간 칸에는 안 맞는다. 100분·50분
 * 수업도 있어서 15분 칸으로도 부족하다. 5분으로 잡으면 실제 수강편람의 모든
 * 수업이 정확히 떨어진다(어긋나는 행 0건 확인).
 */
const SLOT_MINUTES = 5;
const SLOTS_PER_HOUR = 60 / SLOT_MINUTES;

const DEFAULT_GRID_START = 9 * 60;
const DEFAULT_GRID_END = 18 * 60;

/**
 * 과목을 고르는 첫 갈래.
 *
 * 화면의 한 갈래가 DB 이수구분 여러 개에 걸쳐 있어서 categories를 배열로 둔다
 * (효원 균형·창의 교양이 그렇다). "전공"만 단과대 → 학부 → 전공으로 한 번 더
 * 좁히고, 교양 계열은 학부와 무관하게 전교 개설이라 바로 목록을 보여준다.
 */
const COURSE_GROUPS = [
  { key: "balance", label: "효원(균형·창의)교양", categories: ["효원균형교양", "효원창의교양"] },
  { key: "general", label: "일반선택", categories: ["일반선택"] },
  { key: "core", label: "효원핵심교양", categories: ["효원핵심교양"] },
  { key: "major", label: "전공", categories: ["전공"] },
] as const;

type CourseGroupKey = (typeof COURSE_GROUPS)[number]["key"];

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

/** 분반 한 줄 요약. "전공 필수 3학점 · 월 10:00-11:15 · 김태완 교수" */
function offeringSummary(offering: SuggestedOffering) {
  const slot = offering.times.find((time) => time.day_of_week && time.start_time);
  return [
    [offering.category, offering.credits ? `${offering.credits}학점` : null].filter(Boolean).join(" "),
    slot ? `${slot.day_of_week} ${slot.start_time}-${slot.end_time}` : null,
    offering.professor ? `${offering.professor} 교수` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function TimetablePage() {
  const { user } = useAuth();
  const [data, setData] = useState<TimetableRecommendation | null>(null);
  const [scheduleIndex, setScheduleIndex] = useState(0);
  const [excludedIds, setExcludedIds] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  const [chat, setChat] = useState<ChatEntry[]>([]);
  const [prompt, setPrompt] = useState("");
  const [isSending, setIsSending] = useState(false);

  /**
   * AI가 마지막으로 제안한 시간표와 사용자가 체크한 분반.
   *
   * 에이전트는 DB를 쓰지 않는다 — 여기서 사용자가 고르고 승인 버튼을 눌러야
   * 비로소 로드맵에 반영된다(로드맵 챗의 "선택 승인"과 같은 구조).
   */
  const [roadmapId, setRoadmapId] = useState<number | null>(null);
  const [suggestion, setSuggestion] = useState<TimetableChatSuggestion | null>(null);
  const [selectedOfferingIds, setSelectedOfferingIds] = useState<Set<number>>(new Set());
  const [isApplying, setIsApplying] = useState(false);
  const [applyResult, setApplyResult] = useState<TimetableApplyResult | null>(null);
  const [applyError, setApplyError] = useState("");
  /**
   * "과목 추가" 검색 상태.
   *
   * 예전에는 로드맵에 이미 담긴 과목에서 파생된 목록만 보여줘서, 계획에 없는
   * 과목은 아예 고를 수 없었다. 이제 개설 강좌를 학부/전공으로 직접 찾는다.
   */
  const [groupKey, setGroupKey] = useState<CourseGroupKey>("major");
  const [departments, setDepartments] = useState<DepartmentSearchResult[]>([]);
  const [selectedCollege, setSelectedCollege] = useState<string>("");
  const [selectedDepartment, setSelectedDepartment] = useState<DepartmentSearchResult | null>(null);
  const [selectedMajor, setSelectedMajor] = useState<string>("");
  const [offerings, setOfferings] = useState<SuggestedOffering[]>([]);
  const [isSearchingOfferings, setIsSearchingOfferings] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const roadmap = await getCurrentRoadmap();
        const result = await recommendTimetable(roadmap.id, TARGET_YEAR, TARGET_SEMESTER);
        if (cancelled) return;
        // 상담 자체는 로드맵 없이도 되지만, 승인 결과를 반영할 곳은 로드맵이다.
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

  // 학부 목록은 한 번만 통째로 받아 드롭다운에 채운다(정식 편제 110여 개).
  // 다른 학부 과목도 담을 수 있어야 해서 내 학적으로 좁히지 않는다.
  useEffect(() => {
    let cancelled = false;
    void searchDepartments("", 300)
      .then((list) => {
        if (cancelled) return;
        setDepartments(list);
        // 처음에는 내 학부와 그 단과대를 골라둔다. 대부분 자기 학부부터 본다.
        const mine = list.find((item) => item.name === user?.department) ?? null;
        setSelectedDepartment((current) => current ?? mine);
        setSelectedCollege((current) => current || (mine?.college ?? ""));
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, [user?.department]);

  // 고른 갈래(+전공이면 학부·전공)와 키워드로 개설 강좌를 찾는다.
  useEffect(() => {
    let cancelled = false;
    setIsSearchingOfferings(true);
    const group = COURSE_GROUPS.find((item) => item.key === groupKey);
    // 교양·일반선택은 전교 개설이라 학부로 좁히면 오히려 결과가 사라진다.
    const isMajor = groupKey === "major";
    const timer = window.setTimeout(() => {
      void searchOfferings({
        year: TARGET_YEAR,
        semester: TARGET_SEMESTER,
        departmentId: isMajor ? selectedDepartment?.id ?? null : null,
        major: isMajor ? selectedMajor || null : null,
        categories: group ? [...group.categories] : undefined,
        q: search.trim(),
        limit: 60,
      })
        .then((list) => {
          if (!cancelled) setOfferings(list);
        })
        .catch(() => {
          if (!cancelled) setOfferings([]);
        })
        .finally(() => {
          if (!cancelled) setIsSearchingOfferings(false);
        });
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [groupKey, selectedDepartment, selectedMajor, search]);

  /** 학부를 가진 단과대만. "미지정"은 잘못 생성된 껍데기라 서버가 이미 걸러준다. */
  const colleges = [...new Set(departments.map((item) => item.college))].sort();
  const collegeDepartments = departments.filter((item) => item.college === selectedCollege);

  const candidates = useMemo(() => {
    if (!data) return [];
    return [...data.feasible_schedules, ...data.partial_schedules];
  }, [data]);

  const schedule = candidates[scheduleIndex] ?? null;
  const sections = schedule?.sections ?? [];
  const placedSections = sections.filter((section) => !excludedIds.has(section.item_id));

  const allPlaced = placedSections;
  const totalCredits = allPlaced.reduce((sum, section) => sum + (section.credits ?? 0), 0);
  const conflictCount = data?.problematic_courses.length ?? 0;

  /**
   * 이미 시간표에 들어가 있는 분반. "과목 추가" 목록에서 담기 완료 표시에 쓴다.
   * AI 추천으로 담은 과목도 저장되고 나면 여기에 잡힌다.
   */
  const placedOfferingIds = new Set(
    allPlaced.map((section) => section.offering_id).filter((id): id is number => id !== null),
  );

  async function sendPrompt(text: string) {
    const message = text.trim();
    if (!message || isSending) return;

    // 서버가 대화를 저장하지 않으므로 지금까지의 대화를 그대로 넘겨준다.
    const history: TimetableChatTurn[] = chat.map((entry) => ({
      role: entry.role,
      content: entry.content,
    }));

    setPrompt("");
    setIsSending(true);
    setChat((current) => [...current, { key: `u-${current.length}`, role: "user", content: message }]);
    try {
      const response = await chatWithTimetableAgent(
        TARGET_YEAR,
        TARGET_SEMESTER,
        message,
        history,
      );
      setChat((current) => [
        ...current,
        { key: `a-${current.length}`, role: "assistant", content: response.reply },
      ]);
      // 화면에 그릴 수 있는 분반이 실린 제안만 승인 카드로 띄운다.
      const next = response.schedules.find((item) => item.offerings.length > 0) ?? null;
      setSuggestion(next);
      setSelectedOfferingIds(new Set(next?.offerings.map((o) => o.offering_id) ?? []));
      setApplyResult(null);
      setApplyError("");
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

  function toggleOffering(offeringId: number) {
    setSelectedOfferingIds((current) => {
      const next = new Set(current);
      if (next.has(offeringId)) next.delete(offeringId);
      else next.add(offeringId);
      return next;
    });
  }

  /**
   * 고른 분반을 시간표에 담는다. 누르는 즉시 로드맵에 저장된다.
   *
   * 따로 "저장"을 누르게 하면 담아 놓고 저장을 안 한 채 화면을 떠나는 일이
   * 생긴다. 대신 AI 추천은 체크박스로 무엇을 담을지 먼저 고르게 해서, 추천이
   * 곧바로 로드맵을 바꾸지는 않는다.
   */
  async function addOfferings(offeringIds: number[]) {
    if (roadmapId === null || isApplying || offeringIds.length === 0) return;
    setIsApplying(true);
    setApplyError("");
    try {
      const result = await applyTimetableToRoadmap(
        roadmapId,
        TARGET_YEAR,
        TARGET_SEMESTER,
        offeringIds,
      );
      setApplyResult(result);
      // 담은 과목이 주간 시간표에 바로 나타나야 한다. 후보는 로드맵 항목에서
      // 계산되므로 다시 불러온다.
      const refreshed = await recommendTimetable(roadmapId, TARGET_YEAR, TARGET_SEMESTER);
      setData(refreshed);
      setScheduleIndex(0);
      setExcludedIds(new Set());
    } catch (caught) {
      setApplyError(getApiErrorMessage(caught, "과목을 담지 못했습니다."));
    } finally {
      setIsApplying(false);
    }
  }

  async function acceptSuggestion() {
    if (!suggestion || selectedOfferingIds.size === 0) return;
    const picked = [...selectedOfferingIds];
    setSuggestion(null);
    setSelectedOfferingIds(new Set());
    await addOfferings(picked);
  }

  function dismissSuggestion() {
    setSuggestion(null);
    setSelectedOfferingIds(new Set());
  }

  const selectedCredits = (suggestion?.offerings ?? [])
    .filter((offering) => selectedOfferingIds.has(offering.offering_id))
    .reduce((sum, offering) => sum + (offering.credits ?? 0), 0);

  /** 담은 수업의 (요일, 시작분, 종료분). 격자 범위와 블록 배치가 같이 쓴다. */
  const placedTimes = allPlaced.flatMap((section) =>
    section.times.flatMap((time) => {
      const dayIndex = DAYS.indexOf(time.day_of_week ?? "");
      const start = toMinutes(time.start_time);
      const end = toMinutes(time.end_time);
      if (dayIndex < 0 || start === null || end === null || end <= start) return [];
      return [{ section, time, dayIndex, start, end }];
    }),
  );

  /**
   * 격자에 그릴 시간 범위.
   *
   * 기본은 9~18시지만, 담은 수업이 그 밖으로 나가면 시간 단위로 넓힌다.
   * 부산대는 8시 수업도 있고 야간 강의는 23시에 끝나기도 해서, 고정 범위로
   * 두면 블록이 잘려 나간다.
   */
  const gridStart = placedTimes.reduce(
    (earliest, item) => Math.min(earliest, Math.floor(item.start / 60) * 60),
    DEFAULT_GRID_START,
  );
  const gridEnd = placedTimes.reduce(
    (latest, item) => Math.max(latest, Math.ceil(item.end / 60) * 60),
    DEFAULT_GRID_END,
  );
  const hours = Array.from(
    { length: (gridEnd - gridStart) / 60 },
    (_, index) => gridStart / 60 + index,
  );

  /** 분 단위 시각을 grid-row 번호로. 1행은 요일 머리글이라 +2. */
  const toGridRow = (minutes: number) => (minutes - gridStart) / SLOT_MINUTES + 2;

  const blocks = placedTimes.map(({ section, time, dayIndex, start, end }) => ({
    key: `${section.item_id}-${time.day_of_week}-${time.start_time}`,
    name: section.course_name ?? "과목",
    classroom: time.classroom,
    tone: categoryTone(section.category),
    dayIndex,
    rowStart: toGridRow(start),
    rowSpan: (end - start) / SLOT_MINUTES,
  }));

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
          {/* 담기 버튼이 곧바로 저장하므로 별도 "저장" 버튼은 두지 않는다. */}
          {isApplying ? <span className="timetable-saving">담는 중…</span> : null}
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

          {/* 학부·전공으로 개설 강좌를 좁힌다. 내 학적에 묶여 있지 않아 다른 학부
              과목도 담을 수 있다. */}
          {/* 1단계: 교양 계열인지 전공인지. 교양은 전교 개설이라 여기서 끝난다. */}
          <div className="timetable-filters">
            {COURSE_GROUPS.map((group) => (
              <button
                key={group.key}
                type="button"
                className={groupKey === group.key ? "selected" : ""}
                onClick={() => setGroupKey(group.key)}
              >
                {group.label}
              </button>
            ))}
          </div>

          {/* 2단계: 전공을 골랐을 때만 단과대 → 학부 → 전공으로 좁힌다. */}
          {groupKey === "major" ? (
            <div className="timetable-scope">
              <label>
                <select
                  aria-label="단과대 선택"
                  value={selectedCollege}
                  onChange={(event) => {
                    setSelectedCollege(event.target.value);
                    // 단과대가 바뀌면 아래 두 단계는 다시 골라야 한다.
                    setSelectedDepartment(null);
                    setSelectedMajor("");
                  }}
                >
                  <option value="">단과대 선택</option>
                  {colleges.map((college) => (
                    <option key={college} value={college}>
                      {college}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <select
                  aria-label="학부 선택"
                  value={selectedDepartment?.id ?? ""}
                  disabled={!selectedCollege}
                  onChange={(event) => {
                    const next = collegeDepartments.find(
                      (item) => item.id === Number(event.target.value),
                    );
                    setSelectedDepartment(next ?? null);
                    setSelectedMajor(""); // 학부가 바뀌면 이전 전공은 맞지 않는다
                  }}
                >
                  <option value="">{selectedCollege ? "학부 전체" : "단과대를 먼저"}</option>
                  {collegeDepartments.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <select
                  aria-label="전공 선택"
                  value={selectedMajor}
                  onChange={(event) => setSelectedMajor(event.target.value)}
                  disabled={!selectedDepartment || selectedDepartment.majors.length === 0}
                >
                  <option value="">
                    {selectedDepartment && selectedDepartment.majors.length > 0
                      ? "전공 전체"
                      : "세부전공 없음"}
                  </option>
                  {(selectedDepartment?.majors ?? []).map((major) => (
                    <option key={major} value={major}>
                      {major}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          ) : null}

          <ul className="timetable-course-list">
            {isSearchingOfferings ? <li className="timetable-empty">불러오는 중입니다…</li> : null}
            {!isSearchingOfferings && offerings.length === 0 ? (
              <li className="timetable-empty">이 조건으로 개설된 과목이 없습니다.</li>
            ) : null}

            {offerings.map((offering) => {
              const placed = placedOfferingIds.has(offering.offering_id);
              return (
                <li className="timetable-course" key={offering.offering_id}>
                  <div>
                    <strong>{offering.course_name ?? "과목"}</strong>
                    <p>{offeringSummary(offering)}</p>
                  </div>
                  <button
                    type="button"
                    className={placed ? "is-placed" : ""}
                    disabled={placed || isApplying || roadmapId === null}
                    onClick={() => void addOfferings([offering.offering_id])}
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
          {/* 담은 과목은 있는데 그릴 블록이 하나도 없으면 화면이 고장난 것처럼 보인다.
              수강편람 크롤링이 아직 요일·시각을 못 채운 분반이 많아서 생기는 일이다. */}
          {allPlaced.length > 0 && blocks.length === 0 ? (
            <p className="timetable-hint is-warn">
              담은 {allPlaced.length}과목 모두 수강편람에 요일·시각 정보가 없어 시간표에
              표시할 수 없습니다. 학점 합계와 과목 목록은 정상입니다.
            </p>
          ) : null}

          <div className="timetable-grid">
            <div className="timetable-grid-corner" />
            {DAYS.map((day) => (
              <div className="timetable-grid-day" key={day}>
                {day}
              </div>
            ))}

            {/* 시각 라벨과 배경 칸은 한 시간(=12칸)씩 묶어 시간 단위 격자선을 유지한다.
                블록만 5분 칸을 쓴다. */}
            {hours.map((hour, index) => (
              <div
                className="timetable-grid-hour"
                key={hour}
                style={{
                  gridRow: `${index * SLOTS_PER_HOUR + 2} / span ${SLOTS_PER_HOUR}`,
                }}
              >
                {hour}
              </div>
            ))}

            {hours.map((hour, rowIndex) =>
              DAYS.map((day, colIndex) => (
                <div
                  className="timetable-grid-cell"
                  key={`${day}-${hour}`}
                  style={{
                    gridRow: `${rowIndex * SLOTS_PER_HOUR + 2} / span ${SLOTS_PER_HOUR}`,
                    gridColumn: colIndex + 2,
                  }}
                />
              )),
            )}

            {blocks.map((block) => (
              <div
                className={`timetable-block tone-${block.tone}`}
                key={block.key}
                style={{
                  gridColumn: block.dayIndex + 2,
                  gridRow: `${block.rowStart} / span ${block.rowSpan}`,
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

          {suggestion ? (
            <section className="timetable-proposal" aria-label="AI 시간표 추천 승인">
              <div className="timetable-proposal-head">
                <span>추천 시간표</span>
                <h4>{suggestion.offerings.length}개 분반 · {suggestion.total_credits}학점</h4>
                {suggestion.rationale ? <p>{suggestion.rationale}</p> : null}
              </div>
              <ul>
                {suggestion.offerings.map((offering) => (
                  <li key={offering.offering_id}>
                    <label className="timetable-proposal-row">
                      <input
                        type="checkbox"
                        checked={selectedOfferingIds.has(offering.offering_id)}
                        disabled={isApplying}
                        onChange={() => toggleOffering(offering.offering_id)}
                      />
                      <span>
                        <strong>
                          {offering.course_name ?? `분반 ${offering.offering_id}`}
                          {offering.section ? ` (${offering.section})` : ""}
                        </strong>
                        <small>{offeringSummary(offering)}</small>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
              {applyError ? (
                <p className="timetable-proposal-error" role="alert">{applyError}</p>
              ) : null}
              <div className="timetable-proposal-actions">
                <button type="button" disabled={isApplying} onClick={dismissSuggestion}>
                  나중에
                </button>
                <button
                  className="timetable-apply-button"
                  type="button"
                  disabled={selectedOfferingIds.size === 0}
                  onClick={acceptSuggestion}
                >
                  <Check size={14} aria-hidden="true" />
                  시간표에 담기 ({selectedOfferingIds.size}개 · {selectedCredits}학점)
                </button>
              </div>
            </section>
          ) : null}

          {applyError ? (
            <p className="timetable-proposal-error" role="alert">{applyError}</p>
          ) : null}

          {applyResult ? (
            <section className="timetable-applied" aria-live="polite">
              <p>
                <Check size={14} aria-hidden="true" />
                {applyResult.applied.length}개 과목을 {TARGET_YEAR}년 {TARGET_SEMESTER} 로드맵에
                반영했습니다.
              </p>
              {applyResult.skipped.length > 0 ? (
                <ul className="timetable-applied-skipped">
                  {applyResult.skipped.map((item) => (
                    <li key={item.offering_id}>
                      {item.course_name ?? `분반 ${item.offering_id}`} — {item.reason}
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
          ) : null}

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
              /* 시간표 에이전트는 로드맵 없이도 동작한다(수강기록·진로만으로 후보 제안). */
              disabled={isSending}
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
