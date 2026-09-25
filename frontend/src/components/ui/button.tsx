import type { ButtonHTMLAttributes } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "outline" | "ghost";
  size?: "default" | "icon";
};

export function Button({ className = "", variant = "primary", size = "default", ...props }: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 ${
        size === "icon" ? "h-9 w-9" : "h-10 px-4 py-2"
      } ${
        variant === "primary"
          ? "bg-primary text-primary-foreground hover:bg-primary/90"
          : variant === "outline"
            ? "border border-border bg-background text-foreground hover:bg-accent"
            : "text-muted-foreground hover:bg-accent hover:text-foreground"
      } ${className}`}
      {...props}
    />
  );
}
