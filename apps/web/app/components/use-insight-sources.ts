"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { loadHomeSources } from "../../lib/home/load";
import { buildHomeReadModel, type HomeReadModel, type HomeSources } from "../../lib/home/read-model";

export type InsightLoad = {
  sources: HomeSources | null;
  model: HomeReadModel | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
};

/**
 * Loads one signal's backend state (or the backend's first signal) for the pages that display
 * downstream artifacts: Training, Role-Play, and KPI Tracker. Raw sources are kept beside the
 * read-model because the AWS-5 package itself is rendered from the backend payload.
 */
export function useInsightSources(signalId: string | null): InsightLoad {
  const [sources, setSources] = useState<HomeSources | null>(null);
  const [model, setModel] = useState<HomeReadModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const requestNumber = useRef(0);
  const load = useCallback(async () => {
    const request = ++requestNumber.current;
    setLoading(true);
    setError(null);
    try {
      const loaded = await loadHomeSources(signalId);
      if (request !== requestNumber.current) return;
      setSources(loaded);
      setModel(buildHomeReadModel(loaded));
      setLoadedFor(signalId);
    } catch (cause) {
      if (request === requestNumber.current) setError((cause as Error).message);
    } finally {
      if (request === requestNumber.current) setLoading(false);
    }
  }, [signalId]);
  useEffect(() => {
    void Promise.resolve().then(load);
  }, [load]);
  const current = loadedFor === signalId;
  return { sources: current ? sources : null, model: current ? model : null,
    error: current ? error : null, loading: loading || !current, reload: () => void load() };
}
