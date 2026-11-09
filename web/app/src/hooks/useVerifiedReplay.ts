import { useCallback, useEffect, useState } from "react";
import { loadReplay, type LoadOutcome } from "../lib/loader";

// One verification per page load and bundle id; pages share the result.
const cache = new Map<string, Promise<LoadOutcome>>();
let progressListeners: Array<(d: number, t: number) => void> = [];

export function useVerifiedReplay(bundleId: string | null) {
  const key = bundleId ?? "latest";
  const [outcome, setOutcome] = useState<LoadOutcome | null>(null);
  const [progress, setProgress] = useState<[number, number] | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setOutcome(null);
    const onProgress = (d: number, t: number) => live && setProgress([d, t]);
    progressListeners.push(onProgress);
    let p = cache.get(key);
    if (!p) {
      p = loadReplay(bundleId, fetch, (d, t) => progressListeners.forEach((f) => f(d, t)));
      cache.set(key, p);
    }
    p.then((o) => {
      if (o.kind === "error") cache.delete(key);   // allow retry after transient errors
      if (live) setOutcome(o);
    });
    return () => {
      live = false;
      progressListeners = progressListeners.filter((f) => f !== onProgress);
    };
  }, [key, bundleId, attempt]);

  const retry = useCallback(() => {
    cache.delete(key);
    setAttempt((n) => n + 1);
  }, [key]);
  return { outcome, progress, retry };
}
