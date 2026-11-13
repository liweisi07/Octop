import { request } from "../request";

export interface ModelRoles {
  primary: string[];
  backup: string[];
  last_resort: string[];
  available_models: string[];
}

export const modelRolesApi = {
  get: () => request<ModelRoles>("/model-roles"),

  save: (roles: {
    primary: string[];
    backup: string[];
    last_resort: string[];
  }) =>
    request<ModelRoles>("/model-roles", {
      method: "PUT",
      body: JSON.stringify(roles),
    }),
};
