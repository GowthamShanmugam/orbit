import { apiClient } from "./client";

export type UsageBucket = {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  estimated_cost_usd: number;
  calls: number;
};

export type UsageSummary = {
  currency: string;
  is_estimate: boolean;
  pricing_note: string;
  provider: string;
  totals: {
    today: UsageBucket;
    this_month: UsageBucket;
    all_time: UsageBucket;
  };
  by_model: Array<UsageBucket & { model: string }>;
  by_project: Array<UsageBucket & { project_id: string | null; project_name: string }>;
  recent_days: Array<UsageBucket & { date: string }>;
  empty: boolean;
};

export async function getUsageSummary(): Promise<UsageSummary> {
  const { data } = await apiClient.get<UsageSummary>("/settings/usage");
  return data;
}
