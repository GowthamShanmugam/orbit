import type { ActivityAction, SecretWarning } from "@/types";
import { create } from "zustand";

interface ActivityState {
  actions: ActivityAction[];
  isStreaming: boolean;
  streamingText: string;
  secretWarnings: SecretWarning[];
  elapsedSec: number;

  addAction: (action: ActivityAction) => void;
  updateAction: (id: string, patch: Partial<ActivityAction>) => void;
  clearActions: () => void;
  setStreaming: (streaming: boolean) => void;
  appendStreamText: (text: string) => void;
  resetStreamText: () => void;
  setSecretWarnings: (warnings: SecretWarning[]) => void;
  setElapsed: (sec: number) => void;
  reset: () => void;
}

let actionCounter = 0;

export const useActivityStore = create<ActivityState>((set) => ({
  actions: [],
  isStreaming: false,
  streamingText: "",
  secretWarnings: [],
  elapsedSec: 0,

  addAction: (action) =>
    set((s) => ({ actions: [...s.actions, action] })),

  updateAction: (id, patch) =>
    set((s) => ({
      actions: s.actions.map((a) =>
        a.id === id ? { ...a, ...patch } : a,
      ),
    })),

  clearActions: () => set({ actions: [] }),
  setStreaming: (isStreaming) => set({ isStreaming }),
  appendStreamText: (text) =>
    set((s) => ({ streamingText: s.streamingText + text })),
  resetStreamText: () => set({ streamingText: "" }),
  setSecretWarnings: (secretWarnings) => set({ secretWarnings }),
  setElapsed: (elapsedSec) => set({ elapsedSec }),

  reset: () =>
    set({
      actions: [],
      isStreaming: false,
      streamingText: "",
      secretWarnings: [],
      elapsedSec: 0,
    }),
}));

export function nextActionId(): string {
  return `action-${++actionCounter}`;
}
