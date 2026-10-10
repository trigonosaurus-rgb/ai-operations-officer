import { Suspense } from "react";

import { ChatApp, ChatSkeleton } from "@/components/chat/chat-app";
import { getChatMeta } from "@/lib/api/server";

// Server Component. It starts the metadata fetch but doesn't await it: the promise
// is streamed to the Client Component, whose parts unwrap it with use() as it resolves.
export default function ChatPage() {
  return (
    <Suspense fallback={<ChatSkeleton />}>
      <ChatApp meta={getChatMeta()} />
    </Suspense>
  );
}
