import { useEffect, useState } from "react";
import type { MouseEvent } from "react";
import { BookOpen, CalendarDays, CircleHelp, Home, Mail, Map, Megaphone, MessageCircle } from "lucide-react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import {
  STUDENT_PROFILE_UPDATED_EVENT,
  readProfileOverrides,
} from "../../data/studentProfileStorage";
import { BrandMark } from "./BrandMark";
import { themeLabels, useThemeMode, type ThemeMode } from "./useThemeMode";

const ACADEMIC_CALENDAR_URL = "https://www.pusan.ac.kr/kor/CMS/Haksailjung/view.do?mCode=MN076";

/**
 * 외부 링크를 항상 새 창으로 연다. 미리보기 패널처럼 target="_blank"를 무시하는
 * 환경에서 서비스 화면이 통째로 교체되고 뒤로가기도 막히는 걸 막는다.
 */
function openInNewWindow(event: MouseEvent<HTMLAnchorElement>) {
  // 새 탭/새 창으로 여는 보조키 조합은 브라우저 기본 동작에 맡긴다.
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
  event.preventDefault();
  window.open(event.currentTarget.href, "_blank", "noopener,noreferrer");
}

const pageMeta: Record<string, { eyebrow: string; title: string }> = {
  "/": {
    eyebrow: "2026학년도 1학기",
    title: "Home",
  },
  "/roadmap": {
    eyebrow: "Academic Plan",
    title: "성장 로드맵",
  },
  "/info": {
    eyebrow: "Student Data",
    title: "내 정보",
  },
  "/timetable": {
    eyebrow: "2026년도 2학기",
    title: "시간표 작성",
  },
};

export function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logoutUser } = useAuth();
  const meta = pageMeta[location.pathname] ?? pageMeta["/"];
  const [collapsed, setCollapsed] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [themeOpen, setThemeOpen] = useState(false);
  const [profileOverrides, setProfileOverrides] = useState(readProfileOverrides);
  const { themeMode, setThemeMode } = useThemeMode();

  useEffect(() => {
    const refreshProfile = () => setProfileOverrides(readProfileOverrides());
    window.addEventListener(STUDENT_PROFILE_UPDATED_EVENT, refreshProfile);
    return () => window.removeEventListener(STUDENT_PROFILE_UPDATED_EVENT, refreshProfile);
  }, []);

  useEffect(() => {
    // 다른 화면에서 넘어온 바로가기는 해당 영역까지 스크롤한다.
    const anchorId = (location.state as { scrollTo?: string } | null)?.scrollTo;
    if (anchorId) {
      // 브라우저 스크롤 복원이 끝난 다음 프레임에 이동해야 덮이지 않는다.
      const frame = window.requestAnimationFrame(() => {
        document.getElementById(anchorId)?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      return () => window.cancelAnimationFrame(frame);
    }
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [location.pathname, location.state]);

  /** 상담 예약은 Home의 지도 교수 카드로 보낸다. */
  function goToAdvisorCard(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    if (location.pathname === "/") {
      document.getElementById("advisor")?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    navigate("/", { state: { scrollTo: "advisor" } });
  }

  const displayName = profileOverrides?.name ?? user?.name ?? "사용자";

  return (
    <div className={`app-shell${collapsed ? " sidebar-collapsed" : ""}`}>
      <aside className="sidebar" aria-label="주요 메뉴">
        <NavLink className="brand" to="/">
          <BrandMark id="plan-u-face-app" />
          <span>
            Plan <strong>U</strong>
          </span>
        </NavLink>

        <button
          className="sidebar-toggle"
          type="button"
          aria-label={collapsed ? "사이드 메뉴 펼치기" : "사이드 메뉴 접기"}
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((value) => !value)}
        >
          ‹
        </button>

        <nav className="nav-stack">
          <NavLink className={({ isActive }) => `nav-item${isActive ? " active" : ""}`} to="/" end>
            <span className="nav-icon"><Home size={19} strokeWidth={2.2} aria-hidden="true" /></span>
            <span>Home</span>
          </NavLink>
          <NavLink className={({ isActive }) => `nav-item${isActive ? " active" : ""}`} to="/roadmap">
            <span className="nav-icon"><Map size={19} strokeWidth={2.2} aria-hidden="true" /></span>
            <span>성장 로드맵</span>
          </NavLink>
          <NavLink
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            to="/timetable"
          >
            <span className="nav-icon"><CalendarDays size={19} strokeWidth={2.2} aria-hidden="true" /></span>
            <span>시간표 작성</span>
          </NavLink>
        </nav>

        <div className="sidebar-section">
          <p>바로가기</p>
          <a
            href={ACADEMIC_CALENDAR_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={openInNewWindow}
          >
            학사 일정
          </a>
          <a href="/" onClick={goToAdvisorCard}>상담 예약</a>
        </div>

        <NavLink className="mini-profile" to="/info" aria-label="나의 프로필 보기">
          <div className="avatar">{displayName.slice(0, 1)}</div>
          <div>
            <strong>{displayName} 님</strong>
            <span>나의 프로필 보기</span>
          </div>
        </NavLink>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">{meta.eyebrow}</p>
            <h1>{meta.title}</h1>
          </div>
          <div className="top-actions">
            <div
              className={`topbar-help${helpOpen ? " open" : ""}`}
              onMouseEnter={() => setHelpOpen(true)}
              onMouseLeave={() => setHelpOpen(false)}
              onKeyDown={(event) => {
                if (event.key === "Escape") setHelpOpen(false);
              }}
              onBlur={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                  setHelpOpen(false);
                }
              }}
            >
              <button
                className="topbar-help-button"
                type="button"
                aria-label="도움말 메뉴"
                aria-haspopup="dialog"
                aria-controls="topbar-help-menu"
                aria-expanded={helpOpen}
                onClick={() => setHelpOpen(true)}
                onFocus={() => setHelpOpen(true)}
              >
                <CircleHelp size={18} aria-hidden="true" />
              </button>
              <div
                className="topbar-help-menu"
                id="topbar-help-menu"
                role="dialog"
                aria-label="도움말 메뉴 안내"
              >
                <ul>
                  <li><CircleHelp size={15} aria-hidden="true" /><span>도움말</span></li>
                  <li><MessageCircle size={15} aria-hidden="true" /><span>의견 내기</span></li>
                  <li><Megaphone size={15} aria-hidden="true" /><span>공지사항</span></li>
                  <li><BookOpen size={15} aria-hidden="true" /><span>자주 묻는 질문</span></li>
                  <li><Mail size={15} aria-hidden="true" /><span>문의하기</span></li>
                </ul>
              </div>
            </div>
            <div className={`theme-picker${themeOpen ? " open" : ""}`}>
              <button
                className="theme-mode-button"
                type="button"
                aria-label={`현재 ${themeLabels[themeMode]} 모드, 클릭하면 테마가 변경됩니다`}
                aria-expanded={themeOpen}
                onClick={() => setThemeOpen((value) => !value)}
              >
                {themeLabels[themeMode]}
              </button>
              <div className="theme-menu" role="menu" aria-label="테마 선택">
                {(Object.keys(themeLabels) as ThemeMode[]).map((mode) => (
                  <button
                    className={themeMode === mode ? "selected" : ""}
                    key={mode}
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setThemeMode(mode);
                      setThemeOpen(false);
                    }}
                  >
                    {themeLabels[mode]}
                  </button>
                ))}
              </div>
            </div>
            {/* Figma 시안(175:1498)의 내 정보 칩: 아바타 + 라벨 */}
            <NavLink className="user-chip me-chip" to="/info">
              <span className="me-chip-avatar" aria-hidden="true">{displayName.slice(0, 1)}</span>
              내 정보
            </NavLink>
            <NavLink className="user-chip logout-chip" to="/auth" onClick={logoutUser}>
              로그아웃
            </NavLink>
          </div>
        </header>
        <div className="route-view" key={location.pathname}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
