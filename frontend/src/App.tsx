import MainLayout from "@/components/Layout/MainLayout";
import ProjectDetail from "@/pages/ProjectDetail";
import ProjectList from "@/pages/ProjectList";
import SessionView from "@/pages/SessionView";
import { Navigate, Route, Routes } from "react-router-dom";

function ComingSoon() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
      <p className="text-lg font-medium text-[#e6edf3]">Coming soon</p>
      <p className="max-w-sm text-sm text-[#8b949e]">
        This workspace area is not wired up yet.
      </p>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<MainLayout />}>
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectList />} />
        <Route path="/projects/:id" element={<ProjectDetail />} />
        <Route
          path="/projects/:id/sessions/:sessionId"
          element={<SessionView />}
        />
        <Route path="/hub" element={<ComingSoon />} />
        <Route path="/workflows" element={<ComingSoon />} />
        <Route path="/secrets" element={<ComingSoon />} />
        <Route path="/settings" element={<ComingSoon />} />
      </Route>
    </Routes>
  );
}
