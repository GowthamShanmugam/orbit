import type { Project } from "@/types";
import { create } from "zustand";

interface ProjectState {
  currentProject: Project | null;
  setCurrentProject: (project: Project | null) => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
  currentProject: null,
  setCurrentProject: (currentProject) => set({ currentProject }),
}));
