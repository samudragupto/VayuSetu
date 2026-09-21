import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-center">
      <h1 className="text-2xl font-semibold text-slate-900">Page not found</h1>
      <p className="text-sm text-slate-600">The page you requested does not exist.</p>
      <Link href="/" className="btn-primary">
        Back to overview
      </Link>
    </div>
  );
}
