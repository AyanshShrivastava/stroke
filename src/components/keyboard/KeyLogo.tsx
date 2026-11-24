import { cn } from "@/lib/utils";
export function KeyLogo({ size = "sm" }: { size?: "sm" | "lg" }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      role="img"
      aria-label="Stroke"
      className={cn("shrink-0 text-foreground", size === "lg" ? "h-14 w-14" : "h-7 w-7")}
    >
      <path
        d="M23 5H12a6 6 0 0 0 0 12h8a5 5 0 0 1 0 10H7"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="square"
      />
      <path d="m9 22 14-12" stroke="currentColor" strokeWidth="4" />
    </svg>
  );
}
