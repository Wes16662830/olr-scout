import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

/** Fetch JSON from the API, optionally re-polling every `pollMs`. */
export function useData<T>(path: string | null, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api.get<T>(path));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
      if ((e as Error).name === "AuthError" || (e as Error).message === "login required") window.dispatchEvent(new Event("olr-auth"));
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    load();
    if (!pollMs) return;
    const t = setInterval(load, pollMs);
    return () => clearInterval(t);
  }, [load, pollMs]);
  return { data, error, loading, reload: load, setData };
}
