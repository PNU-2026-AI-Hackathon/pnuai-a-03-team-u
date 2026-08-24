import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "../auth/AuthContext";
import { hasActiveSignupFlow } from "../auth/signupFlow";
import { AppLayout } from "../components/layout/AppLayout";
import { AuthPage } from "../pages/AuthPage";
import { DashboardPage } from "../pages/DashboardPage";
import { ForgotPasswordPage } from "../pages/ForgotPasswordPage";
import { InfoPage } from "../pages/InfoPage";
import { OnboardingPage } from "../pages/OnboardingPage";
import { PrivacyPolicyPage } from "../pages/PrivacyPolicyPage";
import { ResetPasswordPage } from "../pages/ResetPasswordPage";
import { RoadmapPage } from "../pages/RoadmapPage";
import { TimetablePage } from "../pages/TimetablePage";

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
  const location = useLocation();
  const isReturningToSignup = location.pathname === "/auth" && hasActiveSignupFlow();

  if (isBootstrapping) return null;
  if (isAuthenticated && !isReturningToSignup) return <Navigate to="/" replace />;
  return children;
}

export function AppRouter() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/auth" element={<GuestOnly><AuthPage /></GuestOnly>} />
          <Route path="/forgot-password" element={<GuestOnly><ForgotPasswordPage /></GuestOnly>} />
          {/* 메일 링크로 들어오는 재설정 화면. 로그인 상태면 홈으로 보낸다. */}
          <Route path="/reset-password" element={<GuestOnly><ResetPasswordPage /></GuestOnly>} />
          {/* 회원가입 동의 체크박스에서 새 탭으로 여는 정책 문서. 로그인 여부와 무관하게 열람 가능해야
              해서 GuestOnly/RequireAuth 어느 쪽으로도 감싸지 않는다. */}
          <Route path="/privacy" element={<PrivacyPolicyPage />} />
          <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
            <Route index element={<DashboardPage />} />
            <Route path="/info" element={<InfoPage />} />
            <Route path="/roadmap" element={<RoadmapPage />} />
            <Route path="/timetable" element={<TimetablePage />} />
          </Route>
          {/* 회원가입 STEP 2·3. 학사정보 불러오기가 인증을 요구해서 로그인 뒤에 이어진다. */}
          <Route path="/onboarding" element={<RequireAuth><OnboardingPage /></RequireAuth>} />
          {/* 추천 활동(/activities)과 AI 대화(/chat)는 메뉴와 함께 라우트도 내렸다.
              메뉴만 빼면 주소로 여전히 들어갈 수 있고, 로드맵 안의 AI 상담이
              남아 있어 대화 기능 자체가 사라지는 것은 아니다.
              화면 코드(ActivitiesPage/ChatPage/ChatShell)는 되살리기 쉽도록 남겨둔다. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
