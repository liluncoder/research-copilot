import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

/*
 * 提示条：错误、成功、说明各一档。
 * 之前每个页面自己拼 `rounded-lg border border-destructive/40 bg-destructive/10`，
 * 有的 px-3、有的 px-4，有的带图标有的不带 —— 现在统一。
 */
const alertVariants = cva("flex items-start gap-2.5 rounded-lg border px-4 py-3 text-[13px] leading-relaxed", {
  variants: {
    variant: {
      info: "border-primary/20 bg-primary/[0.05] text-foreground",
      success: "border-success/25 bg-success/[0.07] text-foreground",
      warning: "border-warning/30 bg-warning/[0.07] text-foreground",
      destructive: "border-destructive/30 bg-destructive/[0.06] text-destructive",
    },
  },
  defaultVariants: { variant: "info" },
});

const ICONS = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  destructive: XCircle,
} as const;

export interface AlertProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {
  /** 关掉左侧图标（例如内容本身已经是列表） */
  hideIcon?: boolean;
}

export function Alert({ className, variant = "info", hideIcon, children, ...props }: AlertProps) {
  const Icon = ICONS[variant ?? "info"];
  return (
    <div role="status" className={cn(alertVariants({ variant }), className)} {...props}>
      {!hideIcon && <Icon className="mt-0.5 h-4 w-4 shrink-0 opacity-80" />}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
