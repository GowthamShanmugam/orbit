import type { ProjectSecret, ScanMatch } from "@/types";
import { create } from "zustand";

interface SecretState {
  secrets: ProjectSecret[];
  scanWarnings: ScanMatch[];
  showScanPopup: boolean;
  setSecrets: (secrets: ProjectSecret[]) => void;
  setScanWarnings: (warnings: ScanMatch[]) => void;
  clearScanWarnings: () => void;
}

export const useSecretStore = create<SecretState>((set) => ({
  secrets: [],
  scanWarnings: [],
  showScanPopup: false,
  setSecrets: (secrets) => set({ secrets }),
  setScanWarnings: (scanWarnings) => set({ scanWarnings, showScanPopup: scanWarnings.length > 0 }),
  clearScanWarnings: () => set({ scanWarnings: [], showScanPopup: false }),
}));
