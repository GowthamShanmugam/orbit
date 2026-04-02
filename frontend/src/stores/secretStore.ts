import type { ProjectSecret, ScanMatch } from "@/types";
import { create } from "zustand";

interface SecretState {
  secrets: ProjectSecret[];
  loading: boolean;
  scanWarnings: ScanMatch[];
  showScanPopup: boolean;
  setSecrets: (secrets: ProjectSecret[]) => void;
  addSecret: (secret: ProjectSecret) => void;
  removeSecret: (id: string) => void;
  updateSecret: (secret: ProjectSecret) => void;
  setLoading: (loading: boolean) => void;
  setScanWarnings: (warnings: ScanMatch[]) => void;
  setShowScanPopup: (show: boolean) => void;
  clearScanWarnings: () => void;
}

export const useSecretStore = create<SecretState>((set) => ({
  secrets: [],
  loading: false,
  scanWarnings: [],
  showScanPopup: false,
  setSecrets: (secrets) => set({ secrets }),
  addSecret: (secret) =>
    set((s) => ({ secrets: [secret, ...s.secrets] })),
  removeSecret: (id) =>
    set((s) => ({ secrets: s.secrets.filter((sec) => sec.id !== id) })),
  updateSecret: (secret) =>
    set((s) => ({
      secrets: s.secrets.map((sec) => (sec.id === secret.id ? secret : sec)),
    })),
  setLoading: (loading) => set({ loading }),
  setScanWarnings: (scanWarnings) =>
    set({ scanWarnings, showScanPopup: scanWarnings.length > 0 }),
  setShowScanPopup: (showScanPopup) => set({ showScanPopup }),
  clearScanWarnings: () =>
    set({ scanWarnings: [], showScanPopup: false }),
}));
