import { Link, useRouteError } from "react-router-dom";

export function RouteError() {
  const error = useRouteError() as Error | undefined;
  return (
    <div className="mx-auto max-w-xl px-6 py-24">
      <h1 className="text-xl font-semibold">This page failed to load</h1>
      <p className="mt-2 text-ink-muted">
        {error?.message?.includes("dynamically imported module")
          ? "A newer version of DataBridge was deployed. Reload the page to continue."
          : "An unexpected error occurred in the interface."}
      </p>
      <div className="mt-6 flex gap-3">
        <button className="link" onClick={() => window.location.reload()}>Reload</button>
        <Link to="/" className="link">Go to overview</Link>
      </div>
    </div>
  );
}
