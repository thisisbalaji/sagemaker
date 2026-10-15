import type { ReactNode } from "react";

const STATUS_LABELS: Record<string, string> = {
  PENDING: "Pending",
  PROVISIONING: "Setting up",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  FAILED: "Failed",
  InService: "Ready",
  Pending: "Creating",
  Updating: "Updating",
  NotFound: "Missing",
};

const STATUS_TONES: Record<string, string> = {
  APPROVED: "ok",
  InService: "ok",
  PENDING: "warn",
  PROVISIONING: "warn",
  Pending: "warn",
  Updating: "warn",
  REJECTED: "bad",
  FAILED: "bad",
  NotFound: "bad",
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="badge">No access</span>;
  return <span className={`badge ${STATUS_TONES[status] ?? ""}`}>{STATUS_LABELS[status] ?? status}</span>;
}

export function ErrorBanner({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="banner error" role="alert">
      {error}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function formatDate(iso?: string) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function errorMessage(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}
