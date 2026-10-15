import { NavLink, Navigate, Outlet, Route, Routes, useNavigate } from "react-router-dom";
import { RequireAdmin, RequireAuth, useAuth } from "./auth";
import Admin from "./pages/Admin";
import Domains from "./pages/Domains";
import Login from "./pages/Login";
import MyAccess from "./pages/MyAccess";
import Studio from "./pages/Studio";

function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <>
      <header className="topbar">
        <span className="brand">ML Portal</span>
        <nav>
          <NavLink to="/domains">Domains</NavLink>
          <NavLink to="/my-access">My access</NavLink>
          <NavLink to="/studio">Launch Studio</NavLink>
          {user?.is_admin && <NavLink to="/admin">Admin</NavLink>}
        </nav>
        <div className="who">
          <span>
            {user?.display_name}
            {user?.is_admin && <span className="badge ok">Admin</span>}
          </span>
          <button
            className="link"
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      <main>
        <Outlet />
      </main>
    </>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/domains" element={<Domains />} />
        <Route path="/domains/:domainId" element={<Domains />} />
        <Route path="/my-access" element={<MyAccess />} />
        <Route path="/studio" element={<Studio />} />
        <Route
          path="/admin"
          element={
            <RequireAdmin>
              <Admin />
            </RequireAdmin>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/domains" replace />} />
    </Routes>
  );
}
