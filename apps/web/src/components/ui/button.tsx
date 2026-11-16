import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "border-accent bg-accent text-white hover:border-accent-hover hover:bg-accent-hover",
  secondary: "border-line-strong bg-panel text-ink hover:bg-sunken",
  ghost: "border-transparent bg-transparent text-ink hover:bg-sunken",
  danger: "border-bad bg-bad text-white hover:bg-bad/90",
};

const SIZES: Record<Size, string> = {
  sm: "h-7 px-2.5 text-xs",
  md: "h-8 px-3 text-sm",
};

/** The classes of a button, for links that act as buttons. */
export function buttonClass(variant: Variant = "secondary", size: Size = "md"): string {
  return `inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-control border font-medium transition-colors duration-100 disabled:cursor-not-allowed disabled:opacity-45 ${VARIANTS[variant]} ${SIZES[size]}`;
}

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return <button type={type} className={`${buttonClass(variant, size)} ${className}`} {...props} />;
}
