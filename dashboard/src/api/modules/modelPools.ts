import { request } from "../request";

export interface ModelPoolMember {
  ref: string;
  enabled: boolean;
  usable: boolean;
}

export interface ModelPool {
  model_id: string;
  enabled: boolean;
  members: ModelPoolMember[];
  fallbacks: string[];
}

export interface ModelPoolSaveItem {
  model_id: string;
  enabled: boolean;
  members: string[];
  fallbacks: string[];
}

export const modelPoolsApi = {
  list: () => request<{ pools: ModelPool[] }>("/model-pools"),

  save: (pools: ModelPoolSaveItem[]) =>
    request<{ pools: ModelPool[] }>("/model-pools", {
      method: "PUT",
      body: JSON.stringify({ pools }),
    }),
};
