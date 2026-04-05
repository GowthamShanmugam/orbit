import type { OrbiState } from "@/components/Orbi/OrbiDog";
import { create } from "zustand";

const LS_KEY = "orbit-orbi-prefs";
const FLASH_DURATION_MS = 3_000;

interface OrbiPrefs {
  visible: boolean;
  name: string;
}

type PassiveState = "idle" | "reading" | "sleeping";
const PASSIVE_STATES = new Set<OrbiState>(["idle", "reading", "sleeping"]);

interface OrbiStoreState extends OrbiPrefs {
  state: OrbiState;
  baseState: PassiveState;

  setState: (s: OrbiState) => void;
  setBaseState: (s: PassiveState) => void;
  revertToBase: () => void;
  flashHappy: () => void;
  flashError: () => void;

  setVisible: (v: boolean) => void;
  setName: (n: string) => void;
}

function loadPrefs(): OrbiPrefs {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) {
      const p = JSON.parse(raw) as Partial<OrbiPrefs>;
      return {
        visible: p.visible ?? true,
        name: p.name || "Orbi",
      };
    }
  } catch {
    /* ignore */
  }
  return { visible: true, name: "Orbi" };
}

function savePrefs(p: OrbiPrefs) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(p));
  } catch {
    /* quota */
  }
}

let flashTimer: ReturnType<typeof setTimeout> | null = null;

export const useOrbiStore = create<OrbiStoreState>((set, get) => {
  const prefs = loadPrefs();

  return {
    ...prefs,
    state: "idle",
    baseState: "idle",

    setState: (s) => {
      if (flashTimer) {
        clearTimeout(flashTimer);
        flashTimer = null;
      }
      set({ state: s });
    },

    setBaseState: (s) => {
      set({ baseState: s });
      if (PASSIVE_STATES.has(get().state)) {
        set({ state: s });
      }
    },

    revertToBase: () => {
      if (flashTimer) {
        clearTimeout(flashTimer);
        flashTimer = null;
      }
      set({ state: get().baseState });
    },

    flashHappy: () => {
      if (flashTimer) clearTimeout(flashTimer);
      set({ state: "happy" });
      flashTimer = setTimeout(() => {
        if (get().state === "happy") set({ state: get().baseState });
        flashTimer = null;
      }, FLASH_DURATION_MS);
    },

    flashError: () => {
      if (flashTimer) clearTimeout(flashTimer);
      set({ state: "error" });
      flashTimer = setTimeout(() => {
        if (get().state === "error") set({ state: get().baseState });
        flashTimer = null;
      }, FLASH_DURATION_MS);
    },

    setVisible: (visible) => {
      set({ visible });
      savePrefs({ ...get(), visible });
    },
    setName: (name) => {
      set({ name });
      savePrefs({ ...get(), name });
    },
  };
});
