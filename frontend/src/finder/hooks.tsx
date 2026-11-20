"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  createHttpApi,
  loadConfig,
  saveConfig,
  type ApiConfig,
} from "./api/client";
import type { FinderApi } from "./api/client";
import type { Job } from "./types";

interface ApiCtx {
  api: FinderApi;
  config: ApiConfig;
  setConfig: (c: ApiConfig) => void;
  toast: (msg: string, tone?: "ok" | "error") => void;
}
const Ctx = createContext<ApiCtx | null>(null);

export function ApiProvider({
  children,
  onToast,
}: {
  children: ReactNode;
  onToast: (m: string, t?: "ok" | "error") => void;
}) {
  const [config, setConfigState] = useState<ApiConfig>({
    baseUrl: "http://localhost:8000",
    token: "",
  });
  const [ready, setReady] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setConfigState(loadConfig());
    setReady(true);
  }, []);
  const api = useMemo(() => createHttpApi(config.baseUrl, config.token), [config.baseUrl, config.token]);
  const setConfig = useCallback((c: ApiConfig) => {
    saveConfig(c);
    setConfigState(c);
  }, []);
  if (!ready) return null;
  return (
    <Ctx.Provider value={{ api, config, setConfig, toast: onToast }}>
      {children}
    </Ctx.Provider>
  );
}

export function useApi() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useApi outside ApiProvider");
  return c;
}

/** Load data; re-runs when deps change. Ignores stale responses. */
export function useLoad<T>(
  fn: (api: FinderApi) => Promise<T>,
  deps: unknown[],
) {
  const { api } = useApi();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });
  useEffect(() => {
    let alive = true;

    setLoading(true);
    setError(null);
    fnRef
      .current(api)
      .then((d) => alive && setData(d))
      .catch(
        (e: unknown) =>
          alive &&
          setError(e instanceof Error ? e.message : "Unbekannter Fehler"),
      )
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, tick, ...deps]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}

/**
 * Poll a job until it succeeds or fails. Polling stops automatically when the
 * component unmounts (= the view is left) or the job id changes.
 */
export function useJobPolling(
  jobId: string | null,
  onDone: (job: Job) => void,
  interval = 1500,
) {
  const { api } = useApi();
  const [job, setJob] = useState<Job | null>(null);
  const doneRef = useRef(onDone);
  useEffect(() => {
    doneRef.current = onDone;
  });
  useEffect(() => {
    if (!jobId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setJob(null);
      return;
    }
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const j = await api.getJob(jobId);
        if (!alive) return;
        setJob(j);
        if (j.status === "succeeded" || j.status === "failed") {
          doneRef.current(j);
          return;
        }
      } catch {
        /* transient – keep polling */
      }
      if (alive) timer = setTimeout(tick, interval);
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [api, jobId, interval]);
  return job;
}
