import * as React from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "outline" | "danger";
type Size = "sm" | "md" | "icon" | "icon-sm";

const variants: Record<Variant, string> = {
  primary: "bg-primary text-primary-foreground hover:bg-[#4338ca] disabled:bg-muted disabled:text-muted-foreground",
  secondary: "bg-muted text-foreground hover:bg-border disabled:opacity-50",
  ghost: "text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50",
  outline: "border border-input bg-transparent text-foreground hover:bg-muted disabled:opacity-50",
  danger: "border border-danger/40 text-danger hover:bg-danger-soft disabled:opacity-50",
};
const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-sm gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  icon: "h-10 w-10",
  "icon-sm": "h-8 w-8",
};

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

/** A small shadcn-style button. */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "secondary", size = "md", type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex shrink-0 cursor-pointer items-center justify-center rounded-xl font-medium transition-colors duration-150 disabled:cursor-not-allowed",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  );
});
