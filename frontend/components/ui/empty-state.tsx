import * as React from "react";
import { cn } from "@/lib/utils";

/** 空态：图标 + 一句解释 + 一个可选的下一步。各页不要各写一套灰字。 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-border px-6 py-10 text-center",
        className,
      )}
    >
      {icon && (
        <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
          {icon}
        </span>
      )}
      <p className="text-sm font-medium text-foreground/85">{title}</p>
      {description && (
        <p className="mt-1 max-w-md text-[13px] leading-relaxed text-muted-foreground">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
