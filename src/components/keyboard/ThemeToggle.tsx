import React, { useEffect, useState } from "react";
import { Sun, Moon, Laptop } from "lucide-react";
import { getStoredTheme, setStoredTheme, type ThemeMode } from "@/lib/theme";

export function ThemeToggle({ className = "" }: { className?: string }) {
  const [theme, setTheme] = useState<ThemeMode>("system");

  useEffect(() => {
    setTheme(getStoredTheme());
    const handler = (e: Event) => {
      const mode = (e as CustomEvent).detail?.mode || getStoredTheme();
      setTheme(mode);
    };
    window.addEventListener("stroke:theme-changed", handler);
    return () => window.removeEventListener("stroke:theme-changed", handler);
  }, []);

  function cycleTheme() {
    const next: ThemeMode =
      theme === "light" ? "dark" : theme === "dark" ? "system" : "light";
    setTheme(next);
    setStoredTheme(next);
  }

  return (
    <button
      type="button"
      onClick={cycleTheme}
      className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition-colors ${className}`}
      title={`Theme: ${theme.charAt(0).toUpperCase() + theme.slice(1)} (Click to switch)`}
      aria-label="Toggle theme appearance"
    >
      {theme === "light" ? (
        <Sun className="h-4 w-4 text-amber-500" />
      ) : theme === "dark" ? (
        <Moon className="h-4 w-4 text-indigo-400" />
      ) : (
        <Laptop className="h-4 w-4 text-muted-foreground" />
      )}
      <span className="capitalize">{theme}</span>
    </button>
  );
}

export function ThemeSelector() {
  const [theme, setTheme] = useState<ThemeMode>("system");

  useEffect(() => {
    setTheme(getStoredTheme());
    const handler = (e: Event) => {
      const mode = (e as CustomEvent).detail?.mode || getStoredTheme();
      setTheme(mode);
    };
    window.addEventListener("stroke:theme-changed", handler);
    return () => window.removeEventListener("stroke:theme-changed", handler);
  }, []);

  const options: Array<{ id: ThemeMode; label: string; icon: typeof Sun }> = [
    { id: "light", label: "Light", icon: Sun },
    { id: "dark", label: "Dark", icon: Moon },
    { id: "system", label: "System", icon: Laptop },
  ];

  return (
    <div className="flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-1">
      {options.map((opt) => {
        const Icon = opt.icon;
        const isActive = theme === opt.id;
        return (
          <button
            key={opt.id}
            type="button"
            onClick={() => {
              setTheme(opt.id);
              setStoredTheme(opt.id);
            }}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all ${
              isActive
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            <span>{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}
