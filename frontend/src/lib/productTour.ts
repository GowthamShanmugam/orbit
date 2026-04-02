const STORAGE_KEY = "orbit_product_tour_v1_done";

export function isProductTourCompleted(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return true;
  }
}

export function markProductTourCompleted(): void {
  try {
    localStorage.setItem(STORAGE_KEY, "1");
  } catch {
    /* ignore */
  }
}

export function clearProductTourCompletion(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export const PRODUCT_TOUR_REPLAY_EVENT = "orbit-replay-product-tour";

export function requestProductTourReplay(): void {
  clearProductTourCompletion();
  window.dispatchEvent(new Event(PRODUCT_TOUR_REPLAY_EVENT));
}
