import { cn } from "@/lib/utils";
export function KeyLogo({ size = "sm" }: { size?: "sm" | "lg" }) {
  return (
    <div
      className={cn(
        "shadow-key grid place-items-center rounded-lg border border-border bg-secondary font-mono font-bold text-primary",
        size === "lg" ? "h-20 w-20 text-3xl" : "h-8 w-8 text-sm",
      )}
    >
      S
    </div>
  );
}
