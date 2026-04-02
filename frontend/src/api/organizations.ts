import type { OrganizationSummary } from "@/types";
import { apiClient } from "./client";

export async function listOrganizations(): Promise<OrganizationSummary[]> {
  const { data } = await apiClient.get<OrganizationSummary[]>("/organizations");
  return data;
}

export async function createOrganization(input: {
  name: string;
  slug?: string;
}): Promise<OrganizationSummary> {
  const { data } = await apiClient.post<OrganizationSummary>(
    "/organizations/create",
    input,
  );
  return data;
}
