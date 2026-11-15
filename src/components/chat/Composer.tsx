import React, { useRef, useState, useEffect } from "react";
import {
  ArrowUp,
  Square,
  Plus,
  X,
  Cpu,
  Brain,
  ChevronDown,
  Paperclip,
  Check,
  Sparkles,
} from "lucide-react";
import {
  AVAILABLE_MODELS,
  REASONING_LEVELS,
  type Attachment,
} from "@/lib/keyboard-store";

interface ComposerProps {
  onSend: (text: string, attachments: Attachment[]) => void;
  onStop?: () => void;
  disabled?: boolean;
  isGenerating?: boolean;
  selectedModel: string;
  onSelectModel: (modelId: string) => void;
  reasoningLevel: string;
  onSelectReasoning: (level: string) => void;
  placeholder?: string;
}

export function Composer({
  onSend,
  onStop,
  disabled = false,
  isGenerating = false,
  selectedModel,
  onSelectModel,
  reasoningLevel,
  onSelectReasoning,
  placeholder = "Ask anything, @ to mention, / for actions",
}: ComposerProps) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [showModelMenu, setShowModelMenu] = useState(false);
  const [showReasoningMenu, setShowReasoningMenu] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const menuContainerRef = useRef<HTMLDivElement>(null);

  const activeModel =
    AVAILABLE_MODELS.find((m) => m.id === selectedModel) || AVAILABLE_MODELS[0];
  const activeReasoning =
    REASONING_LEVELS.find((r) => r.id === reasoningLevel) || REASONING_LEVELS[1];

  // Close menus on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        menuContainerRef.current &&
        !menuContainerRef.current.contains(event.target as Node)
      ) {
        setShowModelMenu(false);
        setShowReasoningMenu(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  function handleSubmit() {
    const trimmed = text.trim();
    if ((!trimmed && attachments.length === 0) || isGenerating || disabled) return;
    onSend(trimmed, attachments);
    setText("");
    setAttachments([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    const newAtts: Attachment[] = [];
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      newAtts.push({
        name: file.name,
        size: file.size,
        type: file.type || "file",
      });
    }
    setAttachments((prev) => [...prev, ...newAtts]);
    e.target.value = "";
  }

  function removeAttachment(index: number) {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }

  function autoGrow(el: HTMLTextAreaElement) {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }

  const hasContent = Boolean(text.trim().length > 0 || attachments.length > 0);

  return (
    <div ref={menuContainerRef} className="relative mx-auto w-full max-w-3xl">
      {/* Model Selector Popover */}
      {showModelMenu && (
        <div className="absolute bottom-full left-3 mb-2 w-72 rounded-xl border border-border bg-popover p-1.5 shadow-lg z-50 animate-in fade-in zoom-in-95">
          <div className="px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Inference Engine
          </div>
          <div className="max-h-64 overflow-y-auto space-y-0.5">
            {AVAILABLE_MODELS.map((model) => {
              const isSelected = model.id === selectedModel;
              return (
                <button
                  key={model.id}
                  type="button"
                  onClick={() => {
                    onSelectModel(model.id);
                    setShowModelMenu(false);
                  }}
                  className={`flex w-full items-start justify-between rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors cursor-pointer ${
                    isSelected
                      ? "bg-accent text-accent-foreground font-medium"
                      : "hover:bg-muted/70 text-foreground"
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate">{model.name}</span>
                      {model.isLocal && (
                        <span className="rounded bg-emerald-500/10 px-1 py-0.2 font-mono text-[9px] text-emerald-600 dark:text-emerald-400">
                          Local
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                      {model.description}
                    </p>
                  </div>
                  {isSelected && <Check className="h-3.5 w-3.5 text-primary shrink-0 ml-1.5 mt-0.5" />}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Reasoning Level Popover */}
      {showReasoningMenu && (
        <div className="absolute bottom-full left-20 mb-2 w-64 rounded-xl border border-border bg-popover p-1.5 shadow-lg z-50 animate-in fade-in zoom-in-95">
          <div className="px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Reasoning Effort
          </div>
          <div className="space-y-0.5">
            {REASONING_LEVELS.map((level) => {
              const isSelected = level.id === reasoningLevel;
              return (
                <button
                  key={level.id}
                  type="button"
                  onClick={() => {
                    onSelectReasoning(level.id);
                    setShowReasoningMenu(false);
                  }}
                  className={`flex w-full items-start justify-between rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors cursor-pointer ${
                    isSelected
                      ? "bg-accent text-accent-foreground font-medium"
                      : "hover:bg-muted/70 text-foreground"
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-xs">{level.label}</div>
                    <p className="text-[10px] text-muted-foreground leading-tight">
                      {level.desc}
                    </p>
                  </div>
                  {isSelected && <Check className="h-3.5 w-3.5 text-primary shrink-0 ml-1.5 mt-0.5" />}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Modern Floating Composer Card Container */}
      <div className="rounded-2xl border border-border/70 bg-card/95 backdrop-blur-md p-2.5 shadow-sm transition-all focus-within:border-border focus-within:ring-1 focus-within:ring-ring/20">
        {/* Attachment preview pills */}
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-1.5 pb-2">
            {attachments.map((att, idx) => (
              <span
                key={idx}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/50 px-2 py-0.5 text-xs text-foreground font-mono text-[11px]"
              >
                <Paperclip className="h-3 w-3 text-muted-foreground" />
                <span className="max-w-[160px] truncate">{att.name}</span>
                <button
                  type="button"
                  onClick={() => removeAttachment(idx)}
                  className="rounded hover:bg-muted p-0.5 text-muted-foreground hover:text-foreground cursor-pointer"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Textarea Input */}
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            autoGrow(e.target);
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          disabled={disabled}
          className="w-full resize-none border-0 bg-transparent px-2 py-1 text-sm text-foreground placeholder:text-muted-foreground/70 focus:outline-none focus:ring-0 leading-relaxed font-sans"
          style={{ maxHeight: "220px" }}
        />

        {/* Bottom Control Bar */}
        <div className="flex items-center justify-between pt-1.5 px-0.5">
          {/* Left Controls: Add Context (+) & Clean Model/Reasoning Capsule Pill */}
          <div className="flex items-center gap-1.5">
            {/* Add context / attach files button */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex h-7 w-7 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground transition-colors cursor-pointer"
              title="Add attachment or context (+)"
            >
              <Plus className="h-4 w-4" />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleFileChange}
            />

            {/* Clean Model Selector Pill */}
            <button
              type="button"
              onClick={() => {
                setShowModelMenu(!showModelMenu);
                setShowReasoningMenu(false);
              }}
              className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-normal text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
            >
              <span>{activeModel.name}</span>
              <ChevronDown className="h-3 w-3 opacity-60" />
            </button>

            {/* Clean Reasoning Level Pill */}
            <button
              type="button"
              onClick={() => {
                setShowReasoningMenu(!showReasoningMenu);
                setShowModelMenu(false);
              }}
              className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-normal text-muted-foreground/80 hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
            >
              <span>{activeReasoning.label}</span>
              <ChevronDown className="h-3 w-3 opacity-60" />
            </button>
          </div>

          {/* Right Controls: Send / Stop Action Button */}
          <div className="flex items-center gap-1">
            {isGenerating ? (
              <button
                type="button"
                onClick={onStop}
                className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-all cursor-pointer shadow-2xs"
                title="Stop generation"
              >
                <Square className="h-3 w-3 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!hasContent || disabled}
                className={`inline-flex h-7 w-7 items-center justify-center rounded-full transition-all cursor-pointer shadow-2xs ${
                  hasContent
                    ? "bg-foreground text-background hover:opacity-90"
                    : "bg-muted text-muted-foreground/40 cursor-not-allowed"
                }`}
                title="Send prompt (Enter)"
              >
                <ArrowUp className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
