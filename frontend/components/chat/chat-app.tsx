"use client";

import { BoxIcon, FileSearchIcon, MenuIcon, PlusIcon, DatabaseIcon, CalculatorIcon } from "lucide-react";
import { Suspense, useEffect, useRef, useState } from "react";

import { ChatMessage } from "@/components/chat/message";
import { Composer } from "@/components/chat/composer";
import {
  BackendNotice,
  DataSourcesCard,
  ExampleList,
  ListSkeleton,
  Suggestions,
} from "@/components/chat/meta-views";
import { SiteHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useChat } from "@/hooks/use-chat";
import { useIsClient } from "@/hooks/use-is-client";
import type { ChatMeta } from "@/lib/api/types";

export function ChatApp({ meta }: { meta: Promise<ChatMeta> }) {
  // The conversation lives in localStorage, which the server can't see: render a
  // neutral skeleton on the server, the real workspace once we're in the browser.
  const isClient = useIsClient();
  return isClient ? <ChatWorkspace meta={meta} /> : <ChatSkeleton />;
}

function ChatWorkspace({ meta }: { meta: Promise<ChatMeta> }) {
  const { messages, isStreaming, send, stop, retry, reset } = useChat();
  const last = messages.at(-1);
  // A finished answer proves the backend is up, even if it was down at page load.
  const backendAnswered = last?.role === "assistant" && last.status === "done";
  const [menuOpen, setMenuOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const lastScrollTop = useRef(0);

  // Follow the stream only while the user is at the bottom; scrolling up to read
  // an earlier answer shouldn't be hijacked by incoming tokens.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTo({ top: el.scrollHeight });
  }, [messages]);

  function ask(question: string) {
    setMenuOpen(false);
    stickToBottom.current = true;
    void send(question);
  }

  function retryLast() {
    stickToBottom.current = true;
    retry();
  }

  function newChat() {
    setMenuOpen(false);
    reset();
  }

  const sidebar = (
    <SidebarContent meta={meta} onAsk={ask} onNewChat={newChat} disabled={isStreaming} />
  );

  return (
    <div className="flex h-dvh flex-col">
      <SiteHeader
        leading={
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open menu" onClick={() => setMenuOpen(true)}>
            <MenuIcon />
          </Button>
        }
      />
      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent side="left" className="w-80 gap-0 p-0 pt-10">
          <SheetTitle className="sr-only">Menu</SheetTitle>
          {sidebar}
        </SheetContent>
      </Sheet>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-72 shrink-0 border-r bg-muted/20 lg:flex">{sidebar}</aside>

        <main className="flex min-w-0 flex-1 flex-col">
          <div
            ref={scrollRef}
            onScroll={(e) => {
              // Only a scroll *up* means the user left the bottom. Checking distance alone
              // races with streaming: our own scrollTo's event can arrive after new content.
              const el = e.currentTarget;
              if (el.scrollHeight - el.scrollTop - el.clientHeight < 80) stickToBottom.current = true;
              else if (el.scrollTop < lastScrollTop.current) stickToBottom.current = false;
              lastScrollTop.current = el.scrollTop;
            }}
            className="flex-1 overflow-y-auto"
          >
            {messages.length === 0 ? (
              <EmptyState meta={meta} onAsk={ask} />
            ) : (
              <div className="mx-auto w-full max-w-3xl space-y-8 px-4 py-6">
                {messages.map((m, i) => (
                  <ChatMessage key={m.id} message={m} onRetry={i === messages.length - 1 ? retryLast : undefined} />
                ))}
              </div>
            )}
          </div>

          <div className="mx-auto w-full max-w-3xl space-y-2 px-4 pt-2 pb-4">
            {!backendAnswered && (
              <Suspense fallback={null}>
                <BackendNotice meta={meta} />
              </Suspense>
            )}
            <Composer onSend={ask} onStop={stop} isStreaming={isStreaming} />
            <p className="text-center text-xs text-muted-foreground">
              Answers come from an AI agent: check the trace and sources. All company data is fictional.
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}

type SidebarProps = {
  meta: Promise<ChatMeta>;
  onAsk: (q: string) => void;
  onNewChat: () => void;
  disabled: boolean;
};

function SidebarContent({ meta, onAsk, onNewChat, disabled }: SidebarProps) {
  return (
    <div className="flex min-h-0 w-full flex-col">
      <div className="p-3">
        <Button variant="outline" className="w-full justify-start" onClick={onNewChat}>
          <PlusIcon /> New chat
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1 pb-3">
        <div className="px-1">
          <Suspense fallback={<ListSkeleton rows={10} />}>
            <ExampleList meta={meta} onAsk={onAsk} disabled={disabled} />
          </Suspense>
        </div>
      </div>
      <div className="border-t p-3">
        <Suspense fallback={<Skeleton className="h-24 rounded-xl" />}>
          <DataSourcesCard meta={meta} />
        </Suspense>
      </div>
    </div>
  );
}

const CAPABILITIES = [
  { icon: FileSearchIcon, title: "Reads policies", text: "Hybrid search over 6 company documents, with page-level citations." },
  { icon: DatabaseIcon, title: "Queries live data", text: "Writes SQL against shipments, docks and inventory, read-only and guarded." },
  { icon: CalculatorIcon, title: "Prices exactly", text: "Freight quotes come from a deterministic calculator, not LLM math." },
];

function EmptyState({ meta, onAsk }: { meta: Promise<ChatMeta>; onAsk: (q: string) => void }) {
  return (
    <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-4 py-10">
      <div className="mb-8 space-y-3">
        <span className="flex size-11 items-center justify-center rounded-xl bg-brand text-brand-foreground shadow-sm">
          <BoxIcon className="size-6" />
        </span>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">AI Operations Officer</h1>
        <p className="max-w-xl text-muted-foreground">
          An agent for <span className="text-foreground">Harbor &amp; Pine Logistics</span>, a fictional
          3PL with four Midwest warehouses. Ask about dock availability, shipment delays, carrier
          contracts, hazmat rules or freight prices, and open the trace to see how it got the answer.
        </p>
      </div>
      <div className="mb-8 grid gap-3 sm:grid-cols-3">
        {CAPABILITIES.map(({ icon: Icon, title, text }) => (
          <div key={title} className="rounded-xl border bg-muted/20 p-3">
            <Icon className="mb-2 size-4 text-brand" />
            <p className="text-sm font-medium">{title}</p>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{text}</p>
          </div>
        ))}
      </div>
      <Suspense fallback={<div className="grid gap-2 sm:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-18 rounded-xl" />)}</div>}>
        <Suggestions meta={meta} onAsk={onAsk} />
      </Suspense>
    </div>
  );
}

export function ChatSkeleton() {
  return (
    <div className="flex h-dvh flex-col">
      <SiteHeader />
      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-72 shrink-0 space-y-4 border-r bg-muted/20 p-3 lg:block">
          <Skeleton className="h-8" />
          <ListSkeleton rows={10} />
        </aside>
        <main className="flex flex-1 flex-col justify-end px-4 pb-4">
          <Skeleton className="mx-auto h-12 w-full max-w-3xl rounded-2xl" />
        </main>
      </div>
    </div>
  );
}
