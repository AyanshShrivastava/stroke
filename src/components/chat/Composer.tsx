import React, { useRef, useState } from "react";
import {
  ArrowUp,
  Square,
  Paperclip,
  X,
  Cpu,
  Brain,
  ChevronDown,
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
  placeholder = "Message Stroke Builder Core…",
}: ComposerProps) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [showModelMenu, setShowModelMenu] = useState(false);
  const [showReasoningMenu, setShowReasoningMenu] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const activeModel =
    AVAILABLE_MODELS.find((m) => m.id === selectedModel) || AVAILABLE_MODELS[0];
  const activeReasoning =
    REASONING_LEVELS.find((r) => r.id === reasoningLevel) || REASONING_LEVELS[1];

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
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  return (
    <div className="relative mx-auto w-full max-w-3xl">
      {/* Model Selector Popover */}
      {showModelMenu && (
        <div
          className="absolute bottom-full left-0 mb-2 w-72 rounded-xl border border-border bg-popover p-1.5 shadow-xl z-50 animate-in fade-in zoom-in-95"
          onMouseLeave={() => setShowModelMenu(false)}
        >
          <div className="px-2 py-1 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
            Inference Engine
          </div>
          <div className="space-y-0.5">
            {AVAILABLE_MODELS.map((model) => (
              <button
                key={model.id}
                type="button"
                onClick={() => {
                  onSelectModel(model.id);
                  setShowModelMenu(false);
                }}
                className={`flex w-full items-start justify-between rounded-lg px-2.5 py-2 text-left text-xs transition-colors ${
                  model.id === selectedModel
                    ? "bg-primary text-primary-foreground font-medium"
                    : "hover:bg-accent text-foreground"
                }`}
              >
                <div>
                  <div className="flex items-center gap-1.5">
                    <span>{model.name}</span>
                    <span
                      className={`text-[9px] px-1.5 py-0.2 rounded font-mono ${
                        model.id === selectedModel
                          ? "bg-primary-foreground/20 text-primary-foreground"
                          : model.isLocal
                          ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {model.badge}
                    </span>
                  </div>
                  <div
                    className={`mt-0.5 text-[10px] leading-tight ${
                      model.id === selectedModel ? "text-primary-foreground/80" : "text-muted-foreground"
                    }`}
                  >
                    {model.description}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Reasoning Level Popover */}
      {showReasoningMenu && (
        <div
          className="absolute bottom-full left-24 mb-2 w-64 rounded-xl border border-border bg-popover p-1.5 shadow-xl z-50 animate-in fade-in zoom-in-95"
          onMouseLeave={() => setShowReasoningMenu(false)}
        >
          <div className="px-2 py-1 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
            Reasoning Effort
          </div>
          <div className="space-y-0.5">
            {REASONING_LEVELS.map((level) => (
              <button
                key={level.id}
                type="button"
                onClick={() => {
                  onSelectReasoning(level.id);
                  setShowReasoningMenu(false);
                }}
                className={`flex w-full items-start justify-between rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors ${
                  level.id === reasoningLevel
                    ? "bg-primary text-primary-foreground font-medium"
                    : "hover:bg-accent text-foreground"
                }`}
              >
                <div>
                  <div className="font-medium">{level.label}</div>
                  <div
                    className={`text-[10px] ${
                      level.id === reasoningLevel ? "text-primary-foreground/80" : "text-muted-foreground"
                    }`}
                  >
                    {level.desc}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Main Composer Box */}
      <div className="rounded-2xl border border-input/80 bg-card p-2 shadow-sm transition-all focus-within:border-primary/60 focus-within:ring-2 focus-within:ring-primary/10">
        {/* Attachment preview pills */}
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-2 pb-2">
            {attachments.map((att, idx) => (
              <span
                key={idx}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/60 px-2 py-0.5 text-xs text-foreground"
              >
                <Paperclip className="h-3 w-3 text-muted-foreground" />
                <span className="max-w-[150px] truncate">{att.name}</span>
                <button
                  type="button"
                  onClick={() => removeAttachment(idx)}
                  className="rounded hover:bg-muted p-0.5 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Input Textarea */}
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
          className="w-full resize-none border-0 bg-transparent px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-0 leading-relaxed"
          style={{ maxHeight: "200px" }}
        />

        {/* Bottom Control Bar */}
        <div className="flex items-center justify-between pt-1 px-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            {/* Model Selector Pill */}
            <button
              type="button"
              onClick={() => {
                setShowModelMenu(!showModelMenu);
                setShowReasoningMenu(false);
              }}
              className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs font-medium text-foreground hover:bg-muted transition-colors"
            >
              <Cpu className="h-3 w-3 text-primary" />
              <span>{activeModel.name}</span>
              {activeModel.isLocal && (
                <span className="rounded bg-emerald-500/15 px-1 py-0.2 font-mono text-[9px] text-emerald-600 dark:text-emerald-400">
                  Local
                </span>
              )}
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            </button>

            {/* Reasoning Pill */}
            <button
              type="button"
              onClick={() => {
                setShowReasoningMenu(!showReasoningMenu);
                setShowModelMenu(false);
              }}
              className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs font-medium text-foreground hover:bg-muted transition-colors"
            >
              <Brain className="h-3 w-3 text-indigo-500" />
              <span>{activeReasoning.label}</span>
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            </button>

            {/* Attachment Button */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center justify-center rounded-full p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              title="Attach files or context"
            >
              <Paperclip className="h-3.5 w-3.5" />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleFileChange}
            />
          </div>

          {/* Send / Stop Button */}
          <div>
            {isGenerating ? (
              <button
                type="button"
                onClick={onStop}
                className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-all shadow-sm"
                title="Stop generation"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSubmit}
                disabled={(!text.trim() && attachments.length === 0) || disabled}
                className={`inline-flex h-8 w-8 items-center justify-center rounded-full transition-all shadow-sm ${
                  text.trim() || attachments.length > 0
                    ? "bg-primary text-primary-foreground hover:bg-primary/90"
                    : "bg-muted text-muted-foreground opacity-50 cursor-not-allowed"
                }`}
                title="Send message (Enter)"
              >
                <ArrowUp className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
