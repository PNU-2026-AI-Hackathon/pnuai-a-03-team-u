import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../auth/AuthContext";
import { AppLayout } from "../components/layout/AppLayout";
import { ActivitiesPage } from "../pages/ActivitiesPage";
import { AuthPage } from "../pages/AuthPage";
import { DashboardPage } from "../pages/DashboardPage";
import { InfoPage } from "../pages/InfoPage";
import { RoadmapPage } from "../pages/RoadmapPage";

export function AppRouter() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
          <Route element={<AppLayout />}>
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
