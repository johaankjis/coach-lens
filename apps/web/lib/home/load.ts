/**
 * Collects the backend payloads the Home read-model is built from.
 *
 * Wiring points for later milestones live here: when AWS-4 / AWS-5 / AWS-6 expose read routes,
 * fetch them in `loadHomeSources` and pass them through `HomeSources`; the builder in
 * `read-model.ts` then replaces the corresponding pending slot.
 */
import { isDesignResult, type DesignResult } from "../designs";
import {
  api,
  ApiError,
  isEvidenceValidation,
  isRecordList,
  isSignalList,
  validated,
  type EvidenceValidation,
  type RecordState,
  type Signal,
} from "../diagnostics";
import { buildHomeReadModel, isRuntimeMode, type HomeReadModel, type HomeSources, type RuntimeMode } from "./read-model";

const optional = async <T>(request: Promise<T>): Promise<T | null> => {
  try {
    return await request;
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) return null;
    throw cause;
  }
};

async function loadMode(): Promise<RuntimeMode | null> {
  // Provenance is informational; a missing mode route degrades to "unknown" rather than
  // hiding the signals the backend did return.
  try {
    return await api("/mode", isRuntimeMode);
  } catch {
    return null;
  }
}

async function loadPriority(signal: Signal): Promise<NonNullable<HomeSources["priority"]>> {
  const records: RecordState[] = await api(
    `/signals/${encodeURIComponent(signal.signal_id)}/hypotheses`,
    isRecordList,
  );
  // The M3 list is newest first; Home summarizes the latest review record only.
  const record = records[0] ?? null;
  let validation: EvidenceValidation | null = null;
  let design: DesignResult | null = null;
  if (record) {
    const id = record.provider_hypothesis.hypothesis_id;
    validation = await optional(
      api(`/hypotheses/${encodeURIComponent(id)}/evidence-validation`, isEvidenceValidation),
    );
    if (validation && validation.hypothesis_id !== id) validation = null;
    if (validated(record)) {
      design = await optional(
        api(`/diagnoses/${encodeURIComponent(id)}`, isDesignResult, undefined, "designs"),
      );
      if (design && design.diagnosis_id !== id) design = null;
    }
  }
  return { signal, record, validation, design };
}

export async function loadHomeSources(): Promise<HomeSources> {
  const [mode, signals] = await Promise.all([loadMode(), api("/signals", isSignalList)]);
  const priority = signals[0] ? await loadPriority(signals[0]) : null;
  return { mode, signals, priority };
}

export async function loadHomeReadModel(): Promise<HomeReadModel> {
  return buildHomeReadModel(await loadHomeSources());
}
