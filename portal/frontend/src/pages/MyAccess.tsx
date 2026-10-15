import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AccessRequest } from "../api";
import { Empty, ErrorBanner, StatusBadge, errorMessage, formatDate } from "../components";

export default function MyAccess() {
  const [rows, setRows] = useState<AccessRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.myRequests().then(setRows).catch((e) => setError(errorMessage(e)));
  }, []);

  return (
    <>
      <h1>My access</h1>
      <p className="muted">Every project you've asked to join and where each request stands.</p>
      <ErrorBanner error={error} />
      {rows === null && !error && <p className="muted">Loading…</p>}
      {rows?.length === 0 && (
        <Empty>
          No requests yet. <Link to="/domains">Browse domains</Link> to request access to a project.
        </Empty>
      )}
      {rows && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Project</th>
                <th>Status</th>
                <th>Requested</th>
                <th>Decision</th>
                <th>Studio profile</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.project_id}>
                  <td>
                    <strong>{r.project_name}</strong>
                    <div className="muted mono">{r.domain_id}</div>
                  </td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td>{formatDate(r.requested_at)}</td>
                  <td>
                    {r.decided_by ? (
                      <>
                        {r.decided_by} · {formatDate(r.decided_at)}
                        {r.decision_note && <div className="muted">“{r.decision_note}”</div>}
                      </>
                    ) : (
                      "—"
                    )}
                    {r.status === "FAILED" && r.error && <div className="error-text">{r.error}</div>}
                  </td>
                  <td>
                    {r.user_profile_name ? (
                      <>
                        <span className="mono">{r.user_profile_name}</span> <StatusBadge status={r.profile_status} />
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
