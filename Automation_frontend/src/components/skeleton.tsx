type SkeletonProps = {
  className?: string;
};

export function Skeleton({ className }: SkeletonProps) {
  return <div className={`skeleton ${className || ""}`.trim()} aria-hidden="true" />;
}

export function TableSkeleton({ rows = 6, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-800">
      <table className="w-full">
        <thead>
          <tr>
            {Array.from({ length: cols }).map((_, idx) => (
              <th key={`h-${idx}`} className="th">
                <Skeleton className="h-3 w-24" />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }).map((_, r) => (
            <tr key={`r-${r}`}>
              {Array.from({ length: cols }).map((_, c) => (
                <td key={`c-${r}-${c}`} className="td">
                  <Skeleton className="h-4 w-full max-w-[180px]" />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
