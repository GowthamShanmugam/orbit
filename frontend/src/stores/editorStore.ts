import { create } from "zustand";

export interface EditorTab {
  id: string;
  repoId: string;
  repoName: string;
  path: string;
  language: string;
  content: string;
  totalLines: number;
}

interface EditorState {
  tabs: EditorTab[];
  activeTabId: string | null;

  openFile: (tab: Omit<EditorTab, "id">) => void;
  closeTab: (id: string) => void;
  setActiveTab: (id: string | null) => void;
  clearTabs: () => void;
}

function makeTabId(repoId: string, path: string) {
  return `${repoId}::${path}`;
}

export const useEditorStore = create<EditorState>((set, get) => ({
  tabs: [],
  activeTabId: null,

  openFile: (tab) => {
    const id = makeTabId(tab.repoId, tab.path);
    const existing = get().tabs.find((t) => t.id === id);
    if (existing) {
      set({ activeTabId: id });
      return;
    }
    set((s) => ({
      tabs: [...s.tabs, { ...tab, id }],
      activeTabId: id,
    }));
  },

  closeTab: (id) => {
    set((s) => {
      const next = s.tabs.filter((t) => t.id !== id);
      let nextActive = s.activeTabId;
      if (s.activeTabId === id) {
        const idx = s.tabs.findIndex((t) => t.id === id);
        nextActive = next[Math.min(idx, next.length - 1)]?.id ?? null;
      }
      return { tabs: next, activeTabId: nextActive };
    });
  },

  setActiveTab: (id) => set({ activeTabId: id }),
  clearTabs: () => set({ tabs: [], activeTabId: null }),
}));
