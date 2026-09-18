import { useEffect, useState } from "react";
import { ToastViewport } from "./components/ToastViewport";
import { useAdminStore } from "./hooks/useAdminStore";
import { AdminLayout } from "./layouts/AdminLayout";
import { LoginPage } from "./pages/LoginPage";
import {
  defaultPathFor,
  matchRoute,
  mayOpen,
  redirectFor,
  type RouteContext,
} from "./routes";

function usePathname() {
  const [pathname, setPathname] = useState(window.location.pathname);

  useEffect(() => {
    const handlePopState = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  // `pathname` stays PATH-ONLY even when a caller passes a query string: every
  // route below is matched with a regex anchored on `$`, so storing
  // "/x/edit?from=y" here would match nothing and render a blank page. The
  // query still goes into the URL, where `window.location.search` can read it.
  const navigate = (nextPath: string) => {
    const [nextPathname = ""] = nextPath.split("?");
    if (window.location.pathname + window.location.search === nextPath) {
      return;
    }
    window.history.pushState({}, "", nextPath);
    setPathname(nextPathname);
  };

  return { pathname, navigate };
}

/**
 * The shell: who is signed in, where they are, and the page that answers.
 *
 * Everything about *which* addresses exist, who may open them and what they
 * render lives in `routes.tsx`. This file used to hold all of it as a
 * nested ternary and two hand-maintained allowlists that had already drifted
 * apart from the sidebar's own two.
 */
function App() {
  const { pathname, navigate } = usePathname();
  const {
    token,
    role,
    restaurantId,
    user,
    isAuthenticated,
    logout,
    toasts,
    dismissToast,
    pushToast,
  } = useAdminStore();

  useEffect(() => {
    if (!isAuthenticated || !user || !role) {
      return;
    }

    if ((role !== "ADMIN" && role !== "OWNER") || user.role !== role) {
      pushToast(
        "Access blocked",
        "Customer accounts cannot access the admin panel.",
        "error",
      );
      logout();
      navigate("/login");
      return;
    }

    if (role === "OWNER" && !restaurantId) {
      pushToast(
        "Access blocked",
        "This owner account is not linked to a restaurant yet.",
        "error",
      );
      logout();
      navigate("/login");
      return;
    }

    const elsewhere = redirectFor(pathname, role, restaurantId);
    if (elsewhere && elsewhere !== pathname) {
      navigate(elsewhere);
    }
  }, [
    isAuthenticated,
    logout,
    navigate,
    pathname,
    pushToast,
    restaurantId,
    role,
    user,
  ]);

  if (!isAuthenticated || !token || !user || !role) {
    return (
      <>
        <LoginPage onSuccess={navigate} />
        <ToastViewport toasts={toasts} onDismiss={dismissToast} />
      </>
    );
  }

  const context: RouteContext = {
    token,
    role,
    restaurantId,
    user,
    navigate,
    pushToast,
  };

  // The redirect above settles an address this role cannot open, but it runs
  // in an effect and this render happens first. Falling back to their own
  // home page means the in-between frame is a page they are allowed to see
  // rather than one they are not.
  const found = matchRoute(pathname);
  const allowed = found && mayOpen(found.route, role) ? found : null;
  const home = allowed ? null : matchRoute(defaultPathFor(role, restaurantId));
  const showing = allowed ?? home;

  return (
    <>
      <AdminLayout
        currentPath={pathname}
        onNavigate={navigate}
        onLogout={() => {
          logout();
          navigate("/login");
        }}
        role={role}
        restaurantId={restaurantId}
      >
        {showing ? showing.route.render(context, showing.params) : null}
      </AdminLayout>
      <ToastViewport toasts={toasts} onDismiss={dismissToast} />
    </>
  );
}

export default App;
