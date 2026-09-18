"use client";

import { useCallback, useEffect, useState } from "react";
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
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const loaded = await loadHomeSources(signalId);
      setSources(loaded);
      setModel(buildHomeReadModel(loaded));
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setLoading(false);
    }
  }, [signalId]);
  useEffect(() => {
    void Promise.resolve().then(load);
  }, [load]);
  return { sources, model, error, loading, reload: () => void load() };
}
