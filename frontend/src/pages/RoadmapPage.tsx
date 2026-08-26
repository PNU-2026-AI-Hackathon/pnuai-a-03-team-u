import { Check, ChevronLeft, ChevronRight, LoaderCircle, Pencil, Plus, RefreshCw, RotateCcw, Save, Send, Trash2, X } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { FormEvent, KeyboardEvent } from "react";
import { getApiErrorMessage } from "../api/client";
import { getActivities } from "../api/profile";
import type { ActivityRecord } from "../api/profile";
import {
  browseCourses,
  chatWithRoadmapAgent,
  confirmRoadmapChanges,
  createRoadmapItem,
  createRoadmapSession,
  clearRoadmapConversation,
  deleteRoadmapItem,
  deleteRoadmapSession,
  getCurrentRoadmap,
  getMyCurriculum,
  getRoadmapConversation,
  listRoadmapSessions,
  searchCourses,
  updateRoadmap,
  updateRoadmapItem,
} from "../api/roadmaps";
import type { CourseSearchResult, Curriculum, CurriculumCourse, PendingRoadmapChange, Roadmap, RoadmapChatSession, RoadmapConversation, RoadmapItem } from "../api/roadmaps";
import { searchDepartments } from "../api/departments";
import type { DepartmentSearchResult } from "../api/departments";
import { getCourseRecords, getGraduationProgress, isMockStudentDataEnabled } from "../api/studentInfo";
import type { CourseRecord, GraduationProgram } from "../api/studentInfo";
import { isMockAuthEnabled, visibleGrades } from "../api/auth";
import type { AdmissionType } from "../api/auth";
import { useAuth } from "../auth/AuthContext";
import { ChatMarkdown } from "../components/chat/ChatMarkdown";

type RoadmapTab = "semester" | "requirements" | "curriculum";

type RequirementCourse = {
  name: string;
  credits: number;
  term: string;
  status: "이수 완료" | "수강 중" | "이수 예정";
};

type RequirementGroup = {
  category: string;
  earned: number;
  required: number;
  courses: RequirementCourse[];
};

type TimelineStatus = "수강 중" | "이수 예정" | "준비 중";

type TimelineItem = {
  name: string;
  category: string;
  status: TimelineStatus;
};

type TimelineTerm = {
  term: string;
  period: string;
  summary: string;
  items: TimelineItem[];
};

type NewTimelineItem = TimelineItem;

type ChatMessage = {
  id: string;
  speaker: "AI" | "나";
  text: string;
};

type SuggestedAction = {
  label: string;
  prompt: string;
};

type ProposalKind = "major-first" | "general-balance" | "load-balance" | "requirement-check" | "balanced";

type RoadmapProposal = {
  kind: ProposalKind;
  title: string;
  summary: string;
  changes: string[];
};

type MockAiResponse = {
  message: string;
  suggestions: SuggestedAction[];
  proposal: RoadmapProposal;
};

const requirementStatusClassNames: Record<RequirementCourse["status"], string> = {
  "이수 완료": "status-completed",
  "수강 중": "status-current",
  "이수 예정": "status-planned",
};

const timelineStatusClassNames: Record<TimelineStatus, string> = {
  "수강 중": "status-current",
  "이수 예정": "status-planned",
  "준비 중": "status-preparing",
};

const timelineCategoryOptions = ["전공 기초", "전공 필수", "전공 선택", "교양 필수", "교양 선택", "자격증", "진로 활동", "학사 일정"];

/** 학기 카드의 "+ 과목 담기" 브라우징 이수구분 칩. courses.category 원 표기(공백 없음)와 맞춘다. */
const COURSE_BROWSE_CATEGORIES = ["전공기초", "전공필수", "전공선택", "교양필수", "교양선택", "일반선택"];
const timelineStatusOptions: TimelineStatus[] = ["수강 중", "이수 예정", "준비 중"];
const emptyTimelineItem: NewTimelineItem = { name: "", category: "전공 선택", status: "이수 예정" };

function cloneTimeline(timeline: TimelineTerm[]): TimelineTerm[] {
  return timeline.map((timelineTerm) => ({
    ...timelineTerm,
    items: timelineTerm.items.map((item) => ({ ...item })),
  }));
}

function summarizeTimelineItems(items: TimelineItem[]) {
  const academicItems = items.filter((item) => item.category.startsWith("전공") || item.category.startsWith("교양"));
  return academicItems.length === items.length ? `${academicItems.length * 3}학점 계획` : `${items.length}개 계획`;
}

/** 비교과로 볼 이수구분. 로드맵 카드에서 교과 활동과 나누어 보여준다. */
const NON_CURRICULAR_CATEGORIES = ["자격증", "진로 활동", "비교과", "대외활동", "공모전", "인턴십", "프로젝트", "상담", "어학"];

function isNonCurricular(category: string) {
  return NON_CURRICULAR_CATEGORIES.some((keyword) => category.includes(keyword));
}

/** 교과 먼저, 비교과 다음 순서로 묶고 각 그룹의 첫 항목을 표시한다. */
function groupTimelineItems<T extends { category: string }>(items: T[]) {
  const courses = items.filter((item) => !isNonCurricular(item.category));
  const activities = items.filter((item) => isNonCurricular(item.category));
  return [
    ...courses.map((item, index) => ({ item, kind: "course" as const, isFirst: index === 0, count: courses.length })),
    ...activities.map((item, index) => ({ item, kind: "activity" as const, isFirst: index === 0, count: activities.length })),
  ];
}

const initialTimeline: TimelineTerm[] = [
  {
    term: "3학년 1학기",
    period: "현재 학기",
    summary: "전공 9학점",
    items: [
      { name: "데이터베이스", category: "전공 기초", status: "수강 중" },
      { name: "자료구조", category: "전공 필수", status: "수강 중" },
      { name: "웹프로그래밍", category: "전공 선택", status: "수강 중" },
    ],
  },
  {
    term: "여름방학",
    period: "방학 계획",
    summary: "진로 활동 2개",
    items: [
      { name: "빅데이터분석기사 필기", category: "자격증", status: "준비 중" },
      { name: "포트폴리오 클리닉", category: "진로 활동", status: "준비 중" },
    ],
  },
  {
    term: "3학년 2학기",
    period: "다음 학기",
    summary: "전공·교양 9학점",
    items: [
      { name: "머신러닝", category: "전공 필수", status: "이수 예정" },
      { name: "바이오데이터분석", category: "전공 선택", status: "이수 예정" },
      { name: "교양 선택", category: "교양 선택", status: "이수 예정" },
    ],
  },
  {
    term: "4학년 1학기",
    period: "장기 계획",
    summary: "졸업 준비 3개",
    items: [
      { name: "캡스톤디자인", category: "전공 필수", status: "이수 예정" },
      { name: "인턴십", category: "진로 활동", status: "준비 중" },
      { name: "졸업요건 최종 점검", category: "학사 일정", status: "준비 중" },
    ],
  },
];

const initialMessages: ChatMessage[] = [
  {
    id: "initial-ai-1",
    speaker: "AI",
    text: "현재 전공 필수 6학점, 교양 선택 3학점, 일반 선택 3학점이 핵심으로 남아 있어요.",
  },
  {
    id: "initial-user-1",
    speaker: "나",
    text: "전공 필수부터 채우는 계획으로 바꿔줘.",
  },
  {
    id: "initial-ai-2",
    speaker: "AI",
    text: "좋아요. 머신러닝과 캡스톤을 우선 배치하고, 교양 선택은 부담이 낮은 학기로 조정할 수 있어요.",
  },
];

const initialSuggestedActions: SuggestedAction[] = [
  { label: "선수과목 확인", prompt: "전공 필수 과목의 선수과목도 확인해줘." },
  { label: "학점 부담 낮추기", prompt: "학기별 학점 부담을 조금 낮춰줘." },
  { label: "졸업요건 점검", prompt: "이 계획으로 졸업요건을 충족하는지 점검해줘." },
];

function buildMockAiResponse(prompt: string): MockAiResponse {
  if (prompt.includes("필수") || prompt.includes("선수")) {
    return {
      message: "전공 필수를 우선하면 3학년 2학기에 머신러닝과 알고리즘을 함께 듣고, 4학년 1학기에 캡스톤디자인으로 이어가는 흐름이 좋아요.",
      suggestions: [
        { label: "과목 난이도 비교", prompt: "머신러닝과 알고리즘의 학습 부담을 비교해줘." },
        { label: "선수과목 다시 확인", prompt: "캡스톤까지 필요한 선수과목을 다시 확인해줘." },
        { label: "교양 배치 추천", prompt: "남은 교양 선택은 어느 학기에 듣는 게 좋을까?" },
      ],
      proposal: {
        kind: "major-first",
        title: "전공 필수 우선 배치",
        summary: "전공 흐름을 먼저 완성하고 교양 과목을 뒤 학기로 분산합니다.",
        changes: ["3학년 2학기에 알고리즘 추가", "교양 선택을 4학년 1학기로 이동", "머신러닝에서 캡스톤으로 이어지는 순서 유지"],
      },
    };
  }

  if (prompt.includes("교양")) {
    return {
      message: "교양 선택 3학점은 캡스톤 준비와 겹치지 않도록 4학년 1학기에 배치하는 편이 안정적이에요. 3학년 2학기는 전공 심화에 집중할 수 있습니다.",
      suggestions: [
        { label: "부담 낮은 교양", prompt: "전공 수업과 병행하기 좋은 교양 과목 기준을 알려줘." },
        { label: "전공 학점 확인", prompt: "교양을 옮긴 뒤 학기별 전공 학점을 확인해줘." },
        { label: "졸업학점 재계산", prompt: "변경 후 남은 졸업학점을 다시 계산해줘." },
      ],
      proposal: {
        kind: "general-balance",
        title: "교양 과목 부담 분산",
        summary: "3학년 2학기의 전공 집중도를 높이도록 교양 선택 시기를 조정합니다.",
        changes: ["3학년 2학기 교양 선택 제외", "4학년 1학기에 교양 선택 3학점 배치", "전공 심화 과목 순서는 그대로 유지"],
      },
    };
  }

  if (prompt.includes("부담") || prompt.includes("난이도")) {
    return {
      message: "3학년 2학기에 전공 심화 과목이 몰리지 않도록 바이오데이터분석을 4학년 1학기로 옮기는 편이 좋아요. 다음 학기는 머신러닝과 교양 선택에 집중할 수 있습니다.",
      suggestions: [
        { label: "4학년 부담 확인", prompt: "과목을 옮긴 뒤 4학년 1학기 부담을 확인해줘." },
        { label: "전공 필수 유지", prompt: "전공 필수 과목은 그대로 유지해서 조정해줘." },
        { label: "방학 학습 계획", prompt: "학기 부담을 줄일 수 있는 방학 학습 계획도 알려줘." },
      ],
      proposal: {
        kind: "load-balance",
        title: "학기별 학습 부담 조정",
        summary: "전공 심화 과목 하나를 뒤 학기로 옮겨 다음 학기의 집중도를 높입니다.",
        changes: ["3학년 2학기 바이오데이터분석 제외", "4학년 1학기에 바이오데이터분석 배치", "머신러닝과 교양 선택 일정 유지"],
      },
    };
  }

  if (prompt.includes("요건") || prompt.includes("학점") || prompt.includes("졸업")) {
    return {
      message: "현재 계획대로라면 전공 필수 6학점과 교양 선택 3학점을 우선 확인해야 해요. 여름방학에 중간 점검을 넣으면 수강신청 전에 누락을 줄일 수 있습니다.",
      suggestions: [
        { label: "필수 과목 우선순위", prompt: "남은 필수 과목의 우선순위를 정해줘." },
        { label: "학기별 학점 계산", prompt: "현재 계획의 학기별 예정 학점을 계산해줘." },
        { label: "수강신청 점검", prompt: "수강신청 전에 확인할 항목을 정리해줘." },
      ],
      proposal: {
        kind: "requirement-check",
        title: "졸업요건 중간 점검 추가",
        summary: "다음 학기 수강신청 전에 부족한 영역을 다시 확인합니다.",
        changes: ["여름방학에 졸업요건 중간 점검 추가", "전공 필수와 교양 선택 부족 학점 재확인", "4학년 1학기 최종 점검 일정 유지"],
      },
    };
  }

  return {
    message: "요청하신 내용을 기준으로 다음 학기는 전공 심화와 졸업요건을 함께 챙기는 균형형 계획이 적합해요. 알고리즘을 추가하고 점검 일정을 앞당겨 볼게요.",
    suggestions: [
      { label: "전공 중심으로 조정", prompt: "전공 과목 중심으로 다시 조정해줘." },
      { label: "학점 부담 낮추기", prompt: "한 학기 최대 12학점 기준으로 조정해줘." },
      { label: "진로 활동 연결", prompt: "로드맵에 진로 활동도 함께 연결해줘." },
    ],
    proposal: {
      kind: "balanced",
      title: "다음 학기 균형 조정",
      summary: "전공 심화 과목을 보강하고 졸업요건 확인 시점을 앞당깁니다.",
      changes: ["3학년 2학기에 알고리즘 추가", "여름방학에 졸업요건 중간 점검 추가", "기존 진로 활동 일정 유지"],
    },
  };
}

function applyProposalToTimeline(current: TimelineTerm[], kind: ProposalKind): TimelineTerm[] {
  return current.map((timelineTerm) => {
    let items = [...timelineTerm.items];
    let summary = timelineTerm.summary;

    if ((kind === "major-first" || kind === "general-balance") && timelineTerm.term === "3학년 2학기") {
      items = items.filter((item) => item.name !== "교양 선택");
      summary = kind === "major-first" ? "전공 9학점" : "전공 6학점";
    }

    if ((kind === "major-first" || kind === "balanced") && timelineTerm.term === "3학년 2학기" && !items.some((item) => item.name === "알고리즘")) {
      items.push({ name: "알고리즘", category: "전공 필수", status: "이수 예정" });
      summary = kind === "balanced" ? "전공·교양 12학점" : "전공 9학점";
    }

    if ((kind === "major-first" || kind === "general-balance") && timelineTerm.term === "4학년 1학기" && !items.some((item) => item.name === "교양 선택")) {
      items.unshift({ name: "교양 선택", category: "교양 선택", status: "이수 예정" });
      summary = "전공·교양 및 졸업 준비";
    }

    if (kind === "load-balance" && timelineTerm.term === "3학년 2학기") {
      items = items.filter((item) => item.name !== "바이오데이터분석");
      summary = "전공·교양 6학점";
    }

    if (kind === "load-balance" && timelineTerm.term === "4학년 1학기" && !items.some((item) => item.name === "바이오데이터분석")) {
      items.unshift({ name: "바이오데이터분석", category: "전공 선택", status: "이수 예정" });
      summary = "전공 심화 및 졸업 준비";
    }

    if ((kind === "requirement-check" || kind === "balanced") && timelineTerm.term === "여름방학" && !items.some((item) => item.name === "졸업요건 중간 점검")) {
      items.push({ name: "졸업요건 중간 점검", category: "학사 일정", status: "준비 중" });
      summary = "진로·학사 활동 3개";
    }

    return { ...timelineTerm, items, summary };
  });
}

const requirementGroups: RequirementGroup[] = [
  {
    category: "전공 기초",
    earned: 18,
    required: 18,
    courses: [
      { name: "데이터베이스", credits: 3, term: "3학년 1학기", status: "수강 중" },
    ],
  },
  {
    category: "전공 필수",
    earned: 12,
    required: 18,
    courses: [
      { name: "자료구조", credits: 3, term: "3학년 1학기", status: "수강 중" },
      { name: "머신러닝", credits: 3, term: "3학년 2학기", status: "이수 예정" },
      { name: "캡스톤디자인", credits: 3, term: "4학년 1학기", status: "이수 예정" },
    ],
  },
  {
    category: "전공 선택",
    earned: 33,
    required: 42,
    courses: [
      { name: "웹프로그래밍", credits: 3, term: "3학년 1학기", status: "수강 중" },
      { name: "바이오데이터분석", credits: 3, term: "3학년 2학기", status: "이수 예정" },
    ],
  },
  {
    category: "교양 필수",
    earned: 12,
    required: 12,
    courses: [
      { name: "대학영어", credits: 3, term: "1학년 1학기", status: "이수 완료" },
      { name: "컴퓨팅사고와인공지능", credits: 3, term: "1학년 2학기", status: "이수 완료" },
    ],
  },
  {
    category: "교양 선택",
    earned: 15,
    required: 18,
    courses: [
      { name: "교양 선택 과목", credits: 3, term: "3학년 2학기", status: "이수 예정" },
    ],
  },
];

const curriculumFlow = [
  {
    step: "기초",
    title: "2학년",
    courses: [
      ["데이터사이언스입문", "done"],
      ["회귀분석과 통계학습", "done"],
      ["자료구조", "doing"],
    ],
  },
  {
    step: "심화",
    title: "3학년",
    courses: [
      ["데이터베이스", "doing"],
      ["알고리즘", "planned"],
      ["인공지능", "planned"],
      ["AI프로그래밍", "planned"],
    ],
  },
  {
    step: "응용",
    title: "4학년",
    courses: [
      ["강화학습", "planned"],
      ["고급프로그래밍", "planned"],
      ["웹/앱 프로그래밍", "planned"],
    ],
  },
  {
    step: "연계",
    title: "졸업 준비",
    courses: [
      ["산학인턴십", "planned"],
      ["산학캡스톤디자인", "planned"],
      ["바이오헬스 진로설계", "planned"],
    ],
  },
] as const;

function MockRoadmapPage() {
  const [activeTab, setActiveTab] = useState<RoadmapTab>("semester");
  const [roadmapTimeline, setRoadmapTimeline] = useState(initialTimeline);
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [suggestedActions, setSuggestedActions] = useState(initialSuggestedActions);
  const [proposal, setProposal] = useState<RoadmapProposal | null>(null);
  const [prompt, setPrompt] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [failedPrompt, setFailedPrompt] = useState("");
  const [requirementScrollState, setRequirementScrollState] = useState({ canScrollLeft: false, canScrollRight: false });
  const [draftTimeline, setDraftTimeline] = useState<TimelineTerm[] | null>(null);
  const [addingTerm, setAddingTerm] = useState<string | null>(null);
  const [newTimelineItem, setNewTimelineItem] = useState<NewTimelineItem>(emptyTimelineItem);
  const [roadmapEditError, setRoadmapEditError] = useState("");
  const chatLogRef = useRef<HTMLDivElement>(null);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const requirementStripRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const chatLog = chatLogRef.current;
    if (!chatLog) return;
    chatLog.scrollTo({ top: chatLog.scrollHeight, behavior: "smooth" });
  }, [messages, isLoading, errorMessage, proposal]);

  useEffect(() => {
    if (activeTab !== "semester") return;
    const strip = requirementStripRef.current;
    if (!strip) return;

    function updateScrollState() {
      if (!strip) return;
      const maxScrollLeft = strip.scrollWidth - strip.clientWidth;
      setRequirementScrollState({
        canScrollLeft: strip.scrollLeft > 4,
        canScrollRight: strip.scrollLeft < maxScrollLeft - 4,
      });
    }

    updateScrollState();
    strip.addEventListener("scroll", updateScrollState, { passive: true });
    const resizeObserver = new ResizeObserver(updateScrollState);
    resizeObserver.observe(strip);

    return () => {
      strip.removeEventListener("scroll", updateScrollState);
      resizeObserver.disconnect();
    };
  }, [activeTab]);

  function scrollRequirementCards(direction: "left" | "right") {
    const strip = requirementStripRef.current;
    if (!strip) return;
    strip.scrollBy({
      left: direction === "right" ? strip.clientWidth * 0.72 : strip.clientWidth * -0.72,
      behavior: "smooth",
    });
  }

  function startRoadmapEditing() {
    setDraftTimeline(cloneTimeline(roadmapTimeline));
    setAddingTerm(null);
    setNewTimelineItem(emptyTimelineItem);
    setRoadmapEditError("");
    setActiveTab("semester");
  }

  function cancelRoadmapEditing() {
    setDraftTimeline(null);
    setAddingTerm(null);
    setNewTimelineItem(emptyTimelineItem);
    setRoadmapEditError("");
  }

  function saveRoadmapEditing() {
    if (!draftTimeline) return;
    const hasEmptyName = draftTimeline.some((timelineTerm) => timelineTerm.items.some((item) => !item.name.trim()));
    if (hasEmptyName) {
      setRoadmapEditError("항목 이름을 입력한 뒤 저장해 주세요.");
      return;
    }

    setRoadmapTimeline(cloneTimeline(draftTimeline));
    setDraftTimeline(null);
    setAddingTerm(null);
    setNewTimelineItem(emptyTimelineItem);
    setRoadmapEditError("");
  }

  function updateDraftTimelineItem(term: string, itemIndex: number, patch: Partial<TimelineItem>) {
    setDraftTimeline((current) => current?.map((timelineTerm) => {
      if (timelineTerm.term !== term) return timelineTerm;
      const items = timelineTerm.items.map((item, index) => index === itemIndex ? { ...item, ...patch } : item);
      return { ...timelineTerm, items, summary: summarizeTimelineItems(items) };
    }) ?? null);
    setRoadmapEditError("");
  }

  function moveDraftTimelineItem(sourceTerm: string, itemIndex: number, targetTerm: string) {
    if (sourceTerm === targetTerm) return;
    setDraftTimeline((current) => {
      if (!current) return null;
      const source = current.find((timelineTerm) => timelineTerm.term === sourceTerm);
      const movedItem = source?.items[itemIndex];
      if (!movedItem) return current;

      return current.map((timelineTerm) => {
        const items = timelineTerm.term === sourceTerm
          ? timelineTerm.items.filter((_, index) => index !== itemIndex)
          : timelineTerm.term === targetTerm
            ? [...timelineTerm.items, movedItem]
            : timelineTerm.items;
        return { ...timelineTerm, items, summary: summarizeTimelineItems(items) };
      });
    });
  }

  function deleteDraftTimelineItem(term: string, itemIndex: number) {
    setDraftTimeline((current) => current?.map((timelineTerm) => {
      if (timelineTerm.term !== term) return timelineTerm;
      const items = timelineTerm.items.filter((_, index) => index !== itemIndex);
      return { ...timelineTerm, items, summary: summarizeTimelineItems(items) };
    }) ?? null);
  }

  function beginAddingTimelineItem(term: string) {
    setAddingTerm(term);
    setNewTimelineItem(emptyTimelineItem);
    setRoadmapEditError("");
  }

  function addDraftTimelineItem(term: string) {
    const name = newTimelineItem.name.trim();
    if (!name) {
      setRoadmapEditError("추가할 항목 이름을 입력해 주세요.");
      return;
    }

    setDraftTimeline((current) => current?.map((timelineTerm) => {
      if (timelineTerm.term !== term) return timelineTerm;
      const items = [...timelineTerm.items, { ...newTimelineItem, name }];
      return { ...timelineTerm, items, summary: summarizeTimelineItems(items) };
    }) ?? null);
    setAddingTerm(null);
    setNewTimelineItem(emptyTimelineItem);
    setRoadmapEditError("");
  }

  async function sendMessage(value: string, appendUserMessage = true) {
    const trimmedValue = value.trim();
    if (!trimmedValue || isLoading) return;

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      speaker: "나",
      text: trimmedValue,
    };

    if (appendUserMessage) setMessages((current) => [...current, userMessage]);
    setPrompt("");
    setProposal(null);
    setErrorMessage("");
    setFailedPrompt("");
    setIsLoading(true);
    if (promptRef.current) promptRef.current.style.height = "auto";

    try {
      await new Promise((resolve) => window.setTimeout(resolve, 700));
      const response = buildMockAiResponse(trimmedValue);
      setMessages((current) => [
        ...current,
        {
          id: `ai-${Date.now()}`,
          speaker: "AI",
          text: response.message,
        },
      ]);
      setSuggestedActions(response.suggestions);
      setProposal(response.proposal);
    } catch {
      setErrorMessage("답변을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
      setFailedPrompt(trimmedValue);
    } finally {
      setIsLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendMessage(prompt);
  }

  function handlePromptKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  function handleApplyProposal() {
    if (!proposal) return;
    if (draftTimeline) {
      setDraftTimeline((current) => current ? applyProposalToTimeline(current, proposal.kind) : null);
    } else {
      setRoadmapTimeline((current) => applyProposalToTimeline(current, proposal.kind));
    }
    setMessages((current) => [
      ...current,
      {
        id: `applied-${Date.now()}`,
        speaker: "AI",
        text: `‘${proposal.title}’ 제안을 학기별 로드맵에 반영했어요. 왼쪽 화면에서 변경된 과목과 일정을 확인해 주세요.`,
      },
    ]);
    setSuggestedActions([
      { label: "변경 후 학점 확인", prompt: "변경된 계획의 학기별 학점을 확인해줘." },
      { label: "다른 계획 비교", prompt: "전공과 교양을 균형 있게 배치한 다른 계획도 보여줘." },
      { label: "졸업요건 재점검", prompt: "변경된 로드맵으로 졸업요건을 다시 점검해줘." },
    ]);
    setProposal(null);
    setActiveTab("semester");
  }

  function handleResetConversation() {
    setMessages([
      {
        id: `reset-${Date.now()}`,
        speaker: "AI",
        text: "새 대화를 시작할게요. 남은 요건이나 학기별 계획에서 궁금한 내용을 말씀해 주세요.",
      },
    ]);
    setSuggestedActions([
      { label: "남은 요건 확인", prompt: "현재 남은 졸업요건을 정리해줘." },
      { label: "다음 학기 추천", prompt: "다음 학기에 들을 과목을 추천해줘." },
      { label: "학점 부담 조정", prompt: "학기별 학점 부담을 균형 있게 조정해줘." },
    ]);
    setProposal(null);
    setPrompt("");
    setErrorMessage("");
    setFailedPrompt("");
  }

  const isEditingRoadmap = draftTimeline !== null;
  const visibleTimeline = draftTimeline ?? roadmapTimeline;

  return (
    <section className="roadmap-shell" data-current-tab={activeTab}>
      <div className="roadmap-shell-body">
      <section className="roadmap-head">
        <div className="roadmap-head-stats" aria-label="남은 요건 요약">
          <div>
            <strong>{requirementGroups.filter((group) => group.earned < group.required).length}</strong>
            <span>남은 요건</span>
          </div>
          <div>
            <strong>{requirementGroups.reduce((sum, group) => sum + Math.max(group.required - group.earned, 0), 0)}</strong>
            <span>남은 학점</span>
          </div>
        </div>
        <div>
          <p className="eyebrow">로드맵</p>
          <h2>데이터사이언스전공 로드맵</h2>
          <p>졸업 요건, 전공 심화, 진로 준비를 한 화면에서 추적합니다.</p>
        </div>
        <div className="roadmap-head-tools">
          <div className="roadmap-score">
            <span>완료율 72%</span>
            <strong>남은 학점 18</strong>
            <small>2026-1 적용</small>
          </div>
          <div className="roadmap-edit-actions">
            {isEditingRoadmap ? (
              <>
                <button type="button" onClick={cancelRoadmapEditing}>
                  <X size={15} aria-hidden="true" />
                  취소
                </button>
                <button className="save-roadmap-button" type="button" onClick={saveRoadmapEditing}>
                  <Save size={15} aria-hidden="true" />
                  저장
                </button>
              </>
            ) : (
              <button className="edit-roadmap-button" type="button" onClick={startRoadmapEditing}>
                <Pencil size={15} aria-hidden="true" />
                로드맵 편집
              </button>
            )}
          </div>
        </div>
      </section>

      <div className="roadmap-tabs" role="tablist" aria-label="로드맵 보기 방식">
        <button
          id="semester-tab"
          className={activeTab === "semester" ? "selected" : ""}
          type="button"
          role="tab"
          aria-selected={activeTab === "semester"}
          aria-controls="semester-panel"
          onClick={() => setActiveTab("semester")}
        >
          학기별
        </button>
        <button
          id="requirements-tab"
          className={activeTab === "requirements" ? "selected" : ""}
          type="button"
          role="tab"
          aria-selected={activeTab === "requirements"}
          aria-controls="requirements-panel"
          disabled={isEditingRoadmap}
          onClick={() => setActiveTab("requirements")}
        >
          요건별
        </button>
        <button
          id="curriculum-tab"
          className={activeTab === "curriculum" ? "selected" : ""}
          type="button"
          role="tab"
          aria-selected={activeTab === "curriculum"}
          aria-controls="curriculum-panel"
          disabled={isEditingRoadmap}
          onClick={() => setActiveTab("curriculum")}
        >
          학과 이수체계도
        </button>
      </div>

      <section className="roadmap-layout">
        <div className="roadmap-main">
          {activeTab === "semester" ? (
            <div id="semester-panel" role="tabpanel" aria-labelledby="semester-tab">
<div className="requirement-strip-wrap">
                <section ref={requirementStripRef} className="requirement-strip" aria-label="전공/교양 이수 요건">
                  {requirementGroups.map((group) => {
                    const remaining = Math.max(group.required - group.earned, 0);
                    const progress = Math.min(100, Math.round((group.earned / group.required) * 100));

                    return (
                      <article
                        className={remaining === 0 ? "requirement-summary-card completed" : "requirement-summary-card"}
                        key={group.category}
                        aria-label={`${group.category}: ${group.required}학점 중 ${remaining}학점 남음`}
                      >
                        <div className="requirement-summary-head">
                          <h3>{group.category}</h3>
                          <strong className="requirement-credit-ratio">
                            {group.earned}/{group.required}
                            {remaining === 0 ? <Check size={14} aria-hidden="true" /> : null}
                          </strong>
                        </div>
                        <div
                          className="requirement-summary-progress"
                          role="progressbar"
                          aria-label={`${group.category} 이수율`}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-valuenow={progress}
                        >
                          <span style={{ width: `${progress}%` }} />
                        </div>
                        <small>
                          {remaining === 0
                            ? "요건 충족 완료"
                            : group.courses[0]
                            ? `${group.courses[0].name} ${group.courses[0].credits}학점 ${group.courses[0].status}`
                            : `${remaining}학점 추가 이수 필요`}
                        </small>
                      </article>
                    );
                  })}
                </section>
                {requirementScrollState.canScrollLeft ? (
                  <button
                    className="requirement-scroll-button scroll-left"
                    type="button"
                    aria-label="이전 학점 현황 보기"
                    title="이전 학점 현황 보기"
                    onClick={() => scrollRequirementCards("left")}
                  >
                    <ChevronLeft size={18} aria-hidden="true" />
                  </button>
                ) : null}
                {requirementScrollState.canScrollRight ? (
                  <button
                    className="requirement-scroll-button scroll-right"
                    type="button"
                    aria-label="다음 학점 현황 보기"
                    title="다음 학점 현황 보기"
                    onClick={() => scrollRequirementCards("right")}
                  >
                    <ChevronRight size={18} aria-hidden="true" />
                  </button>
                ) : null}
              </div>
              

              {roadmapEditError ? <p className="roadmap-edit-feedback" role="alert">{roadmapEditError}</p> : null}

              <section className="semester-timeline">
                {visibleTimeline.map((timelineTerm) => (
                  <article className="semester-timeline-card" key={timelineTerm.term}>
                    <div className="semester-timeline-head">
                      <div>
                        <span>{timelineTerm.period}</span>
                        <h3>{timelineTerm.term}</h3>
                      </div>
                      <strong>{timelineTerm.summary}</strong>
                    </div>
                    <ul className="semester-course-list">
                      {isEditingRoadmap ? timelineTerm.items.map((item, itemIndex) => (
                        <li className="semester-course-edit-row" key={`${timelineTerm.term}-${itemIndex}`}>
                          <label className="semester-edit-name">
                            <span>항목 이름</span>
                            <input
                              value={item.name}
                              type="text"
                              onChange={(event) => updateDraftTimelineItem(timelineTerm.term, itemIndex, { name: event.target.value })}
                            />
                          </label>
                          <label>
                            <span>이수구분</span>
                            <select
                              value={item.category}
                              onChange={(event) => updateDraftTimelineItem(timelineTerm.term, itemIndex, { category: event.target.value })}
                            >
                              {timelineCategoryOptions.map((category) => <option value={category} key={category}>{category}</option>)}
                            </select>
                          </label>
                          <label>
                            <span>배치 학기</span>
                            <select
                              value={timelineTerm.term}
                              onChange={(event) => moveDraftTimelineItem(timelineTerm.term, itemIndex, event.target.value)}
                            >
                              {visibleTimeline.map((targetTerm) => <option value={targetTerm.term} key={targetTerm.term}>{targetTerm.term}</option>)}
                            </select>
                          </label>
                          <label>
                            <span>상태</span>
                            <select
                              value={item.status}
                              onChange={(event) => updateDraftTimelineItem(timelineTerm.term, itemIndex, { status: event.target.value as TimelineStatus })}
                            >
                              {timelineStatusOptions.map((status) => <option value={status} key={status}>{status}</option>)}
                            </select>
                          </label>
                          <button
                            className="delete-roadmap-item-button"
                            type="button"
                            aria-label={`${item.name || "항목"} 삭제`}
                            title="항목 삭제"
                            onClick={() => deleteDraftTimelineItem(timelineTerm.term, itemIndex)}
                          >
                            <Trash2 size={16} aria-hidden="true" />
                          </button>
                        </li>
                      )) : groupTimelineItems(timelineTerm.items).map(({ item, kind, isFirst, count }) => (
                        <Fragment key={`${kind}-${item.name}`}>
                          {isFirst ? (
                            <li className="semester-group-head">
                              <span className={`semester-group-dot is-${kind}`} aria-hidden="true" />
                              <h4>{kind === "course" ? "교과 활동" : "비교과 활동"}</h4>
                              <strong>{kind === "course" ? `${count}과목` : `${count}건`}</strong>
                            </li>
                          ) : null}
                          <li className="semester-course-row">
                            <div>
                              <strong>{item.name}</strong>
                              <span>{item.category}</span>
                            </div>
                            <span className={`semester-course-status ${timelineStatusClassNames[item.status]}`}>
                              {item.status}
                            </span>
                          </li>
                        </Fragment>
                      ))}
                    </ul>
                    {isEditingRoadmap ? (
                      addingTerm === timelineTerm.term ? (
                        <div className="add-roadmap-item-form">
                          <label className="semester-edit-name">
                            <span>새 항목 이름</span>
                            <input
                              value={newTimelineItem.name}
                              type="text"
                              placeholder="예: 알고리즘"
                              onChange={(event) => setNewTimelineItem((current) => ({ ...current, name: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>이수구분</span>
                            <select
                              value={newTimelineItem.category}
                              onChange={(event) => setNewTimelineItem((current) => ({ ...current, category: event.target.value }))}
                            >
                              {timelineCategoryOptions.map((category) => <option value={category} key={category}>{category}</option>)}
                            </select>
                          </label>
                          <label>
                            <span>상태</span>
                            <select
                              value={newTimelineItem.status}
                              onChange={(event) => setNewTimelineItem((current) => ({ ...current, status: event.target.value as TimelineStatus }))}
                            >
                              {timelineStatusOptions.map((status) => <option value={status} key={status}>{status}</option>)}
                            </select>
                          </label>
                          <div className="add-roadmap-item-actions">
                            <button type="button" onClick={() => {
                              setAddingTerm(null);
                              setNewTimelineItem(emptyTimelineItem);
                            }}>
                              취소
                            </button>
                            <button className="confirm-add-roadmap-item" type="button" onClick={() => addDraftTimelineItem(timelineTerm.term)}>
                              <Check size={14} aria-hidden="true" />
                              추가
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button className="add-roadmap-item-button" type="button" onClick={() => beginAddingTimelineItem(timelineTerm.term)}>
                          <Plus size={15} aria-hidden="true" />
                          항목 추가
                        </button>
                      )
                    ) : null}
                  </article>
                ))}
              </section>
            </div>
          ) : activeTab === "requirements" ? (
            <section
              id="requirements-panel"
              className="requirements-overview"
              role="tabpanel"
              aria-labelledby="requirements-tab"
            >
<div className="requirement-strip-wrap">
                <section ref={requirementStripRef} className="requirement-strip" aria-label="전공/교양 이수 요건">
                  {requirementGroups.map((group) => {
                    const remaining = Math.max(group.required - group.earned, 0);
                    const progress = Math.min(100, Math.round((group.earned / group.required) * 100));

                    return (
                      <article
                        className={remaining === 0 ? "requirement-summary-card completed" : "requirement-summary-card"}
                        key={group.category}
                        aria-label={`${group.category}: ${group.required}학점 중 ${remaining}학점 남음`}
                      >
                        <div className="requirement-summary-head">
                          <h3>{group.category}</h3>
                          <strong className="requirement-credit-ratio">
                            {group.earned}/{group.required}
                            {remaining === 0 ? <Check size={14} aria-hidden="true" /> : null}
                          </strong>
                        </div>
                        <div
                          className="requirement-summary-progress"
                          role="progressbar"
                          aria-label={`${group.category} 이수율`}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-valuenow={progress}
                        >
                          <span style={{ width: `${progress}%` }} />
                        </div>
                        <small>
                          {remaining === 0
                            ? "요건 충족 완료"
                            : group.courses[0]
                            ? `${group.courses[0].name} ${group.courses[0].credits}학점 ${group.courses[0].status}`
                            : `${remaining}학점 추가 이수 필요`}
                        </small>
                      </article>
                    );
                  })}
                </section>
                {requirementScrollState.canScrollLeft ? (
                  <button
                    className="requirement-scroll-button scroll-left"
                    type="button"
                    aria-label="이전 학점 현황 보기"
                    title="이전 학점 현황 보기"
                    onClick={() => scrollRequirementCards("left")}
                  >
                    <ChevronLeft size={18} aria-hidden="true" />
                  </button>
                ) : null}
                {requirementScrollState.canScrollRight ? (
                  <button
                    className="requirement-scroll-button scroll-right"
                    type="button"
                    aria-label="다음 학점 현황 보기"
                    title="다음 학점 현황 보기"
                    onClick={() => scrollRequirementCards("right")}
                  >
                    <ChevronRight size={18} aria-hidden="true" />
                  </button>
                ) : null}
              </div>
              {requirementGroups.map((group) => {
                const remaining = Math.max(group.required - group.earned, 0);
                const progress = Math.min(100, Math.round((group.earned / group.required) * 100));

                return (
                  <article className="requirement-group" key={group.category}>
                    <div className="requirement-group-head">
                      <div>
                        <h3>{group.category}</h3>
                        <p>{remaining === 0 ? "요건 충족" : `${remaining}학점 추가 이수 필요`}</p>
                      </div>
                      <strong>{group.earned} / {group.required}학점</strong>
                    </div>
                    <div
                      className="requirement-progress"
                      role="progressbar"
                      aria-label={`${group.category} 이수율`}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={progress}
                    >
                      <span style={{ width: `${progress}%` }} />
                    </div>
                    <ul className="requirement-course-list">
                      {group.courses.map((course) => (
                        <li key={`${group.category}-${course.name}`}>
                          <div>
                            <strong>{course.name}</strong>
                            <span>{course.term} · {course.credits}학점</span>
                          </div>
                          <span className={`requirement-course-status ${requirementStatusClassNames[course.status]}`}>
                            {course.status}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </article>
                );
              })}
            </section>
          ) : (
            <section
              id="curriculum-panel"
              className="curriculum-map course-system"
              role="tabpanel"
              aria-labelledby="curriculum-tab"
            >
              <div className="curriculum-title">
                <div>
                  <p className="eyebrow">Department Curriculum</p>
                  <h2>데이터사이언스전공 이수 흐름</h2>
                </div>
              </div>
              <div className="cmap-grid">
                {curriculumFlow.map((group) => (
                  <article className="cmap-col" key={group.title}>
                    <h3 className="cmap-head">{group.title}</h3>
                    <div className="cmap-body">
                      <div className="cmap-sem">
                        <ul>
                          {group.courses.map(([course, status]) => (
                            <li className={status === "done" ? "cmap-chip is-major" : status === "doing" ? "cmap-chip is-core" : "cmap-chip"} key={course}>{course}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
              <div className="curriculum-legend" aria-label="과목 이수 상태 범례">
                <span className="done">이수 완료</span>
                <span className="doing">수강 중</span>
                <span className="planned">이수 예정</span>
              </div>
            </section>
          )}
        </div>
      </section>
      </div>

      <aside className="ai-roadmap-panel">
        <div className="ai-panel-head">
          <div className="ai-panel-copy">
            <p className="eyebrow">AI와 같이 요건 맞추기</p>
              <h3>AI와 같이 로드맵 짜기</h3>
              <p>남은 요건과 과목 후보를 보면서 바로 조정합니다.</p>
            </div>
            <button
              className="ai-reset-button"
              type="button"
              aria-label="새 대화 시작"
              title="새 대화 시작"
              disabled={isLoading}
              onClick={handleResetConversation}
            >
              <RotateCcw size={16} aria-hidden="true" />
            </button>
          </div>
          <div ref={chatLogRef} className="chat-log" aria-live="polite" aria-busy={isLoading}>
            {messages.map((message) => (
              <div className={message.speaker === "AI" ? "ai-message" : "user-message"} key={message.id}>
                <strong>{message.speaker}</strong>
                <p>{message.text}</p>
              </div>
            ))}
            {isLoading ? (
              <div className="ai-message ai-message-loading">
                <strong>AI</strong>
                <p><LoaderCircle size={14} aria-hidden="true" /> 답변 생성 중</p>
              </div>
            ) : null}
            {errorMessage ? (
              <div className="ai-chat-error" role="alert">
                <p>{errorMessage}</p>
                <button type="button" onClick={() => void sendMessage(failedPrompt, false)}>
                  <RefreshCw size={13} aria-hidden="true" />
                  다시 시도
                </button>
              </div>
            ) : null}
          </div>

          {proposal ? (
            <section className="ai-roadmap-proposal" aria-label="AI 로드맵 변경 제안">
              <div>
                <span>변경 제안</span>
                <h4>{proposal.title}</h4>
                <p>{proposal.summary}</p>
              </div>
              <ul>
                {proposal.changes.map((change) => <li key={change}>{change}</li>)}
              </ul>
              <div className="proposal-actions">
                <button type="button" onClick={() => setProposal(null)}>
                  <X size={14} aria-hidden="true" />
                  취소
                </button>
                <button className="apply-proposal-button" type="button" onClick={handleApplyProposal}>
                  <Check size={14} aria-hidden="true" />
                  로드맵에 반영
                </button>
              </div>
            </section>
          ) : null}

          <div className="suggested-actions">
            <span>다음 추천 행동</span>
            <div className="quick-prompts">
              {suggestedActions.map((action) => (
                <button
                  type="button"
                  key={action.label}
                  disabled={isLoading}
                  onClick={() => void sendMessage(action.prompt)}
                >
                  {action.label}
                </button>
              ))}
            </div>
          </div>
          <form className="ai-input" onSubmit={handleSubmit}>
            <textarea
              ref={promptRef}
              value={prompt}
              rows={1}
              aria-label="AI에게 메시지 보내기"
              placeholder="예: 다음 학기 6과목 추천해줘"
              disabled={isLoading}
              onChange={(event) => {
                setPrompt(event.target.value);
                event.currentTarget.style.height = "auto";
                event.currentTarget.style.height = `${Math.min(event.currentTarget.scrollHeight, 96)}px`;
              }}
              onKeyDown={handlePromptKeyDown}
            />
            <button type="submit" aria-label="메시지 전송" title="메시지 전송" disabled={!prompt.trim() || isLoading}>
              {isLoading ? <LoaderCircle size={17} aria-hidden="true" /> : <Send size={17} aria-hidden="true" />}
            </button>
          </form>
        </aside>
    </section>
  );
}

type ApiTimelineTerm = {
  key: string;
  term: string;
  period: string;
  grade: number | null;
  /** 달력 축. 학년 슬롯은 항목이 하나라도 들어와야 채워진다(빈 미래 학기는 null). */
  year: string | null;
  semester: string | null;
  /** 커리큘럼 축. 학년 슬롯이면 항상 있고, "기타 이수 내역" 칸이면 null. */
  curriculumSemester: string | null;
  items: RoadmapItem[];
};

const apiInitialMessages: ChatMessage[] = [
  {
    id: "api-initial-message",
    speaker: "AI",
    text: "현재 로드맵과 졸업요건을 확인해 과목 배치를 함께 조정할 수 있어요.",
  },
];

const apiStatusLabels: Record<string, RequirementCourse["status"]> = {
  completed: "이수 완료",
  planned: "이수 예정",
};

function normalizeSemester(value: string | null) {
  if (!value) return null;
  if (value === "1" || value === "1학기") return "1학기";
  if (value === "2" || value === "2학기") return "2학기";
  return value;
}

/** 편입/조기이수 인정 학점을 뜻하는 semester 값. 학년 계산이 불가능한 lump-sum이다. */
const PRE_ADMISSION_SEMESTERS = new Set(["입학전성적", "편입인정"]);
const PRE_ADMISSION_KEY = "pre-admission";
const PRE_ADMISSION_LABEL = "입학 전 인정 학점";

function isPreAdmissionSemester(value: string | null) {
  return value !== null && PRE_ADMISSION_SEMESTERS.has(value);
}

function displayCategory(value: string | null) {
  const compact = value?.replace(/\s/g, "") ?? "이수구분 미정";
  const labels: Record<string, string> = {
    전공기초: "전공 기초",
    전공필수: "전공 필수",
    전공선택: "전공 선택",
    교양필수: "교양 필수",
    교양선택: "교양 선택",
    일반선택: "일반 선택",
    교직과목: "교직 과목",
  };
  return labels[compact] ?? value ?? "이수구분 미정";
}

function displayRequirementSummaryLabel(value: string) {
  const compact = value.replace(/\s/g, "");
  const labels: Record<string, string> = {
    전공기초: "전공기초",
    전공필수: "전공필수",
    전공선택: "전공선택",
    교양필수: "교양필수",
    교양선택: "교양선택",
    일반선택: "일반선택",
    교직과목: "교직과목",
  };
  return labels[compact] ?? value;
}

function sameCategory(left: string | null, right: string | null) {
  return (left ?? "").replace(/\s/g, "") === (right ?? "").replace(/\s/g, "");
}

/** 이수기록('컴퓨터프로그래밍 Ⅰ')과 교육과정('컴퓨터프로그래밍(I)') 표기 차이를 흡수한다.
 * 백엔드 roadmap_chat.py의 _norm과 같은 규칙(로마자 통일 + 괄호·공백 제거). */
function normalizeCourseName(name: string | null | undefined): string {
  if (!name) return "";
  const roman: Record<string, string> = { "Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV" };
  const romanized = [...name].map((ch) => roman[ch] ?? ch).join("");
  return romanized.replace(/[()\s]/g, "");
}

const COLLAPSED_CURRICULUM_COURSE_COUNT = 6;

function shouldCollapseCurriculumGroup(title: string) {
  return title.includes("공통") || title.includes("전학년");
}

/** 활동 시작일을 학기 키(연도-학기)로 환산한다. 3~8월은 1학기, 나머지는 2학기로 본다. */
function buildActivityTermMap(activities: ActivityRecord[]) {
  const map = new Map<string, ActivityRecord[]>();
  activities.forEach((activity) => {
    const date = activity.start_date ?? activity.end_date;
    if (!date) return;
    const [yearText, monthText] = date.split("-");
    const month = Number(monthText);
    if (!yearText || !Number.isFinite(month)) return;
    const key = `${yearText}-${month >= 3 && month <= 8 ? "1학기" : "2학기"}`;
    map.set(key, [...(map.get(key) ?? []), activity]);
  });
  return map;
}

/**
 * 로드맵 학년 슬롯을 만든다.
 *
 * 편입생은 1·2학년 커리큘럼을 밟지 않으므로 그 학년 칸을 아예 만들지 않고,
 * 대신 맨 앞에 "입학 전 인정 학점" 칸을 둔다. 편입 인정 학점은 어느 학년에도
 * 속하지 않는 lump-sum이라 정규 학기 슬롯에 넣으면 실제 3학년 1학기와 겹친다.
 */
function buildApiTimeline(
  items: RoadmapItem[],
  admissionType: AdmissionType = "freshman",
): ApiTimelineTerm[] {
  const isTransfer = admissionType === "transfer";
  const regularTerms: ApiTimelineTerm[] = [];

  if (isTransfer) {
    regularTerms.push({
      key: PRE_ADMISSION_KEY,
      term: PRE_ADMISSION_LABEL,
      period: "편입 인정",
      grade: null,
      year: null,
      semester: null,
      curriculumSemester: null,
      items: [],
    });
  }

  for (const grade of visibleGrades(admissionType)) {
    for (const semester of ["1학기", "2학기"]) {
      regularTerms.push({
        key: `${grade}-${semester}`,
        term: `${grade}학년 ${semester}`,
        period: "계획 없음",
        grade,
        // 이 슬롯이 달력상 언제인지는 항목이 들어와야 알 수 있다 — 휴학하면
        // 4학년 1학기가 달력 2학기일 수도 있어서 여기서 추측하지 않는다.
        year: null,
        semester: null,
        curriculumSemester: semester,
        items: [],
      });
    }
  }

  const terms = new Map(regularTerms.map((term) => [term.key, term]));
  items.filter((item) => item.status !== "dropped").forEach((item) => {
    // 학년 슬롯은 커리큘럼 축(planned_grade + curriculum_semester)으로 잡고,
    // 그 밖의 칸 이름은 달력 축(planned_year + planned_semester)으로 쓴다.
    // 휴학·편입 학생은 둘이 어긋난다 — 2026년 1학기가 커리큘럼상 3학년 2학기.
    const semester = normalizeSemester(item.planned_semester);
    const curriculumSemester = normalizeSemester(item.curriculum_semester);
    // 입학전성적은 planned_grade가 비어 있고 semester 원본이 그대로 남아 있다.
    // 편입생만 전용 칸을 갖는다. 조기이수 학점이 있는 신입생은 학년 흐름을
    // 흐트러뜨리지 않도록 아래 "기타 이수 내역"으로 보낸다.
    const isPreAdmission = isPreAdmissionSemester(item.planned_semester);
    const preAdmissionKey = isTransfer && isPreAdmission ? PRE_ADMISSION_KEY : null;
    const regularKey = item.planned_grade
      && (curriculumSemester === "1학기" || curriculumSemester === "2학기")
      ? `${item.planned_grade}-${curriculumSemester}`
      : null;
    const key = preAdmissionKey ?? regularKey ?? `extra-${item.planned_year ?? ""}-${semester ?? "미정"}`;
    const existing = terms.get(key);

    if (existing) {
      existing.items.push(item);
      if (!existing.year && item.planned_year) existing.year = item.planned_year;
      if (!existing.semester && semester) existing.semester = semester;
      return;
    }

    terms.set(key, {
      key,
      term: isPreAdmission
        ? [item.planned_year ? `${item.planned_year}년` : null, PRE_ADMISSION_LABEL]
            .filter(Boolean)
            .join(" ")
        : [item.planned_year ? `${item.planned_year}년` : null, semester ?? "학기 미정"]
            .filter(Boolean)
            .join(" "),
      period: "기타 이수 내역",
      grade: item.planned_grade,
      year: item.planned_year,
      semester,
      curriculumSemester: curriculumSemester ?? null,
      items: [item],
    });
  });

  return [...terms.values()].map((term) => {
    const hasPlanned = term.items.some((item) => item.status !== "completed");
    const hasCompleted = term.items.some((item) => item.status === "completed");
    return {
      ...term,
      period: hasPlanned ? "계획 학기" : hasCompleted ? "이수 내역" : term.period,
    };
  });
}

function summarizeApiTerm(items: RoadmapItem[]) {
  const credits = items.reduce((sum, item) => sum + (item.credits ?? 0), 0);
  if (items.length === 0) return "등록된 과목 없음";
  return credits > 0 ? `${Number.isInteger(credits) ? credits : credits.toFixed(1)}학점` : `${items.length}개 과목`;
}

function buildApiRequirementGroups(program: GraduationProgram | null, items: RoadmapItem[]): RequirementGroup[] {
  const categories = program?.categories ?? [];
  return categories
    .filter((category) => category.required_credits !== null)
    .map((category) => ({
      category: displayCategory(category.category_name),
      earned: category.earned_credits,
      required: category.required_credits ?? 0,
      courses: items
        .filter((item) => item.status !== "dropped" && sameCategory(item.category, category.category_name))
        .map((item) => ({
          name: item.course_name ?? "과목명 없음",
          credits: item.credits ?? 0,
          // "3학년 2학기"는 커리큘럼 축이라 curriculum_semester를 써야 한다.
          // 학년을 모르면 달력 축("2026 1학기")으로 떨어뜨린다.
          term: item.planned_grade
            ? `${item.planned_grade}학년 ${normalizeSemester(item.curriculum_semester) ?? "학기 미정"}`
            : [item.planned_year, normalizeSemester(item.planned_semester)].filter(Boolean).join(" ") || "학기 미정",
          status: apiStatusLabels[item.status] ?? "이수 예정",
        })),
    }));
}

function plannedYearForGrade(roadmap: Roadmap, studentId: string | null | undefined, grade: number | null) {
  if (!grade) return null;
  const startYear = Number(roadmap.start_year ?? studentId?.slice(0, 4));
  return Number.isFinite(startYear) ? String(startYear + grade - 1) : null;
}

function pendingChangeLabel(change: PendingRoadmapChange) {
  const actionLabels = { create: "과목 추가", update: "과목 이동", delete: "과목 삭제" };
  const term = change.planned_grade
    ? `${change.planned_grade}학년 ${normalizeSemester(change.planned_semester) ?? "학기 미정"}`
    : normalizeSemester(change.planned_semester);
  return [actionLabels[change.action], change.course_name, term, change.reason].filter(Boolean).join(" · ");
}

function ConnectedRoadmapPage() {
  const { user } = useAuth();
  const [roadmap, setRoadmap] = useState<Roadmap | null>(null);
  const [graduation, setGraduation] = useState<GraduationProgram | null>(null);
  const [curriculum, setCurriculum] = useState<Curriculum | null>(null);
  const [activeTab, setActiveTab] = useState<RoadmapTab>("semester");
  const [isPageLoading, setIsPageLoading] = useState(true);
  const [pageError, setPageError] = useState("");
  const [draftItems, setDraftItems] = useState<RoadmapItem[] | null>(null);
  const [addingTerm, setAddingTerm] = useState<string | null>(null);
  const [courseQuery, setCourseQuery] = useState("");
  const [courseResults, setCourseResults] = useState<CourseSearchResult[]>([]);
  const [selectedCourse, setSelectedCourse] = useState<CourseSearchResult | null>(null);
  const [isCourseSearching, setIsCourseSearching] = useState(false);
  const [isRoadmapSaving, setIsRoadmapSaving] = useState(false);
  const [roadmapEditError, setRoadmapEditError] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>(apiInitialMessages);
  const [suggestedActions, setSuggestedActions] = useState(initialSuggestedActions);
  const [pendingChanges, setPendingChanges] = useState<PendingRoadmapChange[]>([]);
  const [selectedChangeIds, setSelectedChangeIds] = useState<Set<number>>(new Set());
  const [prompt, setPrompt] = useState("");
  const [isAiLoading, setIsAiLoading] = useState(false);
  const [aiError, setAiError] = useState("");
  const [failedPrompt, setFailedPrompt] = useState("");
  const [requirementScrollState, setRequirementScrollState] = useState({ canScrollLeft: false, canScrollRight: false });
  const [activities, setActivities] = useState<ActivityRecord[]>([]);
  const [sessions, setSessions] = useState<RoadmapChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [isThreadLoading, setIsThreadLoading] = useState(false);
  /** 휴지통을 눌렀을 때 레일 안에 뜨는 삭제 확인 바. */
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  /** 학기 카드의 휴지통 아이콘으로 켜는 이수예정 다중 선택 삭제 모드. 전체 로드맵 편집(draftItems)과는 별개다. */
  const [deleteModeTermKey, setDeleteModeTermKey] = useState<string | null>(null);
  const [selectedDeleteIds, setSelectedDeleteIds] = useState<Set<number>>(new Set());
  const [isConfirmingItemDelete, setIsConfirmingItemDelete] = useState(false);
  const [isDeletingItems, setIsDeletingItems] = useState(false);
  const [itemDeleteError, setItemDeleteError] = useState("");
  /** 학기 카드의 "+" 아이콘으로 켜는 학과별 브라우징 다중 담기. 전체 로드맵 편집(draftItems)과는 별개다. */
  const [addCourseTermKey, setAddCourseTermKey] = useState<string | null>(null);
  const [addCourseDepartments, setAddCourseDepartments] = useState<DepartmentSearchResult[]>([]);
  const [addCourseCollege, setAddCourseCollege] = useState("");
  const [addCourseDepartment, setAddCourseDepartment] = useState<DepartmentSearchResult | null>(null);
  const [addCourseMajor, setAddCourseMajor] = useState("");
  const [addCourseCategory, setAddCourseCategory] = useState("");
  const [addCourseQuery, setAddCourseQuery] = useState("");
  const [addCourseResults, setAddCourseResults] = useState<CourseSearchResult[]>([]);
  const [isAddCourseSearching, setIsAddCourseSearching] = useState(false);
  const [addCourseSelectedIds, setAddCourseSelectedIds] = useState<Set<number>>(new Set());
  const [isAddingCourses, setIsAddingCourses] = useState(false);
  const [addCourseError, setAddCourseError] = useState("");
  // 이수기록(완료·대체 인정 포함) — 담기 목록에서 이미 이수/대체된 과목을 회색으로 막는 데 쓴다.
  const [courseRecords, setCourseRecords] = useState<CourseRecord[]>([]);
  const addCourseModalRef = useRef<HTMLDivElement>(null);
  // 로드맵 메타(제목·목표 졸업연도) 인라인 편집. 항목 편집(draftItems)과는 별개다.
  const [isMetaEditing, setIsMetaEditing] = useState(false);
  const [metaTitleDraft, setMetaTitleDraft] = useState("");
  const [metaTargetYearDraft, setMetaTargetYearDraft] = useState("");
  const [isMetaSaving, setIsMetaSaving] = useState(false);
  const [metaError, setMetaError] = useState("");
  const [expandedCurriculumLists, setExpandedCurriculumLists] = useState<Set<string>>(() => new Set());
  const chatLogRef = useRef<HTMLDivElement>(null);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const requirementStripRef = useRef<HTMLElement>(null);
  /**
   * 화면에 떠 있는 messages가 어느 세션 것인지 기억한다. 대화를 보내면 답변을
   * 낙관적으로 먼저 붙이므로, activeSessionId 변화만 보고 무조건 다시 읽으면
   * 방금 주고받은 말이 깜빡인다.
   */
  const loadedSessionRef = useRef<number | null>(null);

  async function reloadRoadmap() {
    const nextRoadmap = await getCurrentRoadmap();
    setRoadmap(nextRoadmap);
    return nextRoadmap;
  }

  function startMetaEditing() {
    if (!roadmap) return;
    setMetaTitleDraft(roadmap.title ?? "");
    setMetaTargetYearDraft(roadmap.target_graduation_year ?? "");
    setMetaError("");
    setIsMetaEditing(true);
  }

  async function saveMetaEditing() {
    if (!roadmap) return;
    const targetYear = metaTargetYearDraft.trim();
    if (targetYear && !/^\d{4}$/.test(targetYear)) {
      setMetaError("목표 졸업연도는 4자리 연도로 입력해 주세요. 예: 2028");
      return;
    }
    setIsMetaSaving(true);
    setMetaError("");
    try {
      const updated = await updateRoadmap(roadmap.id, {
        // 빈 제목은 null로 지워서 화면이 "전공 로드맵" 기본값으로 돌아가게 한다.
        title: metaTitleDraft.trim() || null,
        target_graduation_year: targetYear || null,
      });
      setRoadmap(updated);
      setIsMetaEditing(false);
    } catch (error) {
      setMetaError(getApiErrorMessage(error, "로드맵 정보를 저장하지 못했습니다."));
    } finally {
      setIsMetaSaving(false);
    }
  }

  /** 서버 대화 응답을 화면 상태로 옮긴다. 비어 있으면 안내 문구로 되돌린다. */
  function applyConversation(conversation: RoadmapConversation) {
    setMessages(conversation.messages.length > 0
      ? conversation.messages.map((message) => ({
          id: `saved-${message.id}`,
          speaker: message.role === "assistant" ? "AI" : "나",
          text: message.content,
        }))
      : apiInitialMessages);
    setPendingChanges(conversation.pending_changes);
    setSelectedChangeIds(new Set(conversation.pending_changes.map((change) => change.change_id)));
    setSuggestedActions(conversation.suggested_actions.length > 0
      ? conversation.suggested_actions
      : initialSuggestedActions);
  }

  async function refreshSessions(roadmapId: number) {
    // 목록 갱신 실패는 대화 흐름을 막지 않는다.
    const list = await listRoadmapSessions(roadmapId).catch(() => null);
    if (list) setSessions(list);
  }

  async function handleSelectSession(sessionId: number) {
    if (!roadmap || sessionId === activeSessionId || isAiLoading) return;
    setIsConfirmingDelete(false); // 다른 대화를 고르면 확인 바는 닫는다
    setActiveSessionId(sessionId);
    setAiError("");
    setFailedPrompt("");
    setIsThreadLoading(true);
    try {
      applyConversation(await getRoadmapConversation(roadmap.id, sessionId));
      loadedSessionRef.current = sessionId;
    } catch (error) {
      setAiError(getApiErrorMessage(error, "지난 대화를 불러오지 못했습니다."));
    } finally {
      setIsThreadLoading(false);
    }
  }

  async function handleCreateSession() {
    if (!roadmap || isAiLoading) return;
    setIsConfirmingDelete(false);
    setAiError("");
    try {
      const session = await createRoadmapSession(roadmap.id);
      setSessions((current) => [session, ...current]);
      setActiveSessionId(session.session_id);
      loadedSessionRef.current = session.session_id; // 방금 만든 빈 세션이라 읽을 게 없다
      setMessages(apiInitialMessages);
      setSuggestedActions(initialSuggestedActions);
      setPrompt("");
      setFailedPrompt("");
    } catch (error) {
      setAiError(getApiErrorMessage(error, "새 대화를 만들지 못했습니다."));
    }
  }

  /**
   * 서버에서 세션과 메시지를 실제로 지운다(soft delete 아님). 되돌릴 수 없어
   * 휴지통을 누르면 바로 지우지 않고 레일 안에 확인 바를 띄운다.
   */
  async function handleDeleteSession() {
    if (!roadmap || activeSessionId === null || isAiLoading) return;
    setIsConfirmingDelete(false);
    setAiError("");
    try {
      await deleteRoadmapSession(roadmap.id, activeSessionId);
      const remaining = sessions.filter((session) => session.session_id !== activeSessionId);
      setSessions(remaining);
      const nextId = remaining[0]?.session_id ?? null;
      setActiveSessionId(nextId);
      loadedSessionRef.current = nextId;
      if (nextId === null) {
        setMessages(apiInitialMessages);
        setSuggestedActions(initialSuggestedActions);
      } else {
        applyConversation(await getRoadmapConversation(roadmap.id, nextId));
      }
    } catch (error) {
      setAiError(getApiErrorMessage(error, "대화를 삭제하지 못했습니다."));
    }
  }

  async function loadPage() {
    setIsPageLoading(true);
    setPageError("");
    try {
      const [nextRoadmap, graduationResult, curriculumResult] = await Promise.all([
        getCurrentRoadmap(),
        getGraduationProgress().catch(() => null),
        getMyCurriculum().catch(() => null),
      ]);
      setRoadmap(nextRoadmap);
      setCurriculum(curriculumResult);
      const primaryProgram = graduationResult?.programs.find((program) => program.program_type === "primary")
        ?? graduationResult?.programs[0]
        ?? null;
      setGraduation(primaryProgram);
      // 세션 목록을 먼저 잡고, 그중 하나의 대화만 읽는다. session_id 없이 읽으면
      // 이 로드맵의 모든 스레드가 한 화면에 뒤섞여 나온다.
      const sessionList = await listRoadmapSessions(nextRoadmap.id).catch(() => []);
      setSessions(sessionList);
      const firstSessionId = sessionList[0]?.session_id ?? null;
      setActiveSessionId(firstSessionId);
      const conversation = await getRoadmapConversation(
        nextRoadmap.id,
        firstSessionId ?? undefined,
      ).catch(() => null);
      if (conversation) {
        applyConversation(conversation);
        loadedSessionRef.current = firstSessionId;
      }
    } catch (error) {
      setPageError(getApiErrorMessage(error, "로드맵을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."));
    } finally {
      setIsPageLoading(false);
    }
  }

  useEffect(() => {
    void loadPage();
  }, []);

  useEffect(() => {
    const chatLog = chatLogRef.current;
    if (!chatLog) return;
    chatLog.scrollTo({ top: chatLog.scrollHeight, behavior: "smooth" });
  }, [messages, isAiLoading, aiError, pendingChanges]);

  useEffect(() => {
    if (!addingTerm || selectedCourse?.course_name === courseQuery || courseQuery.trim().length < 2) {
      setCourseResults([]);
      setIsCourseSearching(false);
      return;
    }

    let cancelled = false;
    const timeout = window.setTimeout(() => {
      setIsCourseSearching(true);
      searchCourses(courseQuery.trim())
        .then((results) => {
          if (!cancelled) setCourseResults(results);
        })
        .catch(() => {
          if (!cancelled) setCourseResults([]);
        })
        .finally(() => {
          if (!cancelled) setIsCourseSearching(false);
        });
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [addingTerm, courseQuery, selectedCourse]);

  // 학기 카드 "+" 담기 패널의 단과대/학부 목록. 300여 개라 한 번만 받아 캐시한다.
  useEffect(() => {
    searchDepartments("", 300)
      .then(setAddCourseDepartments)
      .catch(() => setAddCourseDepartments([]));
  }, []);

  useEffect(() => {
    if (!addCourseTermKey || (!addCourseDepartment && !addCourseQuery.trim())) {
      setAddCourseResults([]);
      setIsAddCourseSearching(false);
      return;
    }
    let cancelled = false;
    const timeout = window.setTimeout(() => {
      setIsAddCourseSearching(true);
      browseCourses(addCourseQuery.trim(), {
        departmentId: addCourseDepartment?.id ?? null,
        major: addCourseMajor || null,
        category: addCourseCategory || null,
      })
        .then((results) => {
          if (!cancelled) setAddCourseResults(results);
        })
        .catch(() => {
          if (!cancelled) setAddCourseResults([]);
        })
        .finally(() => {
          if (!cancelled) setIsAddCourseSearching(false);
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [addCourseTermKey, addCourseDepartment, addCourseMajor, addCourseCategory, addCourseQuery]);

  // 담기 목록에서 이미 이수/대체된 과목을 걸러내는 데 쓴다.
  useEffect(() => {
    getCourseRecords()
      .then(setCourseRecords)
      .catch(() => setCourseRecords([]));
  }, []);

  // 담기 팝업 바깥을 클릭하거나 Esc를 누르면 닫는다.
  useEffect(() => {
    if (!addCourseTermKey) return;
    function handlePointerDown(event: MouseEvent | TouchEvent) {
      const modal = addCourseModalRef.current;
      if (modal && event.target instanceof Node && !modal.contains(event.target)) {
        setAddCourseTermKey(null);
      }
    }
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") setAddCourseTermKey(null);
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("touchstart", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("touchstart", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [addCourseTermKey]);

  /** 이수 완료(roadmap 동기화분 포함) + 계획 중(전 학기 통틀어) + 대체 인정 과목의 정규화된 이름 집합.
   * 담기 목록에서 중복 선택을 막는 데 쓴다 — 이 학기 안 중복은 course_id로, 전체는 이름으로 본다. */
  const alreadyAccountedCourseNames = useMemo(() => {
    const names = new Set<string>();
    for (const item of roadmap?.items ?? []) {
      if (item.status === "dropped") continue;
      names.add(normalizeCourseName(item.course_name));
    }
    for (const record of courseRecords) {
      names.add(normalizeCourseName(record.course_name));
      for (const substitute of record.substitutes ?? []) {
        names.add(normalizeCourseName(substitute.course_name));
      }
    }
    names.delete("");
    return names;
  }, [roadmap, courseRecords]);

  useEffect(() => {
    if (activeTab !== "semester") return;
    const strip = requirementStripRef.current;
    if (!strip) return;

    function updateScrollState() {
      const element = requirementStripRef.current;
      if (!element) return;
      const maxScrollLeft = element.scrollWidth - element.clientWidth;
      setRequirementScrollState({
        canScrollLeft: element.scrollLeft > 4,
        canScrollRight: element.scrollLeft < maxScrollLeft - 4,
      });
    }

    updateScrollState();
    strip.addEventListener("scroll", updateScrollState, { passive: true });
    const resizeObserver = new ResizeObserver(updateScrollState);
    resizeObserver.observe(strip);
    return () => {
      strip.removeEventListener("scroll", updateScrollState);
      resizeObserver.disconnect();
    };
  }, [activeTab, roadmap, graduation]);

  const visibleItems = useMemo(() => draftItems ?? roadmap?.items ?? [], [draftItems, roadmap]);
  const activeSession = sessions.find((session) => session.session_id === activeSessionId) ?? null;
  const admissionType = user?.admission_type ?? "freshman";
  const timeline = useMemo(
    () => buildApiTimeline(visibleItems, admissionType),
    [visibleItems, admissionType],
  );
  const activityTermMap = useMemo(() => buildActivityTermMap(activities), [activities]);

  useEffect(() => {
    getActivities()
      .then(setActivities)
      .catch(() => setActivities([]));
  }, []);
  const requirementGroups = useMemo(
    () => buildApiRequirementGroups(graduation, roadmap?.items ?? []),
    [graduation, roadmap],
  );
  const isEditingRoadmap = draftItems !== null;
  const requiredCredits = graduation?.required_total_credits ?? null;
  const earnedCredits = graduation?.earned_total_credits ?? 0;
  const remainingCredits = graduation?.remaining_total_credits ?? null;
  const completionRate = requiredCredits ? Math.min(100, Math.round((earnedCredits / requiredCredits) * 100)) : 0;
  const roadmapTitle = roadmap?.title?.trim() || `${user?.major ?? "전공"} 로드맵`;

  function scrollRequirementCards(direction: "left" | "right") {
    const strip = requirementStripRef.current;
    if (!strip) return;
    strip.scrollBy({
      left: direction === "right" ? strip.clientWidth * 0.72 : strip.clientWidth * -0.72,
      behavior: "smooth",
    });
  }

  function resetCoursePicker() {
    setAddingTerm(null);
    setCourseQuery("");
    setCourseResults([]);
    setSelectedCourse(null);
    setIsCourseSearching(false);
  }

  function startRoadmapEditing() {
    setDraftItems((roadmap?.items ?? []).map((item) => ({ ...item })));
    setRoadmapEditError("");
    setActiveTab("semester");
    resetCoursePicker();
    setDeleteModeTermKey(null);
    setSelectedDeleteIds(new Set());
    setIsConfirmingItemDelete(false);
    setItemDeleteError("");
    setAddCourseTermKey(null);
    setAddCourseSelectedIds(new Set());
    setAddCourseError("");
  }

  function cancelRoadmapEditing() {
    setDraftItems(null);
    setRoadmapEditError("");
    resetCoursePicker();
  }

  function moveDraftItem(itemId: number, targetTermKey: string) {
    const target = timeline.find((term) => term.key === targetTermKey);
    if (!target || !roadmap) return;
    // 화면이 아는 건 커리큘럼 슬롯뿐이다. 달력 학기는 저장 시 서버가 이수
    // 기록에서 환산하므로, 여기 값은 저장 전까지만 쓰는 낙관적 표시값이다.
    setDraftItems((current) => current?.map((item) => item.id === itemId ? {
      ...item,
      planned_grade: target.grade,
      planned_year: target.year ?? plannedYearForGrade(roadmap, user?.student_id, target.grade),
      planned_semester: target.semester,
      curriculum_semester: target.curriculumSemester,
    } : item) ?? null);
    setRoadmapEditError("");
  }

  function removeDraftItem(item: RoadmapItem) {
    if (item.status === "completed") return;
    setDraftItems((current) => current?.filter((candidate) => candidate.id !== item.id) ?? null);
  }

  function toggleTermDeleteMode(termKey: string) {
    setDeleteModeTermKey((current) => (current === termKey ? null : termKey));
    setSelectedDeleteIds(new Set());
    setIsConfirmingItemDelete(false);
    setItemDeleteError("");
    // 같은 카드에서 삭제 모드와 담기 패널을 동시에 열어두지 않는다.
    setAddCourseTermKey(null);
  }

  function toggleSelectedDeleteId(itemId: number) {
    setSelectedDeleteIds((current) => {
      const next = new Set(current);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }

  async function confirmDeleteSelectedItems() {
    if (!roadmap || selectedDeleteIds.size === 0) return;
    setIsDeletingItems(true);
    setItemDeleteError("");
    try {
      await Promise.all([...selectedDeleteIds].map((id) => deleteRoadmapItem(roadmap.id, id)));
      await reloadRoadmap();
      setDeleteModeTermKey(null);
      setSelectedDeleteIds(new Set());
      setIsConfirmingItemDelete(false);
    } catch (error) {
      // Promise.all은 하나라도 실패하면 나머지 성공 여부를 알려주지 않는다.
      // 어떤 항목이 실제로 지워졌는지 화면이 추측하지 않도록 로드맵을 다시
      // 읽어와 서버 상태로 맞추고 선택 모드를 닫는다 (saveRoadmapEditing과 동일 패턴).
      setItemDeleteError(getApiErrorMessage(error, "과목을 삭제하지 못했습니다."));
      await reloadRoadmap().catch(() => undefined);
      setDeleteModeTermKey(null);
      setSelectedDeleteIds(new Set());
      setIsConfirmingItemDelete(false);
    } finally {
      setIsDeletingItems(false);
    }
  }

  function beginAddingCourse(termKey: string) {
    setAddingTerm(termKey);
    setCourseQuery("");
    setSelectedCourse(null);
    setCourseResults([]);
    setRoadmapEditError("");
  }

  function addSelectedCourse(term: ApiTimelineTerm) {
    if (!selectedCourse || !roadmap) {
      setRoadmapEditError("검색 결과에서 추가할 과목을 선택해 주세요.");
      return;
    }

    const temporaryId = Math.min(-1, ...((draftItems ?? []).map((item) => item.id - 1)));
    const newItem: RoadmapItem = {
      id: temporaryId,
      course_id: selectedCourse.id,
      planned_grade: term.grade,
      planned_year: term.year ?? plannedYearForGrade(roadmap, user?.student_id, term.grade),
      planned_semester: term.semester,
      curriculum_semester: term.curriculumSemester,
      course_name: selectedCourse.course_name,
      department_name: null,
      major_name: null,
      category: selectedCourse.category,
      credits: selectedCourse.credits,
      status: "planned",
      is_confirmed: false,
      reason: null,
      source: "manual",
    };
    setDraftItems((current) => [...(current ?? []), newItem]);
    resetCoursePicker();
    setRoadmapEditError("");
  }

  /** 학기 카드 "+" 담기 패널을 열고 닫는다. 전체 로드맵 편집 모드는 안 건드린다. */
  function toggleAddCoursePanel(termKey: string) {
    setAddCourseTermKey((current) => (current === termKey ? null : termKey));
    setAddCourseSelectedIds(new Set());
    setAddCourseError("");
    // 같은 카드에서 담기 패널과 삭제 모드를 동시에 열어두지 않는다.
    setDeleteModeTermKey(null);
  }

  function toggleAddCourseSelected(courseId: number) {
    setAddCourseSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(courseId)) next.delete(courseId);
      else next.add(courseId);
      return next;
    });
  }

  async function confirmAddCourses(term: ApiTimelineTerm) {
    if (!roadmap || addCourseSelectedIds.size === 0) return;
    setIsAddingCourses(true);
    setAddCourseError("");
    try {
      await Promise.all(
        [...addCourseSelectedIds].map((courseId) =>
          createRoadmapItem(roadmap.id, {
            course_id: courseId,
            planned_grade: term.grade,
            curriculum_semester: term.curriculumSemester,
          }),
        ),
      );
      await reloadRoadmap();
      setAddCourseTermKey(null);
      setAddCourseSelectedIds(new Set());
      setAddCourseQuery("");
      setAddCourseResults([]);
    } catch (error) {
      // 일부만 성공하고 일부만 실패할 수 있다 — 화면을 서버 상태로 다시 맞추고
      // 패널도 닫는다(삭제 쪽 confirmDeleteSelectedItems와 동일 패턴). 안 닫으면
      // 사용자가 그대로 "담기"를 다시 눌러 이미 성공한 과목을 중복으로
      // create_roadmap_item 하게 된다(그 엔드포인트엔 중복 방지가 없다).
      setAddCourseError(getApiErrorMessage(error, "과목을 담지 못했습니다."));
      await reloadRoadmap().catch(() => undefined);
      setAddCourseTermKey(null);
      setAddCourseSelectedIds(new Set());
    } finally {
      setIsAddingCourses(false);
    }
  }

  async function saveRoadmapEditing() {
    if (!roadmap || !draftItems) return;
    setIsRoadmapSaving(true);
    setRoadmapEditError("");

    const originalItems = roadmap.items;
    const draftIds = new Set(draftItems.filter((item) => item.id > 0).map((item) => item.id));
    const deletedItems = originalItems.filter((item) => item.id > 0 && item.status !== "completed" && !draftIds.has(item.id));
    const createdItems = draftItems.filter((item) => item.id < 0);
    const updatedItems = draftItems.filter((item) => {
      if (item.id < 0 || item.status === "completed") return false;
      const original = originalItems.find((candidate) => candidate.id === item.id);
      return original && (
        original.course_id !== item.course_id
        || original.planned_grade !== item.planned_grade
        || normalizeSemester(original.curriculum_semester) !== normalizeSemester(item.curriculum_semester)
      );
    });

    try {
      await Promise.all([
        ...deletedItems.map((item) => deleteRoadmapItem(roadmap.id, item.id)),
        ...createdItems.map((item) => {
          if (!item.course_id) throw new Error("선택되지 않은 과목이 있습니다.");
          // 커리큘럼 축만 보낸다. 달력 학기를 같이 보내면 화면이 추측한 값이
          // 서버의 환산값을 덮어써서, 휴학 학생의 학기가 다시 어긋난다.
          return createRoadmapItem(roadmap.id, {
            course_id: item.course_id,
            planned_grade: item.planned_grade,
            curriculum_semester: item.curriculum_semester,
          });
        }),
        ...updatedItems.map((item) => updateRoadmapItem(roadmap.id, item.id, {
          course_id: item.course_id ?? undefined,
          planned_grade: item.planned_grade,
          curriculum_semester: item.curriculum_semester,
        })),
      ]);
      await reloadRoadmap();
      setDraftItems(null);
      resetCoursePicker();
    } catch (error) {
      setRoadmapEditError(getApiErrorMessage(error, "로드맵 변경사항을 저장하지 못했습니다."));
      await reloadRoadmap().catch(() => undefined);
      setDraftItems(null);
      resetCoursePicker();
    } finally {
      setIsRoadmapSaving(false);
    }
  }

  async function sendMessage(value: string, appendUserMessage = true) {
    const trimmedValue = value.trim();
    if (!trimmedValue || isAiLoading || !roadmap) return;
    if (appendUserMessage) {
      setMessages((current) => [...current, { id: `user-${Date.now()}`, speaker: "나", text: trimmedValue }]);
    }
    setPrompt("");
    setPendingChanges([]);
    setAiError("");
    setFailedPrompt("");
    setIsAiLoading(true);
    if (promptRef.current) promptRef.current.style.height = "auto";

    try {
      const response = await chatWithRoadmapAgent(
        roadmap.id,
        trimmedValue,
        activeSessionId ?? undefined,
      );
      // 세션을 안 넘겼으면 서버가 새로 열었을 수 있다. 화면은 이미 그 세션의
      // 최신 상태이므로 다시 읽지 않도록 표시만 맞춰둔다.
      setActiveSessionId(response.session_id);
      loadedSessionRef.current = response.session_id;
      setMessages((current) => [...current, { id: `ai-${Date.now()}`, speaker: "AI", text: response.reply }]);
      setPendingChanges(response.pending_changes);
      setSelectedChangeIds(new Set(response.pending_changes.map((change) => change.change_id)));
      setSuggestedActions(response.suggested_actions);
      void refreshSessions(roadmap.id);
    } catch (error) {
      setAiError(getApiErrorMessage(error, "AI 답변을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."));
      setFailedPrompt(trimmedValue);
    } finally {
      setIsAiLoading(false);
    }
  }

  async function resolvePendingChanges(approve: boolean) {
    if (!roadmap || pendingChanges.length === 0 || isAiLoading) return;
    // approve=true면 사용자가 체크한 항목만 반영. 나머지는 rejected로 함께 정리해서
    // pending 상태로 남지 않게 한다. approve=false면 전부 rejected.
    const allIds = pendingChanges.map((change) => change.change_id);
    const approved = approve ? allIds.filter((id) => selectedChangeIds.has(id)) : [];
    const rejected = approve ? allIds.filter((id) => !selectedChangeIds.has(id)) : allIds;
    if (approve && approved.length === 0) return;
    setIsAiLoading(true);
    setAiError("");
    try {
      await confirmRoadmapChanges(roadmap.id, approved, rejected);
      if (approve && approved.length > 0) {
        await reloadRoadmap();
        setMessages((current) => [...current, {
          id: `applied-${Date.now()}`,
          speaker: "AI",
          text: `승인한 ${approved.length}개 변경사항을 로드맵에 반영했습니다.`,
        }]);
        setActiveTab("semester");
      }
      setPendingChanges([]);
      setSelectedChangeIds(new Set());
    } catch (error) {
      setAiError(getApiErrorMessage(error, "AI 변경안을 처리하지 못했습니다."));
    } finally {
      setIsAiLoading(false);
    }
  }

  function togglePendingChangeSelection(changeId: number) {
    setSelectedChangeIds((current) => {
      const next = new Set(current);
      if (next.has(changeId)) next.delete(changeId); else next.add(changeId);
      return next;
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendMessage(prompt);
  }

  function handlePromptKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  /**
   * 지금 보고 있는 스레드만 비운다. 세션 도입 전에는 로드맵 전체를 날렸는데,
   * 그러면 다른 스레드와 아직 승인 안 한 변경안까지 같이 사라진다.
   */
  async function handleResetConversation() {
    if (!roadmap || isAiLoading) return;
    setIsAiLoading(true);
    setAiError("");
    try {
      await clearRoadmapConversation(roadmap.id, activeSessionId ?? undefined);
      setMessages(apiInitialMessages);
      setSuggestedActions(initialSuggestedActions);
      setPendingChanges([]);
      setSelectedChangeIds(new Set());
      setPrompt("");
      setFailedPrompt("");
      void refreshSessions(roadmap.id);
    } catch (error) {
      setAiError(getApiErrorMessage(error, "대화 초기화에 실패했습니다."));
    } finally {
      setIsAiLoading(false);
    }
  }

  if (isPageLoading) {
    return (
      <section className="roadmap-api-state" aria-live="polite">
        <LoaderCircle size={22} aria-hidden="true" />
        <strong>로드맵을 불러오는 중입니다.</strong>
      </section>
    );
  }

  if (pageError || !roadmap) {
    return (
      <section className="roadmap-api-state" role="alert">
        <strong>{pageError || "로드맵 정보가 없습니다."}</strong>
        <button type="button" onClick={() => void loadPage()}>
          <RefreshCw size={15} aria-hidden="true" />
          다시 시도
        </button>
      </section>
    );
  }

  return (
    <section className="roadmap-shell" data-current-tab={activeTab}>
      <div className="roadmap-shell-body">
      <section className="roadmap-head">
        <div className="roadmap-head-stats" aria-label="남은 요건 요약">
          <div>
            <strong>{requirementGroups.filter((group) => group.earned < group.required).length}</strong>
            <span>남은 요건</span>
          </div>
          <div>
            <strong>{requirementGroups.reduce((sum, group) => sum + Math.max(group.required - group.earned, 0), 0)}</strong>
            <span>남은 학점</span>
          </div>
        </div>
        <div>
          <p className="eyebrow">로드맵</p>
          {isMetaEditing ? (
            <div className="roadmap-meta-editor">
              <input
                className="roadmap-meta-title-input"
                value={metaTitleDraft}
                onChange={(event) => setMetaTitleDraft(event.target.value)}
                placeholder={`${user?.major ?? "전공"} 로드맵`}
                maxLength={120}
                disabled={isMetaSaving}
              />
              <input
                className="roadmap-meta-year-input"
                value={metaTargetYearDraft}
                onChange={(event) => setMetaTargetYearDraft(event.target.value)}
                placeholder="목표 졸업연도"
                inputMode="numeric"
                maxLength={4}
                disabled={isMetaSaving}
              />
              <button type="button" onClick={() => void saveMetaEditing()} disabled={isMetaSaving} title="저장">
                {isMetaSaving ? <LoaderCircle size={15} aria-hidden="true" /> : <Save size={15} aria-hidden="true" />}
              </button>
              <button type="button" onClick={() => setIsMetaEditing(false)} disabled={isMetaSaving} title="취소">
                <X size={15} aria-hidden="true" />
              </button>
              {metaError ? <p className="roadmap-meta-error" role="alert">{metaError}</p> : null}
            </div>
          ) : (
            <h2 className="roadmap-meta-title">
              {roadmapTitle}
              {roadmap.target_graduation_year ? (
                <span className="roadmap-meta-target">{roadmap.target_graduation_year}년 졸업 목표</span>
              ) : null}
              <button className="roadmap-meta-edit-button" type="button" onClick={startMetaEditing} title="로드맵 이름·목표 졸업연도 수정" aria-label="로드맵 이름과 목표 졸업연도 수정">
                <Pencil size={14} aria-hidden="true" />
              </button>
            </h2>
          )}
          <p>{roadmap.summary || "졸업 요건과 앞으로 이수할 과목을 한 화면에서 관리합니다."}</p>
        </div>
        <div className="roadmap-head-tools">
          <div className="roadmap-score">
            <span>완료율 {completionRate}%</span>
            <strong>{remainingCredits === null ? "기준 확인 필요" : `남은 학점 ${remainingCredits}`}</strong>
            <small>{graduation?.curriculum_year ? `${graduation.curriculum_year} 교육과정` : "교육과정 확인 필요"}</small>
          </div>
          <div className="roadmap-edit-actions">
            {isEditingRoadmap ? (
              <>
                <button type="button" disabled={isRoadmapSaving} onClick={cancelRoadmapEditing}>
                  <X size={15} aria-hidden="true" /> 취소
                </button>
                <button className="save-roadmap-button" type="button" disabled={isRoadmapSaving} onClick={() => void saveRoadmapEditing()}>
                  {isRoadmapSaving ? <LoaderCircle size={15} aria-hidden="true" /> : <Save size={15} aria-hidden="true" />}
                  저장
                </button>
              </>
            ) : (
              <button className="edit-roadmap-button" type="button" onClick={startRoadmapEditing}>
                <Pencil size={15} aria-hidden="true" /> 로드맵 편집
              </button>
            )}
          </div>
        </div>
      </section>

      <div className="roadmap-tabs" role="tablist" aria-label="로드맵 보기 방식">
        <button id="semester-tab" className={activeTab === "semester" ? "selected" : ""} type="button" role="tab" aria-selected={activeTab === "semester"} onClick={() => setActiveTab("semester")}>학기별</button>
        <button id="requirements-tab" className={activeTab === "requirements" ? "selected" : ""} type="button" role="tab" aria-selected={activeTab === "requirements"} disabled={isEditingRoadmap} onClick={() => setActiveTab("requirements")}>요건별</button>
        <button id="curriculum-tab" className={activeTab === "curriculum" ? "selected" : ""} type="button" role="tab" aria-selected={activeTab === "curriculum"} disabled={isEditingRoadmap} onClick={() => setActiveTab("curriculum")}>학과 이수체계도</button>
      </div>

      <section className="roadmap-layout">
        <div className="roadmap-main">
          {activeTab === "semester" ? (
            <div id="semester-panel" role="tabpanel" aria-labelledby="semester-tab">
<div className="requirement-strip-shell">
                <section ref={requirementStripRef} className="requirement-strip" aria-label="전공 및 교양 이수 요건">
                  {requirementGroups.length > 0 ? requirementGroups.map((group) => {
                    const remaining = Math.max(group.required - group.earned, 0);
                    const progress = group.required > 0 ? Math.min(100, Math.round((group.earned / group.required) * 100)) : 0;
                    return (
                      <article className="requirement-summary-card" key={group.category} aria-label={`${group.category} ${group.required}학점 중 ${remaining}학점 남음`}>
                        <div className="requirement-summary-head"><h3 title={group.category}>{displayRequirementSummaryLabel(group.category)}</h3><strong className="requirement-credit-ratio">{group.earned}/{group.required}{remaining === 0 ? <Check size={14} aria-hidden="true" /> : null}</strong></div>
                        <div className="requirement-summary-progress" role="progressbar" aria-label={`${group.category} 이수율`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div>
                        <small>{remaining === 0 ? "요건 충족 완료" : `${remaining}학점 추가 이수 필요`}</small>
                      </article>
                    );
                  }) : <p className="roadmap-inline-empty">학생지원시스템 동기화 후 이수 현황이 표시됩니다.</p>}
                </section>
                {requirementScrollState.canScrollLeft ? <button className="requirement-scroll-button scroll-left" type="button" aria-label="이전 학점 현황 보기" onClick={() => scrollRequirementCards("left")}><ChevronLeft size={18} aria-hidden="true" /></button> : null}
                {requirementScrollState.canScrollRight ? <button className="requirement-scroll-button scroll-right" type="button" aria-label="다음 학점 현황 보기" onClick={() => scrollRequirementCards("right")}><ChevronRight size={18} aria-hidden="true" /></button> : null}
              </div>
              

              {roadmapEditError ? <p className="roadmap-edit-feedback" role="alert">{roadmapEditError}</p> : null}
              {itemDeleteError ? <p className="roadmap-edit-feedback" role="alert">{itemDeleteError}</p> : null}
              {addCourseError ? <p className="roadmap-edit-feedback" role="alert">{addCourseError}</p> : null}
              <section className="semester-timeline">
                {timeline.map((term) => (
                  <article className="semester-timeline-card" key={term.key}>
                    <div className="semester-timeline-head">
                      <div><span>{term.period}</span><h3>{term.term}</h3></div>
                      <div className="semester-timeline-credit">
                        <strong>{summarizeApiTerm(term.items)}</strong>
                        {!isEditingRoadmap ? (
                          <div className="semester-timeline-toolbar">
                            {term.grade && term.curriculumSemester && term.period !== "이수 내역" ? (
                              <button
                                type="button"
                                className={addCourseTermKey === term.key ? "term-add-toggle is-active" : "term-add-toggle"}
                                aria-label={addCourseTermKey === term.key ? "과목 담기 패널 닫기" : "과목 담기"}
                                title={addCourseTermKey === term.key ? "과목 담기 패널 닫기" : "과목 담기"}
                                onClick={() => toggleAddCoursePanel(term.key)}
                              >
                                <Plus size={14} aria-hidden="true" />
                              </button>
                            ) : null}
                            {term.items.some((item) => item.status !== "completed") ? (
                              <button
                                type="button"
                                className={deleteModeTermKey === term.key ? "term-delete-toggle is-active" : "term-delete-toggle"}
                                aria-label={deleteModeTermKey === term.key ? "이수예정 삭제 모드 닫기" : "이수예정 과목 삭제"}
                                title={deleteModeTermKey === term.key ? "삭제 모드 닫기" : "이수예정 과목 삭제"}
                                onClick={() => toggleTermDeleteMode(term.key)}
                              >
                                <Trash2 size={14} aria-hidden="true" />
                              </button>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    </div>
                    <ul className="semester-course-list">
                      {term.items.map((item) => {
                        if (isEditingRoadmap) {
                          return (
                            <li className="semester-course-edit-row api-roadmap-edit-row" key={item.id}>
                              <div className="api-roadmap-course-copy"><strong>{item.course_name ?? "과목명 없음"}</strong><span>{displayCategory(item.category)} · {item.credits ?? 0}학점</span></div>
                              {item.status === "completed" ? (
                                <span className="semester-course-status status-completed">이수 완료</span>
                              ) : (
                                <>
                                  <label><span>배치 학기</span><select value={term.key} onChange={(event) => moveDraftItem(item.id, event.target.value)}>{timeline.filter((candidate) => candidate.grade && candidate.curriculumSemester).map((candidate) => <option value={candidate.key} key={candidate.key}>{candidate.term}</option>)}</select></label>
                                  <button className="delete-roadmap-item-button" type="button" aria-label={`${item.course_name ?? "과목"} 삭제`} title="과목 삭제" onClick={() => removeDraftItem(item)}><Trash2 size={16} aria-hidden="true" /></button>
                                </>
                              )}
                            </li>
                          );
                        }

                        const isSelectable = deleteModeTermKey === term.key && item.status !== "completed";
                        return (
                          <Fragment key={item.id}>
                            {term.items[0]?.id === item.id ? (
                              <li className="semester-group-head">
                                <span className="semester-group-dot is-course" aria-hidden="true" />
                                <h4>교과 활동</h4>
                                <strong>{term.items.length}과목</strong>
                              </li>
                            ) : null}
                            <li className="semester-course-row">
                              <div><strong>{item.course_name ?? "과목명 없음"}</strong><span>{displayCategory(item.category)} · {item.credits ?? 0}학점</span></div>
                              {isSelectable ? (
                                <input
                                  className="semester-course-select-badge"
                                  type="checkbox"
                                  checked={selectedDeleteIds.has(item.id)}
                                  aria-label={`${item.course_name ?? "과목"} 삭제 선택`}
                                  onChange={() => toggleSelectedDeleteId(item.id)}
                                />
                              ) : (
                                <span className={`semester-course-status ${item.status === "completed" ? "status-completed" : "status-planned"}`}>{item.status === "completed" ? "이수 완료" : "이수 예정"}</span>
                              )}
                            </li>
                          </Fragment>
                        );
                      })}
                      {!isEditingRoadmap && term.year && (activityTermMap.get(`${term.year}-${term.semester}`)?.length ?? 0) > 0 ? (
                        <>
                          <li className="semester-group-head">
                            <span className="semester-group-dot is-activity" aria-hidden="true" />
                            <h4>비교과 활동</h4>
                            <strong>{activityTermMap.get(`${term.year}-${term.semester}`)!.length}건</strong>
                          </li>
                          {activityTermMap.get(`${term.year}-${term.semester}`)!.map((activity) => (
                            <li className="semester-course-row" key={`activity-${activity.id}`}>
                              <div><strong>{activity.title}</strong><span>{activity.category ?? "비교과"}{activity.organization ? ` · ${activity.organization}` : ""}</span></div>
                              <span className="semester-course-status status-completed">{activity.end_date ? "완료" : "진행 중"}</span>
                            </li>
                          ))}
                        </>
                      ) : null}
                    </ul>
                    {deleteModeTermKey === term.key ? (
                      isConfirmingItemDelete ? (
                        <div className="timetable-delete-confirm" role="alertdialog" aria-label="이수예정 과목 삭제 확인">
                          <p>
                            선택한 과목 <strong>{selectedDeleteIds.size}개</strong>를 로드맵에서 삭제할까요?
                            <span>되돌릴 수 없습니다.</span>
                          </p>
                          <div>
                            <button type="button" disabled={isDeletingItems} onClick={() => setIsConfirmingItemDelete(false)}>취소</button>
                            <button
                              className="timetable-delete-confirm-button"
                              type="button"
                              autoFocus
                              disabled={isDeletingItems}
                              onClick={() => void confirmDeleteSelectedItems()}
                            >
                              {isDeletingItems ? <LoaderCircle size={13} aria-hidden="true" /> : <Trash2 size={13} aria-hidden="true" />} 삭제
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="term-delete-bar">
                          <span>{selectedDeleteIds.size > 0 ? `${selectedDeleteIds.size}개 선택됨` : "삭제할 과목을 선택하세요"}</span>
                          <div className="term-delete-bar-actions">
                            <button type="button" onClick={() => toggleTermDeleteMode(term.key)}>취소</button>
                            <button
                              className="term-delete-bar-delete"
                              type="button"
                              disabled={selectedDeleteIds.size === 0}
                              onClick={() => setIsConfirmingItemDelete(true)}
                            >
                              <Trash2 size={13} aria-hidden="true" /> 삭제
                            </button>
                          </div>
                        </div>
                      )
                    ) : null}
                    {addCourseTermKey === term.key ? (() => {
                      const existingCourseIds = new Set(
                        term.items.map((item) => item.course_id).filter((id): id is number => id !== null),
                      );
                      const addCourseColleges = [...new Set(addCourseDepartments.map((item) => item.college))].sort();
                      const addCourseCollegeDepartments = addCourseDepartments.filter(
                        (item) => item.college === addCourseCollege,
                      );
                      return createPortal(
                        <div className="roadmap-add-course-overlay" role="presentation">
                        <div
                          className="roadmap-add-course-modal"
                          role="dialog"
                          aria-modal="true"
                          aria-label={`${term.term} 과목 담기`}
                          ref={addCourseModalRef}
                        >
                          <header className="substitution-modal-head">
                            <div>
                              <p className="substitution-modal-eyebrow">과목 담기</p>
                              <h4>{term.term}</h4>
                            </div>
                            <button
                              type="button"
                              className="substitution-modal-close"
                              aria-label="닫기"
                              onClick={() => toggleAddCoursePanel(term.key)}
                            >
                              <X size={16} aria-hidden="true" />
                            </button>
                          </header>
                          <div className="timetable-scope">
                            <label>
                              <select
                                aria-label="단과대 선택"
                                value={addCourseCollege}
                                onChange={(event) => {
                                  setAddCourseCollege(event.target.value);
                                  setAddCourseDepartment(null);
                                  setAddCourseMajor("");
                                }}
                              >
                                <option value="">단과대 선택</option>
                                {addCourseColleges.map((college) => <option value={college} key={college}>{college}</option>)}
                              </select>
                            </label>
                            <label>
                              <select
                                aria-label="학부 선택"
                                value={addCourseDepartment?.id ?? ""}
                                disabled={!addCourseCollege}
                                onChange={(event) => {
                                  const next = addCourseCollegeDepartments.find((item) => item.id === Number(event.target.value));
                                  setAddCourseDepartment(next ?? null);
                                  setAddCourseMajor("");
                                }}
                              >
                                <option value="">{addCourseCollege ? "학부 선택" : "단과대를 먼저"}</option>
                                {addCourseCollegeDepartments.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
                              </select>
                            </label>
                            <label>
                              <select
                                aria-label="전공 선택"
                                value={addCourseMajor}
                                disabled={!addCourseDepartment || addCourseDepartment.majors.length === 0}
                                onChange={(event) => setAddCourseMajor(event.target.value)}
                              >
                                <option value="">
                                  {addCourseDepartment && addCourseDepartment.majors.length > 0 ? "학부 전체 (모든 전공)" : "세부전공 없음"}
                                </option>
                                {(addCourseDepartment?.majors ?? []).map((major) => <option value={major} key={major}>{major}</option>)}
                              </select>
                            </label>
                          </div>
                          <div className="timetable-filters is-sub">
                            {COURSE_BROWSE_CATEGORIES.map((category) => (
                              <button
                                key={category}
                                type="button"
                                className={addCourseCategory === category ? "selected" : ""}
                                onClick={() => setAddCourseCategory((current) => (current === category ? "" : category))}
                              >
                                {displayCategory(category)}
                              </button>
                            ))}
                          </div>
                          <input
                            className="term-add-course-search"
                            type="search"
                            autoComplete="off"
                            placeholder="과목명으로 바로 검색할 수도 있어요"
                            value={addCourseQuery}
                            onChange={(event) => setAddCourseQuery(event.target.value)}
                          />
                          <ul className="timetable-course-list term-add-course-list">
                            {isAddCourseSearching ? (
                              <li className="timetable-empty"><strong>과목을 찾는 중입니다</strong></li>
                            ) : null}
                            {!isAddCourseSearching && !addCourseDepartment && !addCourseQuery.trim() ? (
                              <li className="timetable-empty">
                                <strong>학부를 먼저 선택해 주세요</strong>
                                <span>단과대 → 학부를 고르면 그 학부 과목이 쭉 나옵니다. 과목명으로 바로 검색할 수도 있어요.</span>
                              </li>
                            ) : null}
                            {!isAddCourseSearching && (addCourseDepartment || addCourseQuery.trim()) && addCourseResults.length === 0 ? (
                              <li className="timetable-empty">
                                <strong>조건에 맞는 과목이 없습니다</strong>
                                <span>검색어를 줄이거나 이수구분 필터를 해제해 보세요.</span>
                              </li>
                            ) : null}
                            {addCourseResults.map((course) => {
                              const alreadyInThisTerm = existingCourseIds.has(course.id);
                              // 이 학기 안 중복은 course_id로, 전체(이수완료·대체인정·다른 학기 계획)는
                              // 이름으로 본다 — course_id가 없는 이수기록·대체 인정도 걸러야 하므로.
                              const alreadyElsewhere = !alreadyInThisTerm
                                && alreadyAccountedCourseNames.has(normalizeCourseName(course.course_name));
                              const isUnavailable = alreadyInThisTerm || alreadyElsewhere;
                              return (
                                <li className={isUnavailable ? "timetable-course is-unavailable" : "timetable-course"} key={course.id}>
                                  <div className="timetable-course-info">
                                    <strong>
                                      {course.course_name}
                                      {alreadyInThisTerm ? <em> · 이미 이 학기에 담김</em> : null}
                                      {alreadyElsewhere ? <em> · 이미 이수·대체·계획됨</em> : null}
                                    </strong>
                                    <div className="timetable-course-tags" aria-label="과목 정보">
                                      {course.category ? <span>{displayCategory(course.category)}</span> : null}
                                      {course.major_name ? <span>{course.major_name}</span> : null}
                                      {course.credits ? <span>{course.credits}학점</span> : null}
                                      {course.year ? <span>{course.year}학년</span> : null}
                                      {course.semester ? <span>{course.semester}학기 개설</span> : null}
                                    </div>
                                  </div>
                                  <input
                                    className="semester-course-select-badge"
                                    type="checkbox"
                                    checked={addCourseSelectedIds.has(course.id)}
                                    disabled={isUnavailable}
                                    aria-label={`${course.course_name} 선택`}
                                    onChange={() => toggleAddCourseSelected(course.id)}
                                  />
                                </li>
                              );
                            })}
                          </ul>
                          <div className="term-add-bar">
                            <span>{addCourseSelectedIds.size > 0 ? `${addCourseSelectedIds.size}개 선택됨` : "담을 과목을 선택하세요"}</span>
                            <div className="term-add-bar-actions">
                              <button type="button" disabled={isAddingCourses} onClick={() => toggleAddCoursePanel(term.key)}>취소</button>
                              <button
                                className="term-add-bar-confirm"
                                type="button"
                                disabled={addCourseSelectedIds.size === 0 || isAddingCourses}
                                onClick={() => void confirmAddCourses(term)}
                              >
                                {isAddingCourses ? <LoaderCircle size={13} aria-hidden="true" /> : <Plus size={13} aria-hidden="true" />} 담기
                              </button>
                            </div>
                          </div>
                        </div>
                        </div>,
                        document.body,
                      );
                    })() : null}
                    {isEditingRoadmap && term.grade && term.curriculumSemester ? (
                      addingTerm === term.key ? (
                        <div className="add-roadmap-item-form api-course-picker">
                          <label className="semester-edit-name"><span>과목 검색</span><input value={courseQuery} type="search" autoComplete="off" placeholder="과목명을 2글자 이상 입력" onChange={(event) => { setCourseQuery(event.target.value); setSelectedCourse(null); }} /></label>
                          {isCourseSearching ? <p className="course-search-status"><LoaderCircle size={14} aria-hidden="true" /> 검색 중</p> : null}
                          {courseResults.length > 0 ? <div className="course-search-results">{courseResults.map((course) => <button type="button" key={course.id} onClick={() => { setSelectedCourse(course); setCourseQuery(course.course_name); setCourseResults([]); }}><strong>{course.course_name}</strong><span>{displayCategory(course.category)} · {course.credits ?? 0}학점{course.course_code ? ` · ${course.course_code}` : ""}</span></button>)}</div> : null}
                          {selectedCourse ? <p className="selected-course-summary"><Check size={14} aria-hidden="true" /> {selectedCourse.course_name}</p> : null}
                          <div className="add-roadmap-item-actions"><button type="button" onClick={resetCoursePicker}>취소</button><button className="confirm-add-roadmap-item" type="button" disabled={!selectedCourse} onClick={() => addSelectedCourse(term)}><Check size={14} aria-hidden="true" /> 추가</button></div>
                        </div>
                      ) : (
                        <button className="add-roadmap-item-button" type="button" onClick={() => beginAddingCourse(term.key)}><Plus size={15} aria-hidden="true" /> 과목 추가</button>
                      )
                    ) : null}
                  </article>
                ))}
              </section>
            </div>
          ) : activeTab === "requirements" ? (
            <section id="requirements-panel" className="requirements-overview" role="tabpanel" aria-labelledby="requirements-tab">
<div className="requirement-strip-shell">
                <section ref={requirementStripRef} className="requirement-strip" aria-label="전공 및 교양 이수 요건">
                  {requirementGroups.length > 0 ? requirementGroups.map((group) => {
                    const remaining = Math.max(group.required - group.earned, 0);
                    const progress = group.required > 0 ? Math.min(100, Math.round((group.earned / group.required) * 100)) : 0;
                    return (
                      <article className="requirement-summary-card" key={group.category} aria-label={`${group.category} ${group.required}학점 중 ${remaining}학점 남음`}>
                        <div className="requirement-summary-head"><h3 title={group.category}>{displayRequirementSummaryLabel(group.category)}</h3><strong className="requirement-credit-ratio">{group.earned}/{group.required}{remaining === 0 ? <Check size={14} aria-hidden="true" /> : null}</strong></div>
                        <div className="requirement-summary-progress" role="progressbar" aria-label={`${group.category} 이수율`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div>
                        <small>{remaining === 0 ? "요건 충족 완료" : `${remaining}학점 추가 이수 필요`}</small>
                      </article>
                    );
                  }) : <p className="roadmap-inline-empty">학생지원시스템 동기화 후 이수 현황이 표시됩니다.</p>}
                </section>
                {requirementScrollState.canScrollLeft ? <button className="requirement-scroll-button scroll-left" type="button" aria-label="이전 학점 현황 보기" onClick={() => scrollRequirementCards("left")}><ChevronLeft size={18} aria-hidden="true" /></button> : null}
                {requirementScrollState.canScrollRight ? <button className="requirement-scroll-button scroll-right" type="button" aria-label="다음 학점 현황 보기" onClick={() => scrollRequirementCards("right")}><ChevronRight size={18} aria-hidden="true" /></button> : null}
              </div>
              {requirementGroups.length > 0 ? requirementGroups.map((group) => {
                const remaining = Math.max(group.required - group.earned, 0);
                const progress = group.required > 0 ? Math.min(100, Math.round((group.earned / group.required) * 100)) : 0;
                return (
                  <article className="requirement-group" key={group.category}>
                    <div className="requirement-group-head"><div><h3>{group.category}</h3><p>{remaining === 0 ? "요건 충족" : `${remaining}학점 추가 이수 필요`}</p></div><strong>{group.earned} / {group.required}학점</strong></div>
                    <div className="requirement-progress" role="progressbar" aria-label={`${group.category} 이수율`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div>
                    <ul className="requirement-course-list">{group.courses.map((course, index) => <li key={`${group.category}-${course.name}-${index}`}><div><strong>{course.name}</strong><span>{course.term} · {course.credits}학점</span></div><span className={`requirement-course-status ${requirementStatusClassNames[course.status]}`}>{course.status}</span></li>)}</ul>
                  </article>
                );
              }) : <p className="roadmap-inline-empty">졸업요건 데이터가 아직 없습니다.</p>}
            </section>
          ) : (
            <section id="curriculum-panel" className="curriculum-map course-system" role="tabpanel" aria-labelledby="curriculum-tab">
              <div className="curriculum-title"><div><p className="eyebrow">Department Curriculum</p><h2>{curriculum?.major ?? curriculum?.department ?? user?.major ?? user?.department ?? "학과"} 이수 흐름</h2></div></div>
              {curriculum?.groups.length ? (
                <>
                  <div className="cmap-grid">
                    {curriculum.groups.map((group) => {
                      const bySemester = (want: "1" | "2") => group.courses.filter((course) => {
                        const sem = String(course.semester ?? "");
                        if (want === "1") return sem !== "2"; // 학기 미상은 1학기 컬럼에 흡수
                        return sem === "2";
                      });
                      const chipClass = (course: CurriculumCourse) => {
                        const category = course.category ?? "";
                        if (category.replace(/\s/g, "").includes("전공기초")) return "cmap-chip is-required";
                        if (category.includes("필수")) return "cmap-chip is-required";
                        if (category.includes("전공")) return "cmap-chip is-major";
                        return "cmap-chip";
                      };
                      return (
                        <article className="cmap-col" key={group.grade}>
                          <h3 className="cmap-head">{group.title}</h3>
                          <div className="cmap-body">
                            {(["1", "2"] as const).map((sem) => (
                              <div className="cmap-sem" key={sem}>
                                <span className="cmap-sem-head">{sem}학기</span>
                                <ul>
                                  {(() => {
                                    const courses = bySemester(sem);
                                    const listKey = `${group.grade}-${sem}`;
                                    const isCollapsible = shouldCollapseCurriculumGroup(group.title) && courses.length > COLLAPSED_CURRICULUM_COURSE_COUNT;
                                    const isExpanded = expandedCurriculumLists.has(listKey);
                                    const visibleCourses = isCollapsible && !isExpanded ? courses.slice(0, COLLAPSED_CURRICULUM_COURSE_COUNT) : courses;
                                    return (
                                      <>
                                        {visibleCourses.map((course) => (
                                    <li
                                      className={chipClass(course)}
                                      key={course.id}
                                      title={[course.category, course.credits !== null ? `${course.credits}학점` : null].filter(Boolean).join(" · ")}
                                    >
                                      {course.course_name}
                                    </li>
                                        ))}
                                        {isCollapsible ? (
                                          <li className="cmap-more-item">
                                            <button
                                              type="button"
                                              className="cmap-more-button"
                                              onClick={() => {
                                                setExpandedCurriculumLists((current) => {
                                                  const next = new Set(current);
                                                  if (next.has(listKey)) next.delete(listKey);
                                                  else next.add(listKey);
                                                  return next;
                                                });
                                              }}
                                            >
                                              {isExpanded ? "접기" : `더보기 ${courses.length - COLLAPSED_CURRICULUM_COURSE_COUNT}개`}
                                            </button>
                                          </li>
                                        ) : null}
                                      </>
                                    );
                                  })()}
                                </ul>
                              </div>
                            ))}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                  <ul className="cmap-legend" aria-label="과목 유형 범례">
                    <li><span className="cmap-swatch is-major" aria-hidden="true" />전공 과목</li>
                    <li><span className="cmap-swatch is-core" aria-hidden="true" />핵심 과목</li>
                    <li><span className="cmap-swatch is-required" aria-hidden="true" />필수 과목</li>
                    <li><span className="cmap-swatch" aria-hidden="true" />기타 과목</li>
                  </ul>
                </>
              ) : <p className="roadmap-inline-empty">등록된 학과 이수체계도 데이터가 없습니다.</p>}
            </section>
          )}
        </div>
      </section>
      </div>

      <aside className="ai-roadmap-panel">
        <div className="ai-panel-head"><div className="ai-panel-copy"><p className="eyebrow">AI와 같이 요건 맞추기</p><h3>AI와 같이 로드맵 짜기</h3><p>남은 요건과 실제 로드맵을 기준으로 변경안을 제안합니다.</p></div><button className="ai-reset-button" type="button" aria-label="이 대화 비우기" title="이 대화 비우기" disabled={isAiLoading || pendingChanges.length > 0} onClick={handleResetConversation}><RotateCcw size={16} aria-hidden="true" /></button></div>
        <div className="ai-session-bar">
          <select
            className="ai-session-select"
            aria-label="대화 스레드 선택"
            value={activeSessionId ?? ""}
            disabled={isAiLoading || isThreadLoading || sessions.length === 0}
            onChange={(event) => void handleSelectSession(Number(event.target.value))}
          >
            {sessions.length === 0 ? <option value="">새 대화</option> : null}
            {sessions.map((session) => (
              <option key={session.session_id} value={session.session_id}>
                {(session.title?.trim() || "제목 없는 대화")} · {session.message_count}개
              </option>
            ))}
          </select>
          <button className="ai-session-new" type="button" aria-label="새 대화 시작" title="새 대화 시작" disabled={isAiLoading} onClick={() => void handleCreateSession()}><Plus size={15} aria-hidden="true" /></button>
          <button className="ai-session-delete" type="button" aria-label="이 대화 삭제" title="이 대화 삭제" disabled={isAiLoading || activeSessionId === null} onClick={() => setIsConfirmingDelete(true)}><Trash2 size={15} aria-hidden="true" /></button>
        </div>

        {isConfirmingDelete && activeSession ? (
          <div className="ai-session-confirm" role="alertdialog" aria-label="대화 삭제 확인">
            <p>
              <strong>{activeSession.title?.trim() || "제목 없는 대화"}</strong>을(를) 삭제할까요?
              {activeSession.message_count > 0
                ? ` 메시지 ${activeSession.message_count}개가 함께 지워집니다.`
                : null}
              <span> 되돌릴 수 없습니다.</span>
            </p>
            <div className="ai-session-confirm-actions">
              <button type="button" onClick={() => setIsConfirmingDelete(false)}>취소</button>
              <button
                className="ai-session-confirm-delete"
                type="button"
                autoFocus
                onClick={() => void handleDeleteSession()}
              >
                <Trash2 size={13} aria-hidden="true" /> 삭제
              </button>
            </div>
          </div>
        ) : null}
        {/* 시간표 챗과 같은 말풍선 디자인(timetable-chat)을 공유한다 — 두 AI 챗이
            딴 화면처럼 보이던 것을 통일. AI 답변은 마크다운으로 렌더링. */}
        <div ref={chatLogRef} className="timetable-chat roadmap-rail-chat" aria-live="polite" aria-busy={isAiLoading || isThreadLoading}>
          {isThreadLoading ? <p className="timetable-empty">지난 대화를 불러오는 중입니다…</p> : messages.map((message) => (
            <div className={`timetable-chat-row ${message.speaker === "AI" ? "assistant" : "user"}`} key={message.id}>
              <span className="timetable-chat-who">{message.speaker === "AI" ? "AI" : "나"}</span>
              {message.speaker === "AI"
                ? <div className="chat-bubble"><ChatMarkdown text={message.text} /></div>
                : <p>{message.text}</p>}
            </div>
          ))}
          {isAiLoading ? <p className="timetable-empty">답변을 작성하고 있습니다…</p> : null}
          {aiError ? <div className="ai-chat-error" role="alert"><p>{aiError}</p>{failedPrompt ? <button type="button" onClick={() => void sendMessage(failedPrompt, false)}><RefreshCw size={13} aria-hidden="true" /> 다시 시도</button> : null}</div> : null}
        </div>
        {pendingChanges.length > 0 ? <section className="ai-roadmap-proposal" aria-label="AI 로드맵 변경 제안"><div><span>변경 제안</span><h4>{pendingChanges.length}개의 변경사항</h4><p>반영할 항목만 체크한 뒤 승인하세요.</p></div><ul>{pendingChanges.map((change) => <li key={change.change_id}><label className="pending-change-row"><input type="checkbox" checked={selectedChangeIds.has(change.change_id)} onChange={() => togglePendingChangeSelection(change.change_id)} disabled={isAiLoading} /><span>{pendingChangeLabel(change)}</span></label></li>)}</ul><div className="proposal-actions"><button type="button" disabled={isAiLoading} onClick={() => void resolvePendingChanges(false)}><X size={14} aria-hidden="true" /> 모두 거절</button><button className="apply-proposal-button" type="button" disabled={isAiLoading || selectedChangeIds.size === 0} onClick={() => void resolvePendingChanges(true)}><Check size={14} aria-hidden="true" /> 선택 승인 ({selectedChangeIds.size})</button></div></section> : null}
        <div className="suggested-actions"><span>다음 추천 행동</span><div className="quick-prompts">{suggestedActions.map((action) => <button type="button" key={action.label} disabled={isAiLoading || pendingChanges.length > 0} onClick={() => void sendMessage(action.prompt)}>{action.label}</button>)}</div></div>
        <form className="ai-input" onSubmit={handleSubmit}><textarea ref={promptRef} value={prompt} rows={1} aria-label="AI에게 메시지 보내기" placeholder="예: 다음 학기 전공 필수를 먼저 배치해줘" disabled={isAiLoading || pendingChanges.length > 0} onChange={(event) => { setPrompt(event.target.value); event.currentTarget.style.height = "auto"; event.currentTarget.style.height = `${Math.min(event.currentTarget.scrollHeight, 96)}px`; }} onKeyDown={handlePromptKeyDown} /><button type="submit" aria-label="메시지 전송" title="메시지 전송" disabled={!prompt.trim() || isAiLoading || pendingChanges.length > 0}>{isAiLoading ? <LoaderCircle size={17} aria-hidden="true" /> : <Send size={17} aria-hidden="true" />}</button></form>
      </aside>
    </section>
  );
}

export function RoadmapPage() {
  return isMockStudentDataEnabled || isMockAuthEnabled ? <MockRoadmapPage /> : <ConnectedRoadmapPage />;
}
