import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  CalendarDays,
  ChevronRight,
  ClipboardList,
  LineSquiggle,
  LogOut,
  PanelsTopLeft,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
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

/** 상단 네비 항목. `to`가 없으면 아직 화면이 없는 준비 중 메뉴다. */
const navEntries: { label: string; icon: LucideIcon; to?: string }[] = [
  { label: "성장 로드맵", icon: LineSquiggle, to: "/roadmap" },
  { label: "추천 활동", icon: Sparkles, to: "/activities" },
  { label: "시간표", icon: PanelsTopLeft },
  { label: "이력서 작성", icon: ClipboardList },
  { label: "달력", icon: CalendarDays },
];

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
    <div className="app-frame">
      <header className="topnav">
        <NavLink className="topnav-brand" to="/">
          <BrandMark id="plan-u-face-app" />
          <span>
            Plan <strong>U</strong>
          </span>
        </NavLink>

        <nav className="topnav-menu" aria-label="주요 메뉴">
          {navEntries.map(({ label, icon: Icon, to }) =>
            to ? (
              <NavLink
                key={label}
                className={({ isActive }) => `topnav-link${isActive ? " active" : ""}`}
                to={to}
              >
                <Icon size={20} aria-hidden="true" />
                <span>{label}</span>
              </NavLink>
            ) : (
              <span key={label} className="topnav-link is-pending" title="준비 중인 메뉴입니다">
                <Icon size={20} aria-hidden="true" />
                <span>{label}</span>
                <em>준비 중</em>
              </span>
            ),
          )}

          <span className="topnav-divider" aria-hidden="true" />

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

          <NavLink className="topnav-profile" to="/info" aria-label="나의 프로필 보기">
            <span className="avatar">{displayName.slice(0, 1)}</span>
            <span>{displayName} 님</span>
            <ChevronRight size={18} aria-hidden="true" />
          </NavLink>

          <NavLink className="topnav-link logout-link" to="/auth" onClick={logoutUser}>
            <LogOut size={20} aria-hidden="true" />
            <span>로그아웃</span>
          </NavLink>
        </nav>
      </header>

      <main className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">{meta.eyebrow}</p>
            <h1>{meta.title}</h1>
          </div>
        </header>
        <Outlet />
      </main>
    </div>
  );
}
