import type { ActivityAction, Message, Thread } from "@/types";
import { create } from "zustand";

interface ThreadState {
  activeThread: Thread | null;
  parentMessage: Message | null;
  threadMessages: Message[];
  /** Map from parent_message_id to Thread for badge lookups. */
  threadsByMessage: Record<string, Thread>;

  isStreaming: boolean;
  streamingText: string;
  actions: ActivityAction[];

  openThread: (thread: Thread, parentMessage: Message) => void;
  closeThread: () => void;
  setThreadMessages: (messages: Message[]) => void;
  addThreadMessage: (message: Message) => void;
  registerThread: (thread: Thread) => void;
  registerThreads: (threads: Thread[]) => void;
  removeThread: (threadId: string) => void;

  setStreaming: (streaming: boolean) => void;
  appendStreamText: (text: string) => void;
  resetStreamText: () => void;
  addAction: (action: ActivityAction) => void;
  updateAction: (id: string, patch: Partial<ActivityAction>) => void;
  clearActions: () => void;
}

let threadActionCounter = 0;

export function nextThreadActionId(): string {
  return `thread-action-${++threadActionCounter}`;
}

export const useThreadStore = create<ThreadState>((set) => ({
  activeThread: null,
  parentMessage: null,
  threadMessages: [],
  threadsByMessage: {},

  isStreaming: false,
  streamingText: "",
  actions: [],

  openThread: (thread, parentMessage) =>
    set({ activeThread: thread, parentMessage, threadMessages: [] }),

  closeThread: () =>
    set({
      activeThread: null,
      parentMessage: null,
      threadMessages: [],
      isStreaming: false,
      streamingText: "",
      actions: [],
    }),

  setThreadMessages: (threadMessages) => set({ threadMessages }),

  addThreadMessage: (message) =>
    set((s) => {
      const i = s.threadMessages.findIndex((m) => m.id === message.id);
      if (i >= 0) {
        const next = [...s.threadMessages];
        next[i] = message;
        return { threadMessages: next };
      }
      return { threadMessages: [...s.threadMessages, message] };
    }),

  registerThread: (thread) =>
    set((s) => ({
      threadsByMessage: {
        ...s.threadsByMessage,
        [thread.parent_message_id]: thread,
      },
    })),

  registerThreads: (threads) =>
    set((s) => {
      const map = { ...s.threadsByMessage };
      for (const t of threads) {
        map[t.parent_message_id] = t;
      }
      return { threadsByMessage: map };
    }),

  removeThread: (threadId) =>
    set((s) => {
      const map = { ...s.threadsByMessage };
      for (const [key, t] of Object.entries(map)) {
        if (t.id === threadId) {
          delete map[key];
          break;
        }
      }
      return {
        threadsByMessage: map,
        activeThread:
          s.activeThread?.id === threadId ? null : s.activeThread,
        parentMessage:
          s.activeThread?.id === threadId ? null : s.parentMessage,
        threadMessages:
          s.activeThread?.id === threadId ? [] : s.threadMessages,
      };
    }),

  setStreaming: (isStreaming) => set({ isStreaming }),
  appendStreamText: (text) =>
    set((s) => ({ streamingText: s.streamingText + text })),
  resetStreamText: () => set({ streamingText: "" }),
  addAction: (action) =>
    set((s) => ({ actions: [...s.actions, action] })),
  updateAction: (id, patch) =>
    set((s) => ({
      actions: s.actions.map((a) => (a.id === id ? { ...a, ...patch } : a)),
    })),
  clearActions: () => set({ actions: [] }),
}));
