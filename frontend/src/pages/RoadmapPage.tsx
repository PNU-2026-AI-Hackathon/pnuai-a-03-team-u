import { Check, ChevronLeft, ChevronRight, LoaderCircle, Pencil, Plus, RefreshCw, RotateCcw, Save, Send, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

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

export function RoadmapPage() {
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
      <section className="roadmap-head">
        <div>
          <p className="eyebrow">남은 요건</p>
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
                          <strong>{progress}%</strong>
                        </div>
                        <p className="requirement-credit-status">
                          <strong>{group.required}학점 중</strong>
                          <span>{remaining === 0 ? "모두 이수" : `${remaining}학점 남음`}</span>
                        </p>
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
                        <small>{group.earned} / {group.required}학점 이수</small>
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
                      {timelineTerm.items.map((item, itemIndex) => isEditingRoadmap ? (
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
                      ) : (
                        <li className="semester-course-row" key={item.name}>
                          <div>
                            <strong>{item.name}</strong>
                            <span>{item.category}</span>
                          </div>
                          <span className={`semester-course-status ${timelineStatusClassNames[item.status]}`}>
                            {item.status}
                          </span>
                        </li>
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
                <span>2026 교육과정 기준</span>
              </div>
              <div className="curriculum-flow">
                {curriculumFlow.map((group) => (
                  <article key={group.title}>
                    <span className="flow-step">{group.step}</span>
                    <h3>{group.title}</h3>
                    <ul>
                      {group.courses.map(([course, status]) => (
                        <li className={status} key={course}>{course}</li>
                      ))}
                    </ul>
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
    </section>
  );
}
