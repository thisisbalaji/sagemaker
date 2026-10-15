import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AccessRequest } from "../api";
import { Empty, ErrorBanner, StatusBadge, errorMessage } from "../components";

export default function Studio() {
  const [rows, setRows] = useState<AccessRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .myRequests()
      .then((all) => setRows(all.filter((r) => r.status === "APPROVED")))
      .catch((e) => setError(errorMessage(e)));
  }, []);

  useEffect(load, [load]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Launch Studio</h1>
          <p className="muted">
            Open SageMaker AI Studio for a project you have access to. Each click creates a fresh single-use login that
            opens in a new tab — the login link itself is never shown.
          </p>
        </div>
        <button className="secondary" onClick={load}>
          Refresh
        </button>
      </div>
      <ErrorBanner error={error} />
      {rows === null && !error && <p className="muted">Loading…</p>}
      {rows?.length === 0 && (
        <Empty>
          You don't have access to any projects yet. <Link to="/domains">Request access</Link> first.
        </Empty>
      )}

      <ul className="launch-list">
        {rows?.map((r) => {
          const ready = r.profile_status === "InService";
          return (
            <li key={r.project_id} className="launch-card">
              <div>
                <strong>{r.project_name}</strong>
                <div className="muted mono">
                  {r.domain_id} · {r.user_profile_name}
                </div>
                <div className="tags">
                  <StatusBadge status={r.profile_status} />
                  {!ready && <span className="muted">Profile is still being set up — refresh in a minute.</span>}
                </div>
              </div>
              {/* A real form POST (not fetch) so the browser follows the server's 302 straight into Studio. */}
              <form method="post" action="/api/studio/launch" target="_blank">
                <input type="hidden" name="project_id" value={r.project_id} />
                <button type="submit" disabled={!ready}>
                  Open Studio ↗
                </button>
              </form>
            </li>
          );
        })}
      </ul>
    </>
  );
}
