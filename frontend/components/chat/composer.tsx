"use client";

import { ArrowUpIcon, SquareIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const MAX_CHARS = 2000; // mirrors MAX_MESSAGE_CHARS on the backend

type Props = {
  onSend: (text: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
};

export function Composer({ onSend, onStop, isStreaming, disabled }: Props) {
  const [text, setText] = useState("");
  const tooLong = text.length > MAX_CHARS;
  const canSend = !disabled && !isStreaming && text.trim().length > 0 && !tooLong;

  function submit() {
    if (!canSend) return;
    onSend(text);
    setText("");
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="relative rounded-2xl border bg-background shadow-sm transition-colors focus-within:border-ring"
    >
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          // Enter sends, Shift+Enter adds a line; ignore Enter while an IME is composing.
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder="Ask the operations agent…"
        aria-label="Message"
        disabled={disabled}
        rows={1}
        className="max-h-48 min-h-12 resize-none border-0 bg-transparent py-3 pr-14 pl-4 shadow-none focus-visible:ring-0 dark:bg-transparent"
      />
      <div className="absolute right-2 bottom-2 flex items-center gap-2">
        {text.length > MAX_CHARS * 0.8 && (
          <span className={cn("text-xs tabular-nums", tooLong ? "text-destructive" : "text-muted-foreground")}>
            {text.length}/{MAX_CHARS}
          </span>
        )}
        {isStreaming ? (
          <Button type="button" size="icon" variant="secondary" onClick={onStop} aria-label="Stop answering">
            <SquareIcon className="size-3 fill-current" />
          </Button>
        ) : (
          <Button type="submit" size="icon" disabled={!canSend} aria-label="Send" className="bg-brand text-brand-foreground hover:bg-brand/85">
            <ArrowUpIcon />
          </Button>
        )}
      </div>
    </form>
  );
}
