import MainLayout from "@/components/Layout/MainLayout";
import SecretScanner from "@/components/SecretVault/SecretScanner";
import VaultManager from "@/components/SecretVault/VaultManager";
import IntegrationsCatalog from "@/components/Skills/IntegrationsCatalog";
import SkillsCatalog from "@/components/Skills/SkillsCatalog";
import ProjectDetail from "@/pages/ProjectDetail";
import ProjectList from "@/pages/ProjectList";
import SessionView from "@/pages/SessionView";
import SettingsPage from "@/pages/SettingsPage";
import { listProjects } from "@/api/projects";
import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";

function SecretsPage() {
  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });

  const projects = projectsQuery.data ?? [];
  const firstProject = projects[0];

  return (
    <div className="mx-auto max-w-5xl p-8">
      {projectsQuery.isLoading ? (
        <div className="flex justify-center py-12 text-[var(--o-text-secondary)]">
          <span className="text-sm">Loading…</span>
        </div>
      ) : !firstProject ? (
        <div className="py-12 text-center text-sm text-[var(--o-text-tertiary)]">
          Create a project first to start managing secrets.
        </div>
      ) : (
        <VaultManager projectId={firstProject.id} />
      )}
    </div>
  );
}

export default function App() {
  return (
    <>
      <Routes>
        <Route element={<MainLayout />}>
          <Route path="/" element={<Navigate to="/projects" replace />} />
          <Route path="/projects" element={<ProjectList />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/projects/:id/sessions/:sessionId" element={<SessionView />} />
          <Route path="/integrations" element={<IntegrationsCatalog />} />
          <Route path="/skills" element={<SkillsCatalog />} />
          <Route path="/secrets" element={<SecretsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Routes>
      <SecretScanner />
    </>
  );
}
