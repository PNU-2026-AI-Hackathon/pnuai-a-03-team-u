import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "../auth/AuthContext";
import { AppLayout } from "../components/layout/AppLayout";
import { ChatShell } from "../components/layout/ChatShell";
import { ActivitiesPage } from "../pages/ActivitiesPage";
import { AuthPage } from "../pages/AuthPage";
import { ChatPage } from "../pages/ChatPage";
import { DashboardPage } from "../pages/DashboardPage";
import { ForgotPasswordPage } from "../pages/ForgotPasswordPage";
import { InfoPage } from "../pages/InfoPage";
import { OnboardingPage } from "../pages/OnboardingPage";
import { RoadmapPage } from "../pages/RoadmapPage";

function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated, isBootstrapping } = useAuth();
  const location = useLocation();

  if (isBootstrapping) return null;
  if (!isAuthenticated) {
    return <Navigate to="/auth" replace state={{ from: location.pathname }} />;
  }
  return children;
}

function GuestOnly({ children }: { children: ReactNode }) {
  const { isAuthenticated, isBootstrapping } = useAuth();

  if (isBootstrapping) return null;
  if (isAuthenticated) return <Navigate to="/" replace />;
  return children;
}

export function AppRouter() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/auth" element={<GuestOnly><AuthPage /></GuestOnly>} />
          <Route path="/forgot-password" element={<GuestOnly><ForgotPasswordPage /></GuestOnly>} />
          <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
            <Route index element={<DashboardPage />} />
            <Route path="/activities" element={<ActivitiesPage />} />
            <Route path="/info" element={<InfoPage />} />
            <Route path="/roadmap" element={<RoadmapPage />} />
          </Route>
          {/* 회원가입 STEP 2·3. 학사정보 불러오기가 인증을 요구해서 로그인 뒤에 이어진다. */}
          <Route path="/onboarding" element={<RequireAuth><OnboardingPage /></RequireAuth>} />
          {/* AI 대화만 시안대로 상단 네비 셸을 쓴다. */}
          <Route element={<RequireAuth><ChatShell /></RequireAuth>}>
            <Route path="/chat" element={<ChatPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
