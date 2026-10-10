import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/**
 * false during server rendering and hydration, true afterwards.
 * For UI that depends on browser-only state (localStorage) and must not cause a
 * hydration mismatch. Unlike useEffect + setState, there's no extra render pass
 * on later mounts: React reads the client snapshot directly.
 */
export function useIsClient(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
