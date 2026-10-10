import { useCallback, useEffect, useRef, useState } from "react";

// Polls `fn` every `intervalMs` while mounted (and immediately on mount).
// Returns { data, error, loading, refresh }. Keeps the last good data on error.
export function usePoll(fn, intervalMs, deps = []) {
  const [state, setState] = useState({ data: undefined, error: null, loading: true });
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const refresh = useCallback(async () => {
    try {
      const data = await fnRef.current();
      setState({ data, error: null, loading: false });
    } catch (error) {
      setState((s) => ({ ...s, error, loading: false }));
    }
  }, []);

  useEffect(() => {
    let alive = true;
    let timer;
    const tick = async () => {
      await refresh();
      if (alive && intervalMs) timer = setTimeout(tick, intervalMs);
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, refresh, ...deps]);

  return { ...state, refresh };
}

// Minimal hash router: "#/alerts/123" -> ["alerts", "123"].
export function useRoute() {
  const parse = () => (window.location.hash.replace(/^#\/?/, "") || "").split("/").filter(Boolean).map(decodeURIComponent);
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const onChange = () => setRoute(parse());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export const navigate = (path) => {
  window.location.hash = path.startsWith("#") ? path : `#${path}`;
};
