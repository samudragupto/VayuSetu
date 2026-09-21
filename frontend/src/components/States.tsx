export function LoadingState({ message = "Loading" }: { message?: string }) {
  return (
    <div className="flex items-center gap-3 text-sm text-slate-500" role="status" aria-live="polite">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" aria-hidden="true" />
      {message}
    </div>
  );
}

export function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-10 text-center">
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {description ? <p className="mt-1 max-w-md text-xs text-slate-500">{description}</p> : null}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
      {message}
    </div>
  );
}
