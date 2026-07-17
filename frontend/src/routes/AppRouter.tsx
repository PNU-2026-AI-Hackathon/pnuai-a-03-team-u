import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "../auth/AuthContext";
import { AppLayout } from "../components/layout/AppLayout";
import { ActivitiesPage } from "../pages/ActivitiesPage";
import { AuthPage } from "../pages/AuthPage";
import { DashboardPage } from "../pages/DashboardPage";
import { InfoPage } from "../pages/InfoPage";
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
          <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
            <Route index element={<DashboardPage />} />
            <Route path="/activities" element={<ActivitiesPage />} />
            <Route path="/info" element={<InfoPage />} />
            <Route path="/roadmap" element={<RoadmapPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
