import HubCatalog from "@/components/ContextHub/HubCatalog";
import PackCreator from "@/components/ContextHub/PackCreator";
import PackDetail from "@/components/ContextHub/PackDetail";
import MainLayout from "@/components/Layout/MainLayout";
import SecretScanner from "@/components/SecretVault/SecretScanner";
import VaultManager from "@/components/SecretVault/VaultManager";
import ProjectDetail from "@/pages/ProjectDetail";
import ProjectList from "@/pages/ProjectList";
import SessionView from "@/pages/SessionView";
import { listProjects } from "@/api/projects";
import { useProjectStore } from "@/stores/projectStore";
import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

function ComingSoon() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
      <p className="text-lg font-medium text-[var(--o-text)]">Coming soon</p>
      <p className="max-w-sm text-sm text-[var(--o-text-secondary)]">
        This workspace area is not wired up yet.
      </p>
    </div>
  );
}

function SecretsPage() {
  const project = useProjectStore((s) => s.currentProject);
  const setCurrentProject = useProjectStore((s) => s.setCurrentProject);
  const navigate = useNavigate();

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });

  const projects = projectsQuery.data ?? [];

  if (project) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center gap-3 border-b border-[var(--o-border)] bg-[var(--o-bg)] px-6 py-2">
          <button
            type="button"
            onClick={() => setCurrentProject(null)}
            className="text-xs text-[var(--o-text-secondary)] transition-colors hover:text-[var(--o-accent)]"
          >
            All Projects
          </button>
          <span className="text-xs text-[var(--o-border)]">/</span>
          <span className="text-xs font-medium text-[var(--o-text)]">{project.name}</span>
        </div>
        <div className="min-h-0 flex-1">
          <VaultManager projectId={project.id} />
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-md p-8">
      <h2 className="mb-4 text-lg font-semibold text-[var(--o-text)]">Select a project</h2>
      <p className="mb-6 text-sm text-[var(--o-text-secondary)]">
        Choose a project to manage its secrets.
      </p>
      {projects.length === 0 ? (
        <p className="text-sm text-[var(--o-border-subtle)]">No projects found.</p>
      ) : (
        <ul className="divide-y divide-[var(--o-border)] overflow-hidden rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)]">
          {projects.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => setCurrentProject(p)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm text-[var(--o-text)] transition-colors hover:bg-[var(--o-bg-subtle)]"
              >
                {p.name}
              </button>
            </li>
          ))}
        </ul>
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
          <Route
            path="/projects/:id/sessions/:sessionId"
            element={<SessionView />}
          />
          <Route path="/projects/:id/secrets" element={<ProjectSecretsPage />} />
          <Route path="/hub" element={<HubCatalog />} />
          <Route path="/hub/create" element={<PackCreator />} />
          <Route path="/hub/:packId" element={<PackDetail />} />
          <Route path="/workflows" element={<ComingSoon />} />
          <Route path="/secrets" element={<SecretsPage />} />
          <Route path="/settings" element={<ComingSoon />} />
        </Route>
      </Routes>
      <SecretScanner />
    </>
  );
}

function ProjectSecretsPage() {
  const project = useProjectStore((s) => s.currentProject);
  if (!project) return null;
  return <VaultManager projectId={project.id} />;
}
