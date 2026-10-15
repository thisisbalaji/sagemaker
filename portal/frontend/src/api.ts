export type User = {
  user_id: string;
  display_name: string;
  email: string;
  admin_domains: string[];
  is_admin: boolean;
};

export type MockUser = { user_id: string; display_name: string; is_admin: boolean };

export type Domain = {
  domain_id: string;
  name: string;
  status: string;
  auth_mode: string;
  is_admin: boolean;
};

export type RequestStatus = "PENDING" | "PROVISIONING" | "APPROVED" | "REJECTED" | "FAILED";

export type Project = {
  project_id: string;
  domain_id: string;
  name: string;
  description: string;
  created_at: string;
  my_status: RequestStatus | null;
};

export type AdminProject = Omit<Project, "my_status"> & {
  domain_name: string;
  role_name: string;
  role_arn: string;
  created_by: string;
};

export type AccessRequest = {
  project_id: string;
  project_name: string;
  domain_id: string;
  domain_name?: string;
  user_id: string;
  user_display_name?: string;
  user_email?: string;
  status: RequestStatus;
  reason: string;
  requested_at: string;
  decided_by?: string;
  decided_at?: string;
  decision_note?: string;
  error?: string | null;
  user_profile_name?: string;
  profile_status?: string;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `Request failed (${res.status})`;
    throw new ApiError(res.status, message);
  }
  return data as T;
}

const enc = encodeURIComponent;

export const api = {
  me: () => call<User>("GET", "/api/me"),
  mockUsers: () => call<MockUser[]>("GET", "/api/auth/users"),
  login: (userId: string) => call("POST", "/api/auth/login", { user_id: userId }),
  logout: () => call("POST", "/api/auth/logout"),

  domains: () => call<Domain[]>("GET", "/api/domains"),
  projects: (domainId: string) => call<Project[]>("GET", `/api/domains/${enc(domainId)}/projects`),
  requestAccess: (projectId: string, reason: string) =>
    call<AccessRequest>("POST", `/api/projects/${enc(projectId)}/requests`, { reason }),
  myRequests: () => call<AccessRequest[]>("GET", "/api/me/requests"),

  admin: {
    projects: () => call<AdminProject[]>("GET", "/api/admin/projects"),
    createProject: (domainId: string, name: string, description: string) =>
      call<AdminProject>("POST", "/api/admin/projects", { domain_id: domainId, name, description }),
    requests: (status: RequestStatus) => call<AccessRequest[]>("GET", `/api/admin/requests?status=${status}`),
    approve: (projectId: string, userId: string) =>
      call<AccessRequest>("POST", `/api/admin/requests/${enc(projectId)}/${enc(userId)}/approve`),
    reject: (projectId: string, userId: string, note: string) =>
      call<AccessRequest>("POST", `/api/admin/requests/${enc(projectId)}/${enc(userId)}/reject`, { note }),
  },
};
