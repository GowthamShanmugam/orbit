import type { Message, Session } from "@/types";
import { create } from "zustand";

interface SessionState {
  currentSession: Session | null;
  messages: Message[];
  setSession: (session: Session | null) => void;
  addMessage: (message: Message) => void;
  setMessages: (messages: Message[]) => void;
  clearSession: () => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  currentSession: null,
  messages: [],
  setSession: (currentSession) => set({ currentSession }),
  addMessage: (message) =>
    set((state) => {
      const i = state.messages.findIndex((m) => m.id === message.id);
      if (i >= 0) {
        const next = [...state.messages];
        next[i] = message;
        return { messages: next };
      }
      return { messages: [...state.messages, message] };
    }),
  setMessages: (messages) => set({ messages }),
  clearSession: () =>
    set({ currentSession: null, messages: [] }),
}));
