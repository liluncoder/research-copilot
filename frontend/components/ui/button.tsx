import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/*
 * 之前 7 个页面里的按钮都是手写 <button className="rounded border px-3 py-1.5 ...">，
 * 尺寸、圆角、hover 各写一套 ⇒ 同一个产品看起来像 7 个人做的。
 * 统一到这里：只允许用 variant / size 表达差异，不允许页面自己改 padding。
 *
 * 链接按钮用 buttonVariants 套在 <Link> 上，不要 <Link><Button></Link>：
 * <a> 里套 <button> 是非法嵌套，键盘和读屏都会出问题。
 */
const buttonVariants = cva(
  "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-1 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90",
        outline: "border border-border bg-card hover:border-primary/30 hover:bg-muted/60",
        ghost: "text-foreground/80 hover:bg-muted hover:text-foreground",
        subtle: "bg-muted text-foreground/80 hover:bg-muted/70",
        selected: "border border-primary/25 bg-primary/10 text-primary hover:bg-primary/15",
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        "destructive-outline":
          "border border-destructive/35 bg-transparent text-destructive hover:bg-destructive/10",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-8 px-3 text-[13px]",
        default: "h-9 px-4",
        lg: "h-11 px-6 text-[15px]",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  ),
);
Button.displayName = "Button";

export { Button, buttonVariants };
