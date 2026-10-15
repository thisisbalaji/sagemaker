import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type AccessRequest, type AdminProject, type Domain, type RequestStatus } from "../api";
import { Empty, ErrorBanner, StatusBadge, errorMessage, formatDate } from "../components";

type Tab = "requests" | "projects";

export default function Admin() {
  const [tab, setTab] = useState<Tab>("requests");
  return (
    <>
      <h1>Admin</h1>
      <p className="muted">Approve project access and manage projects for the domains you administer.</p>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "requests"} className={tab === "requests" ? "active" : ""} onClick={() => setTab("requests")}>
          Access requests
        </button>
        <button role="tab" aria-selected={tab === "projects"} className={tab === "projects" ? "active" : ""} onClick={() => setTab("projects")}>
          Projects
        </button>
      </div>
      {tab === "requests" ? <Requests /> : <Projects />}
    </>
  );
}

const STATUSES: RequestStatus[] = ["PENDING", "FAILED", "APPROVED", "REJECTED"];

function Requests() {
  const [status, setStatus] = useState<RequestStatus>("PENDING");
  const [rows, setRows] = useState<AccessRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const load = useCallback(() => {
    setRows(null);
    api.admin.requests(status).then(setRows).catch((e) => setError(errorMessage(e)));
  }, [status]);

  useEffect(load, [load]);

  async function act(r: AccessRequest, action: "approve" | "reject") {
    const key = `${r.project_id}/${r.user_id}`;
    setBusyKey(key);
    setError(null);
    try {
      if (action === "approve") await api.admin.approve(r.project_id, r.user_id);
      else await api.admin.reject(r.project_id, r.user_id, note);
      setRejecting(null);
      setNote("");
      load();
    } catch (e) {
      setError(errorMessage(e));
      load();
    } finally {
      setBusyKey(null);
    }
  }

  const actionable = status === "PENDING" || status === "FAILED";

  return (
    <section className="panel">
      <div className="page-head">
        <label className="inline">
          Show
          <select value={status} onChange={(e) => setStatus(e.target.value as RequestStatus)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.charAt(0) + s.slice(1).toLowerCase()}
              </option>
            ))}
          </select>
        </label>
        <button className="secondary" onClick={load}>
          Refresh
        </button>
      </div>
      <ErrorBanner error={error} />
      {rows === null && !error && <p className="muted">Loading…</p>}
      {rows?.length === 0 && <Empty>No {status.toLowerCase()} requests.</Empty>}
      {rows && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Project</th>
                <th>Reason</th>
                <th>Requested</th>
                <th>Status</th>
                {actionable && <th aria-label="Actions" />}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const key = `${r.project_id}/${r.user_id}`;
                return (
                  <tr key={key}>
                    <td>
                      <strong>{r.user_display_name}</strong>
                      <div className="muted">{r.user_email ?? r.user_id}</div>
                    </td>
                    <td>
                      {r.project_name}
                      <div className="muted">{r.domain_name}</div>
                    </td>
                    <td>{r.reason || <span className="muted">—</span>}</td>
                    <td>{formatDate(r.requested_at)}</td>
                    <td>
                      <StatusBadge status={r.status} />
                      {r.error && <div className="error-text">{r.error}</div>}
                      {r.user_profile_name && <div className="muted mono">{r.user_profile_name}</div>}
                    </td>
                    {actionable && (
                      <td className="actions">
                        {rejecting === key ? (
                          <form
                            className="inline-form"
                            onSubmit={(e) => {
                              e.preventDefault();
                              act(r, "reject");
                            }}
                          >
                            <input
                              aria-label="Reason for rejecting"
                              placeholder="Note to the user (optional)"
                              value={note}
                              maxLength={500}
                              onChange={(e) => setNote(e.target.value)}
                            />
                            <div className="row">
                              <button type="submit" className="danger" disabled={busyKey === key}>
                                Reject
                              </button>
                              <button type="button" className="secondary" onClick={() => setRejecting(null)}>
                                Cancel
                              </button>
                            </div>
                          </form>
                        ) : (
                          <div className="row">
                            <button disabled={busyKey === key} onClick={() => act(r, "approve")}>
                              {busyKey === key ? "Creating profile…" : status === "FAILED" ? "Retry" : "Approve"}
                            </button>
                            <button className="secondary" disabled={busyKey === key} onClick={() => setRejecting(key)}>
                              Reject
                            </button>
                          </div>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Projects() {
  const [projects, setProjects] = useState<AdminProject[] | null>(null);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ domainId: "", name: "", description: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.admin.projects().then(setProjects).catch((e) => setError(errorMessage(e)));
  }, []);

  useEffect(() => {
    load();
    api
      .domains()
      .then((all) => {
        const mine = all.filter((d) => d.is_admin);
        setDomains(mine);
        if (mine.length) setForm((f) => ({ ...f, domainId: f.domainId || mine[0].domain_id }));
      })
      .catch((e) => setError(errorMessage(e)));
  }, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.admin.createProject(form.domainId, form.name, form.description);
      setForm((f) => ({ ...f, name: "", description: "" }));
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="panel">
        <h2>New project</h2>
        <p className="muted">Creating a project also creates its IAM execution role. User profiles approved for the project use this role.</p>
        <form className="stack" onSubmit={create}>
          <label>
            Domain
            <select value={form.domainId} onChange={(e) => setForm({ ...form, domainId: e.target.value })} required>
              {domains.map((d) => (
                <option key={d.domain_id} value={d.domain_id}>
                  {d.name} ({d.domain_id})
                </option>
              ))}
            </select>
          </label>
          <label>
            Name
            <input value={form.name} maxLength={80} required onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Churn Model" />
          </label>
          <label>
            Description
            <textarea value={form.description} maxLength={500} rows={2} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </label>
          <div>
            <button type="submit" disabled={busy || !form.domainId}>
              {busy ? "Creating role and project…" : "Create project"}
            </button>
          </div>
        </form>
      </section>

      <ErrorBanner error={error} />

      <section className="panel">
        <h2>Projects</h2>
        {projects === null && !error && <p className="muted">Loading…</p>}
        {projects?.length === 0 && <Empty>No projects yet.</Empty>}
        {projects && projects.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Domain</th>
                  <th>Execution role</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.project_id}>
                    <td>
                      <strong>{p.name}</strong>
                      {p.description && <div className="muted">{p.description}</div>}
                    </td>
                    <td>{p.domain_name}</td>
                    <td className="mono">{p.role_name}</td>
                    <td>
                      {formatDate(p.created_at)}
                      <div className="muted">by {p.created_by}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
