import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import {
  STUDENT_PROFILE_UPDATED_EVENT,
  readProfileOverrides,
} from "../../data/studentProfileStorage";
import { BrandMark } from "./BrandMark";

const themeLabels = {
  auto: "자동",
  light: "라이트",
  dark: "다크",
} as const;

type ThemeMode = keyof typeof themeLabels;

const pageMeta: Record<string, { eyebrow: string; title: string }> = {
  "/": {
    eyebrow: "2026학년도 1학기",
    title: "Home",
  },
  "/roadmap": {
    eyebrow: "데이터사이언스전공",
    title: "성장 로드맵",
  },
  "/activities": {
    eyebrow: "개인별 추천",
    title: "추천 활동",
  },
  "/info": {
    eyebrow: "Student Data",
    title: "내 정보",
  },
};

function resolveTheme(mode: ThemeMode) {
  if (mode === "auto") {
    const hour = new Date().getHours();
    return hour >= 18 || hour < 6 ? "dark" : "light";
  }
  return mode;
}

export function AppLayout() {
  const location = useLocation();
  const { user, logoutUser } = useAuth();
  const meta = pageMeta[location.pathname] ?? pageMeta["/"];
  const [collapsed, setCollapsed] = useState(false);
  const [themeOpen, setThemeOpen] = useState(false);
  const [profileOverrides, setProfileOverrides] = useState(readProfileOverrides);
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    const saved = window.localStorage.getItem("planUThemeMode");
    return saved === "light" || saved === "dark" || saved === "auto" ? saved : "auto";
  });

  useEffect(() => {
    const resolved = resolveTheme(themeMode);
    document.body.classList.toggle("theme-dark", resolved === "dark");
    document.body.dataset.themeMode = themeMode;
    window.localStorage.setItem("planUThemeMode", themeMode);
  }, [themeMode]);

  useEffect(() => {
    const refreshProfile = () => setProfileOverrides(readProfileOverrides());
    window.addEventListener(STUDENT_PROFILE_UPDATED_EVENT, refreshProfile);
    return () => window.removeEventListener(STUDENT_PROFILE_UPDATED_EVENT, refreshProfile);
  }, []);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [location.pathname]);

  const displayName = profileOverrides?.name ?? user?.name ?? "이도원";

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
            <span className="nav-icon">⌂</span>
            <span>Home</span>
          </NavLink>
          <NavLink className={({ isActive }) => `nav-item${isActive ? " active" : ""}`} to="/roadmap">
            <span className="nav-icon">⌁</span>
            <span>성장 로드맵</span>
          </NavLink>
          <NavLink className={({ isActive }) => `nav-item${isActive ? " active" : ""}`} to="/activities">
            <span className="nav-icon">✦</span>
            <span>추천 활동</span>
          </NavLink>
          <a className="nav-item schedule-link" href="#schedule">
            <span className="nav-icon">▣</span>
            <span>시간표 작성</span>
          </a>
        </nav>

        <div className="sidebar-section">
          <p>바로가기</p>
          <a href="#calendar">학사 일정</a>
          <NavLink to="/activities">추천 활동</NavLink>
          <a href="#advisor">상담 예약</a>
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
            <button type="button" aria-label="도움말">
              ?
            </button>
            <NavLink className="user-chip logout-chip" to="/auth" onClick={logoutUser}>
              로그아웃
            </NavLink>
          </div>
        </header>
        <Outlet />
      </main>
    </div>
  );
}
