import * as React from "react";
import { cn } from "@/lib/utils";

export type SegmentedOption = {
  value: string;
  label: React.ReactNode;
  icon?: React.ReactNode;
};

/*
 * 分段控件：写作页的 Tab、图谱页的指标切换、阅读器的开关共用一个。
 * 之前三处各写一套（border 容器 + 选中态颜色不同），现在只允许尺寸与是否撑满不同。
 */
export function Segmented({
  value,
  onChange,
  options,
  size = "default",
  fullWidth,
  className,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  options: SegmentedOption[];
  size?: "sm" | "default";
  fullWidth?: boolean;
  className?: string;
  label?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-lg border border-border bg-muted/45 p-0.5",
        fullWidth && "flex w-full",
        className,
      )}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(o.value)}
            className={cn(
              "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors",
              size === "sm" ? "h-7 px-2.5 text-[12px]" : "h-8 px-3 text-[12.5px]",
              fullWidth && "flex-1",
              active
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {o.icon}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
