import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Domain, type Project } from "../api";
import { Empty, ErrorBanner, StatusBadge, errorMessage } from "../components";

export default function Domains() {
  const { domainId } = useParams();
  const [domains, setDomains] = useState<Domain[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.domains().then(setDomains).catch((e) => setError(errorMessage(e)));
  }, []);

  const selected = domains?.find((d) => d.domain_id === domainId);

  return (
    <>
      <h1>Domains</h1>
      <p className="muted">SageMaker AI domains in this account. Pick one to see its projects and request access.</p>
      <ErrorBanner error={error} />
      {domains === null && !error && <p className="muted">Loading domains…</p>}
      {domains?.length === 0 && <Empty>No SageMaker AI domains found in this region.</Empty>}

      <div className="split">
        <nav className="domain-list" aria-label="Domains">
          {domains?.map((d) => (
            <Link
              key={d.domain_id}
              to={`/domains/${d.domain_id}`}
              className={`domain-card ${d.domain_id === domainId ? "active" : ""}`}
            >
              <strong>{d.name}</strong>
              <span className="muted mono">{d.domain_id}</span>
              <span className="tags">
                <span className="badge">{d.auth_mode}</span>
                {d.status !== "InService" && <span className="badge warn">{d.status}</span>}
                {d.is_admin && <span className="badge ok">You're an admin</span>}
              </span>
            </Link>
          ))}
        </nav>

        <section className="panel">
          {selected ? <DomainProjects domain={selected} /> : domains?.length ? <Empty>Select a domain.</Empty> : null}
        </section>
      </div>
    </>
  );
}

function DomainProjects({ domain }: { domain: Domain }) {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requesting, setRequesting] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setProjects(null);
    api.projects(domain.domain_id).then(setProjects).catch((e) => setError(errorMessage(e)));
  }, [domain.domain_id]);

  useEffect(load, [load]);

  async function submit(projectId: string) {
    setBusy(true);
    setError(null);
    try {
      await api.requestAccess(projectId, reason);
      setRequesting(null);
      setReason("");
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h2>{domain.name} projects</h2>
      {domain.auth_mode !== "IAM" && (
        <div className="banner warn">
          This domain uses {domain.auth_mode} login. Studio launch from the portal needs an IAM-mode domain.
        </div>
      )}
      <ErrorBanner error={error} />
      {projects === null && !error && <p className="muted">Loading projects…</p>}
      {projects?.length === 0 && <Empty>No projects in this domain yet. An admin can create one.</Empty>}

      <ul className="project-list">
        {projects?.map((p) => {
          const canRequest = p.my_status === null || p.my_status === "REJECTED";
          return (
            <li key={p.project_id} className="project">
              <div className="project-head">
                <div>
                  <strong>{p.name}</strong>
                  {p.description && <p className="muted">{p.description}</p>}
                </div>
                <div className="project-actions">
                  <StatusBadge status={p.my_status} />
                  {canRequest && requesting !== p.project_id && (
                    <button onClick={() => setRequesting(p.project_id)}>
                      {p.my_status === "REJECTED" ? "Request again" : "Request access"}
                    </button>
                  )}
                  {p.my_status === "APPROVED" && (
                    <Link className="button secondary" to="/studio">
                      Open Studio
                    </Link>
                  )}
                </div>
              </div>
              {requesting === p.project_id && (
                <form
                  className="inline-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    submit(p.project_id);
                  }}
                >
                  <label htmlFor={`reason-${p.project_id}`}>Why do you need access? (optional)</label>
                  <textarea
                    id={`reason-${p.project_id}`}
                    value={reason}
                    maxLength={500}
                    onChange={(e) => setReason(e.target.value)}
                    rows={2}
                  />
                  <div className="row">
                    <button type="submit" disabled={busy}>
                      Submit request
                    </button>
                    <button type="button" className="secondary" onClick={() => setRequesting(null)}>
                      Cancel
                    </button>
                  </div>
                </form>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}
