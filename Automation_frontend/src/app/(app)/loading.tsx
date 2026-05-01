import { Skeleton } from "@/components/skeleton";

export default function AppRouteLoading() {
  return (
    <div className="space-y-4">
      <section className="card p-5">
        <Skeleton className="h-7 w-56" />
        <Skeleton className="mt-3 h-4 w-80" />
      </section>
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <article key={i} className="card p-4">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="mt-3 h-8 w-20" />
          </article>
        ))}
      </section>
      <section className="card p-5">
        <Skeleton className="h-72 w-full" />
      </section>
    </div>
  );
}
