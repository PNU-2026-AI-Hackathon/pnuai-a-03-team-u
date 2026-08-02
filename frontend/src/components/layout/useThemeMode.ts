import { useEffect, useState } from "react";

export const themeLabels = {
  auto: "자동",
  light: "라이트",
  dark: "다크",
} as const;

export type ThemeMode = keyof typeof themeLabels;

function resolveTheme(mode: ThemeMode) {
  if (mode === "auto") {
    const hour = new Date().getHours();
    return hour >= 18 || hour < 6 ? "dark" : "light";
  }
  return mode;
}

/** 사이드바 셸과 AI 대화 셸이 같은 테마 상태를 쓰도록 뽑아둔 훅. */
export function useThemeMode() {
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

  return { themeMode, setThemeMode };
}
