import { create } from "zustand";

interface ContextHubState {
  searchQuery: string;
  selectedCategory: string | null;
  setSearchQuery: (q: string) => void;
  setSelectedCategory: (c: string | null) => void;
}

export const useContextHubStore = create<ContextHubState>((set) => ({
  searchQuery: "",
  selectedCategory: null,
  setSearchQuery: (searchQuery) => set({ searchQuery }),
  setSelectedCategory: (selectedCategory) => set({ selectedCategory }),
}));
