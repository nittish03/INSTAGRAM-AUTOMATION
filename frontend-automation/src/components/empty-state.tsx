import { ReactNode } from "react";

type EmptyStateProps = {
  title: string;
  description?: string;
  action?: ReactNode;
};

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="card flex flex-col items-center justify-center px-6 py-16 text-center">
      <p className="text-sm font-semibold text-slate-200">{title}</p>
      {description ? (
        <p className="mt-1 max-w-md text-sm text-slate-400">{description}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
