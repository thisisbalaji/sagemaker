import { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { api, type MockUser } from "../api";
import { useAuth } from "../auth";
import { ErrorBanner, errorMessage } from "../components";

export default function Login() {
  const { user, refresh } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [users, setUsers] = useState<MockUser[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.mockUsers().then(setUsers).catch((e) => setError(errorMessage(e)));
  }, []);

  if (user) return <Navigate to="/domains" replace />;

  async function signIn(userId: string) {
    setError(null);
    try {
      await api.login(userId);
      await refresh();
      navigate((location.state as { from?: string } | null)?.from ?? "/domains", { replace: true });
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <div className="login">
      <h1>ML Portal</h1>
      <p className="muted">Development login — pick a user. Replace with real sign-in before sharing the portal.</p>
      <ErrorBanner error={error} />
      <div className="user-list">
        {users.map((u) => (
          <button key={u.user_id} className="user-card" onClick={() => signIn(u.user_id)}>
            <strong>{u.display_name}</strong>
            <span className="muted">
              {u.user_id} · {u.is_admin ? "Domain admin" : "User"}
            </span>
          </button>
        ))}
      </div>
      {users.length === 0 && !error && (
        <p className="muted">
          No users yet. Run <code>python -m app.seed --admin-domain &lt;domain-id&gt;</code> in <code>portal/backend</code>.
        </p>
      )}
    </div>
  );
}
