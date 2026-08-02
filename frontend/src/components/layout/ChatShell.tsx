import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  CalendarDays,
  ClipboardList,
  LineSquiggle,
  LogOut,
  PanelsTopLeft,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { BrandMark } from "./BrandMark";
import { themeLabels, useThemeMode, type ThemeMode } from "./useThemeMode";

/**
 * AI 대화 화면 전용 셸. 시안 22:387만 좌측 사이드바 대신 상단 가로 네비를 쓰기 때문에
 * 나머지 화면(AppLayout)과 분리해 둔다. `to`가 없는 항목은 아직 화면이 없는 준비 중 메뉴다.
 */
const navEntries: { label: string; icon: LucideIcon; to?: string }[] = [
  { label: "성장 로드맵", icon: LineSquiggle, to: "/roadmap" },
  { label: "추천 활동", icon: Sparkles, to: "/activities" },
  { label: "시간표", icon: PanelsTopLeft },
  { label: "이력서 작성", icon: ClipboardList },
  { label: "달력", icon: CalendarDays },
];

export function ChatShell() {
  const { logoutUser } = useAuth();
  const { themeMode, setThemeMode } = useThemeMode();
  const [themeOpen, setThemeOpen] = useState(false);

  return (
    <div className="app-frame">
      <header className="topnav">
        <NavLink className="topnav-brand" to="/">
          <BrandMark id="plan-u-face-chat-shell" />
          <span>
            Plan <strong>U</strong>
          </span>
        </NavLink>

        <nav className="topnav-menu" aria-label="주요 메뉴">
          {navEntries.map(({ label, icon: Icon, to }) =>
            to ? (
              <NavLink key={label} className="topnav-link" to={to}>
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

          <NavLink className="topnav-link logout-link" to="/auth" onClick={logoutUser}>
            <LogOut size={20} aria-hidden="true" />
            <span>로그아웃</span>
          </NavLink>
        </nav>
      </header>

      <Outlet />
    </div>
  );
}
