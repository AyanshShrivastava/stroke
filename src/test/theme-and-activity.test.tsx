import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { getStoredTheme, setStoredTheme, getResolvedTheme, applyTheme } from "@/lib/theme";
import { ActivityFeed } from "@/components/chat/ActivityFeed";
import { Composer } from "@/components/chat/Composer";

describe("Theme System", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.className = "";
  });

  it("defaults to system when no theme stored", () => {
    expect(getStoredTheme()).toBe("system");
  });

  it("persists theme mode in localStorage and fires event", () => {
    const listener = vi.fn();
    window.addEventListener("stroke:theme-changed", listener);

    setStoredTheme("light");
    expect(localStorage.getItem("stroke_theme")).toBe("light");
    expect(getStoredTheme()).toBe("light");
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    setStoredTheme("dark");
    expect(localStorage.getItem("stroke_theme")).toBe("dark");
    expect(getStoredTheme()).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    window.removeEventListener("stroke:theme-changed", listener);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("resolves system theme according to matchMedia", () => {
    expect(getResolvedTheme("light")).toBe("light");
    expect(getResolvedTheme("dark")).toBe("dark");
  });
});

describe("ActivityFeed Component", () => {
  it("renders live thinking indicator when active", () => {
    render(<ActivityFeed isLiveThinking liveElapsedSeconds={2.4} />);
    expect(screen.getByText("Thinking…")).toBeInTheDocument();
    expect(screen.getByText("2.4s")).toBeInTheDocument();
    expect(screen.getByText("Active Agent Loop")).toBeInTheDocument();
  });

  it("renders summary badges and expands detailed execution steps", () => {
    const mockSteps = [
      {
        name: "File Analysis",
        detail: "Read ServerScriptService/VFXController.luau",
        status: "success" as const,
      },
      {
        name: "Autonomous Tool Execution",
        detail: "Ran studio_execute_luau",
        status: "success" as const,
      },
    ];
    const mockCodingLoop = {
      iterations: 2,
      initial_passed: false,
      final_passed: true,
      healed: true,
      syntax_valid: true,
      domain_tests_passed: true,
    };

    render(
      <ActivityFeed
        steps={mockSteps}
        codingLoop={mockCodingLoop}
        durationSeconds={1.8}
        taskState="completed"
      />,
    );

    // Collapsed header: formatWorkedDuration outputs "Worked for 2s"
    expect(screen.getByText("Worked for 2s")).toBeInTheDocument();

    // Click to expand parent thinking tree
    const button = screen.getByRole("button", { name: /Worked for 2s/i });
    fireEvent.click(button);

    // Hierarchical tree stream details
    expect(screen.getByText("Explored files, ran commands")).toBeInTheDocument();
    expect(screen.getByText("Analyzed VFXController.luau")).toBeInTheDocument();
    expect(screen.getByText("Autonomous Tool Execution")).toBeInTheDocument();
    expect(screen.getByText(/Luau syntax & tests verified/)).toBeInTheDocument();
  });
});

describe("Composer Component", () => {
  it("renders model pill, reasoning pill, and dispatches send on Enter", () => {
    const onSend = vi.fn();
    const onSelectModel = vi.fn();
    const onSelectReasoning = vi.fn();

    render(
      <Composer
        onSend={onSend}
        selectedModel="llama3.2-local"
        onSelectModel={onSelectModel}
        reasoningLevel="medium"
        onSelectReasoning={onSelectReasoning}
      />,
    );

    expect(screen.getByText("Llama 3.2 1B")).toBeInTheDocument();
    expect(screen.getByText("Medium")).toBeInTheDocument();

    const textarea = screen.getByPlaceholderText(/Ask anything/i);
    fireEvent.change(textarea, { target: { value: "Build fire VFX" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    expect(onSend).toHaveBeenCalledWith("Build fire VFX", []);
  });
});
