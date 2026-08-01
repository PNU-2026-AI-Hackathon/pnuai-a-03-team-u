import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { ArrowUp, ChevronRight, LoaderCircle, Plus, Trash2 } from "lucide-react";
import {
  chatWithRoadmapAgent,
  createRoadmapSession,
  deleteRoadmapSession,
  getCurrentRoadmap,
  listRoadmapSessions,
  type RoadmapChatSession,
} from "../api/roadmaps";
import { useAuth } from "../auth/AuthContext";
import { BrandMark } from "../components/layout/BrandMark";
import { activityTone, recommendedActivities } from "../data/recommendedActivities";
import { readProfileOverrides } from "../data/studentProfileStorage";

type ThreadMessage = { key: string; role: "user" | "assistant"; content: string };

const DAY = 24 * 60 * 60 * 1000;

function sessionLabel(session: RoadmapChatSession) {
  return session.title?.trim() || "제목 없는 대화";
}

/** 세션을 시안의 '오늘 / 이전 7일 / 이전' 묶음으로 나눈다. */
function groupSessions(sessions: RoadmapChatSession[]) {
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const todayStart = startOfToday.getTime();
  const weekAgo = todayStart - 7 * DAY;

  const groups: { label: string; items: RoadmapChatSession[] }[] = [
    { label: "오늘", items: [] },
    { label: "이전 7일", items: [] },
    { label: "이전", items: [] },
  ];

  for (const session of sessions) {
    const time = new Date(session.updated_at).getTime();
    if (Number.isNaN(time) || time >= todayStart) groups[0].items.push(session);
    else if (time >= weekAgo) groups[1].items.push(session);
    else groups[2].items.push(session);
  }

  return groups.filter((group) => group.items.length > 0);
}

function errorMessage(error: unknown, fallback: string) {
  if (typeof error === "object" && error !== null && "message" in error) {
    return String((error as { message: unknown }).message) || fallback;
  }
  return fallback;
}

export function ChatPage() {
  const { user } = useAuth();
  const [roadmapId, setRoadmapId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<RoadmapChatSession[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [thread, setThread] = useState<ThreadMessage[]>([]);
  const [prompt, setPrompt] = useState("");
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const threadRef = useRef<HTMLOListElement>(null);

  const displayName = readProfileOverrides()?.name ?? user?.name ?? "이도원";
  const groups = useMemo(() => groupSessions(sessions), [sessions]);
  const activeSession = sessions.find((session) => session.session_id === activeId) ?? null;

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        const roadmap = await getCurrentRoadmap();
        const list = await listRoadmapSessions(roadmap.id);
        if (cancelled) return;
        setRoadmapId(roadmap.id);
        setSessions(list);
        setActiveId(list[0]?.session_id ?? null);
      } catch (caught) {
        if (cancelled) return;
        setError(errorMessage(caught, "대화 세션을 불러오지 못했습니다."));
      } finally {
        if (!cancelled) setIsBootstrapping(false);
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const node = threadRef.current;
    if (!node) return;
    node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
  }, [thread]);

  const refreshSessions = useCallback(async (id: number) => {
    try {
      setSessions(await listRoadmapSessions(id));
    } catch {
      // 목록 갱신 실패는 대화 흐름을 막지 않는다.
    }
  }, []);

  async function handleCreateSession() {
    if (roadmapId === null) return;
    setError(null);
    try {
      const session = await createRoadmapSession(roadmapId);
      setSessions((current) => [session, ...current]);
      setActiveId(session.session_id);
      setThread([]);
    } catch (caught) {
      setError(errorMessage(caught, "새 대화를 만들지 못했습니다."));
    }
  }

  async function handleDeleteSession(sessionId: number) {
    if (roadmapId === null) return;
    setError(null);
    try {
      await deleteRoadmapSession(roadmapId, sessionId);
      setSessions((current) => current.filter((session) => session.session_id !== sessionId));
      if (activeId === sessionId) {
        setActiveId(null);
        setThread([]);
      }
    } catch (caught) {
      setError(errorMessage(caught, "대화를 삭제하지 못했습니다."));
    }
  }

  function handleSelectSession(sessionId: number) {
    if (sessionId === activeId) return;
    setActiveId(sessionId);
    setThread([]);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const message = prompt.trim();
    if (!message || roadmapId === null || isSending) return;

    setPrompt("");
    setError(null);
    setIsSending(true);
    setThread((current) => [
      ...current,
      { key: `user-${current.length}-${message.slice(0, 8)}`, role: "user", content: message },
    ]);

    try {
      const response = await chatWithRoadmapAgent(roadmapId, message, activeId ?? undefined);
      setActiveId(response.session_id);
      setThread((current) => [
        ...current,
        { key: `ai-${current.length}`, role: "assistant", content: response.reply },
      ]);
      await refreshSessions(roadmapId);
    } catch (caught) {
      setError(errorMessage(caught, "답변을 받지 못했습니다. 잠시 후 다시 시도해 주세요."));
    } finally {
      setIsSending(false);
    }
  }

  // 이전 세션을 고르면 서버에 쌓인 메시지가 있어도 아직 불러올 수 없다
  // (백엔드에 세션별 메시지 조회가 없음). 개수만 알려준다.
  const unloadedCount =
    thread.length === 0 && activeSession ? activeSession.message_count : 0;

  return (
    <div className="chat-screen">
      <aside className="chat-rail" aria-label="대화 세션 목록">
        <button
          className="chat-new-button"
          type="button"
          onClick={() => void handleCreateSession()}
          disabled={roadmapId === null}
        >
          <Plus size={24} aria-hidden="true" />
          <span>새 대화</span>
        </button>

        <div className="chat-session-groups">
          {isBootstrapping ? (
            <p className="chat-session-empty">대화 목록을 불러오는 중입니다…</p>
          ) : groups.length === 0 ? (
            <p className="chat-session-empty">아직 대화가 없습니다. 새 대화를 시작해 보세요.</p>
          ) : (
            groups.map((group) => (
              <section className="chat-session-group" key={group.label}>
                <h2>{group.label}</h2>
                <ul>
                  {group.items.map((session) => (
                    <li key={session.session_id}>
                      <button
                        className={`chat-session${session.session_id === activeId ? " active" : ""}`}
                        type="button"
                        aria-current={session.session_id === activeId ? "true" : undefined}
                        onClick={() => handleSelectSession(session.session_id)}
                      >
                        {sessionLabel(session)}
                      </button>
                      <button
                        className="chat-session-delete"
                        type="button"
                        aria-label={`${sessionLabel(session)} 대화 삭제`}
                        onClick={() => void handleDeleteSession(session.session_id)}
                      >
                        <Trash2 size={16} aria-hidden="true" />
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))
          )}
        </div>

        <NavLink className="chat-profile" to="/info">
          <span className="chat-profile-face">
            <BrandMark id="plan-u-face-chat-profile" />
          </span>
          <span className="chat-profile-name">
            <strong>{displayName} 님</strong>
            <span>나의 프로필 보기</span>
          </span>
          <ChevronRight size={32} aria-hidden="true" />
        </NavLink>
      </aside>

      <div className="chat-main">
        <div className="chat-stage">
          {thread.length > 0 ? (
            <ol className="chat-thread" ref={threadRef} aria-live="polite">
              {thread.map((message) => (
                <li className={`chat-bubble ${message.role}`} key={message.key}>
                  {message.content}
                </li>
              ))}
              {isSending ? (
                <li className="chat-bubble assistant is-pending">
                  <LoaderCircle size={18} aria-hidden="true" />
                  <span>답변을 작성하고 있습니다…</span>
                </li>
              ) : null}
            </ol>
          ) : (
            <div className="chat-intro">
              <span className="chat-intro-face">
                <BrandMark id="plan-u-face-chat-intro" />
              </span>
              <p className="chat-intro-title">무엇을 도와드릴까요?</p>
              <p className="chat-intro-sub">진로, 활동, 이력서 등 무엇이든 물어보세요</p>
              {unloadedCount > 0 ? (
                <p className="chat-intro-note">
                  이 대화에 저장된 메시지 {unloadedCount}개 · 지난 메시지 불러오기는 준비 중입니다
                </p>
              ) : null}
            </div>
          )}

          {error ? (
            <p className="chat-error" role="alert">
              {error}
            </p>
          ) : null}

          <form className="chat-composer" onSubmit={handleSubmit}>
            <input
              aria-label="AI에게 메시지 보내기"
              placeholder="메세지를 입력해 주세요."
              value={prompt}
              disabled={roadmapId === null || isSending}
              onChange={(event) => setPrompt(event.target.value)}
            />
            <button
              type="submit"
              aria-label="메시지 전송"
              disabled={!prompt.trim() || roadmapId === null || isSending}
            >
              <ArrowUp size={32} aria-hidden="true" />
            </button>
          </form>
        </div>

        <section className="chat-recommend">
          <header>
            <h2>맞춤 추천 활동</h2>
            <NavLink to="/activities">
              <Plus size={16} aria-hidden="true" />
              <span>전체보기</span>
            </NavLink>
          </header>
          <ul>
            {recommendedActivities.slice(0, 4).map((activity) => (
              <li className="chat-activity-card" key={activity.title}>
                <span className={`chat-activity-tag ${activityTone(activity.category)}`}>
                  {activity.category}
                </span>
                <strong>{activity.title}</strong>
                <p>{activity.description}</p>
                <span className="chat-activity-deadline">{activity.dDay}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
