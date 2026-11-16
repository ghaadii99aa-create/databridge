import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div className="py-16">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="mt-2 text-ink-muted">The address does not match any page in DataBridge.</p>
      <Link to="/" className="link mt-5 inline-block">Go to overview</Link>
    </div>
  );
}
