export function PageHeader({ title, summary }: { title: string; summary: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-1 max-w-3xl text-sm text-muted">{summary}</p>
    </div>
  );
}
