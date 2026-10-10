"use client";

import { AlertTriangleIcon, BoxIcon, CheckIcon, CopyIcon, RotateCcwIcon } from "lucide-react";
import { useState } from "react";

import { AgentTrace, toolMeta } from "@/components/chat/agent-trace";
import { SourceChips } from "@/components/chat/citations";
import { Markdown } from "@/components/chat/markdown";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { AssistantMessage, Message } from "@/lib/chat/state";
import { formatMs, formatNumber, formatUsd } from "@/lib/format";

export function ChatMessage({ message, onRetry }: { message: Message; onRetry?: () => void }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[0.9375rem] whitespace-pre-wrap text-primary-foreground">
          {message.content}
        </p>
      </div>
    );
  }
  return <AssistantTurn message={message} onRetry={onRetry} />;
}

function AssistantTurn({ message, onRetry }: { message: AssistantMessage; onRetry?: () => void }) {
  const { content, steps, citations, status } = message;
  const running = steps.findLast((s) => s.status === "running");

  return (
    <div className="flex gap-3">
      <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-brand text-brand-foreground">
        <BoxIcon className="size-4" />
      </span>
      <div className="min-w-0 flex-1 space-y-3">
        <AgentTrace steps={steps} />

        {status === "streaming" && !content && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="flex gap-1">
              <Dot delay="0ms" />
              <Dot delay="150ms" />
              <Dot delay="300ms" />
            </span>
            {running ? `${toolMeta(running.tool).running}…` : steps.length ? "Writing the answer…" : "Thinking…"}
          </p>
        )}

        {content && <Markdown content={content} citations={citations} />}

        {status === "stopped" && <p className="text-xs text-muted-foreground italic">Stopped.</p>}

        {status === "error" && message.error && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm">
            <AlertTriangleIcon className="size-4 text-destructive" />
            <span className="flex-1">{message.error.message}</span>
            {onRetry && (
              <Button size="sm" variant="outline" onClick={onRetry}>
                <RotateCcwIcon /> Retry
              </Button>
            )}
          </div>
        )}

        {status === "done" && (
          <>
            <SourceChips citations={citations} content={content} />
            <AnswerFooter message={message} />
          </>
        )}
      </div>
    </div>
  );
}

function AnswerFooter({ message }: { message: AssistantMessage }) {
  const { usage, latencyMs } = message;
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="flex items-center gap-3 text-xs text-muted-foreground tabular-nums">
      <Button variant="ghost" size="icon-xs" aria-label="Copy answer" onClick={copy}>
        {copied ? <CheckIcon /> : <CopyIcon />}
      </Button>
      {latencyMs != null && <span>{formatMs(latencyMs)}</span>}
      {usage && (
        <Tooltip>
          <TooltipTrigger render={<span className="cursor-default underline decoration-dotted underline-offset-2" />}>
            {formatNumber(usage.prompt_tokens + usage.completion_tokens)} tokens
            {usage.cost_usd != null && ` · ${formatUsd(usage.cost_usd)}`}
          </TooltipTrigger>
          <TooltipContent className="block text-left">
            {formatNumber(usage.prompt_tokens)} in · {formatNumber(usage.completion_tokens)} out ·{" "}
            {usage.llm_calls} LLM {usage.llm_calls === 1 ? "call" : "calls"}
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}

function Dot({ delay }: { delay: string }) {
  return <span className="size-1.5 animate-bounce rounded-full bg-current" style={{ animationDelay: delay }} />;
}
