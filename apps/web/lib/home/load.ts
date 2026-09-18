/**
 * Collects the backend payloads the Home read-model is built from.
 *
 * Every route used here is a read route that already exists: M3 signals and records, the AWS-3
 * stored semantic review, the AWS-4 intervention record, the AWS-5 / M5 design result, and the
 * AWS-6 stored alignment review (`GET /designs/diagnoses/{id}/alignment-review`).
 */
import { isAlignmentReview, isDesignResult, type AlignmentReview, type DesignResult } from "../designs";
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
import { isInterventionRecord, type InterventionRecord } from "../interventions";
import {
  buildHomeReadModel,
  isRuntimeMode,
  type HomeReadModel,
  type HomeSources,
  type InsightSources,
  type RuntimeMode,
} from "./read-model";

const optional = async <T>(request: Promise<T>, absent: (cause: ApiError) => boolean = (cause) => cause.status === 404): Promise<T | null> => {
  try {
    return await request;
  } catch (cause) {
    if (cause instanceof ApiError && absent(cause)) return null;
    throw cause;
  }
};

/**
 * The AWS-6 read route answers 404 when no review was recorded and 409 `alignment_review_stale`
 * when the stored review no longer matches the design run's digest. Both mean "no current
 * review": Home shows the stage as pending rather than rendering an outdated verdict.
 */
const noCurrentReview = (cause: ApiError) =>
  cause.status === 404 || (cause.status === 409 && cause.code === "alignment_review_stale");

async function loadMode(): Promise<RuntimeMode | null> {
  // Provenance is informational; a missing mode route degrades to "unknown" rather than
  // hiding the signals the backend did return.
  try {
    return await api("/mode", isRuntimeMode);
  } catch {
    return null;
  }
}

export async function loadInsight(signal: Signal): Promise<InsightSources> {
  const records: RecordState[] = await api(
    `/signals/${encodeURIComponent(signal.signal_id)}/hypotheses`,
    isRecordList,
  );
  // The M3 list is newest first; Home summarizes the latest review record only.
  const record = records[0]?.provider_hypothesis.signal_id === signal.signal_id ? records[0] : null;
  let validation: EvidenceValidation | null = null;
  let intervention: InterventionRecord | null = null;
  let design: DesignResult | null = null;
  let alignment: AlignmentReview | null = null;
  if (record) {
    const id = record.provider_hypothesis.hypothesis_id;
    validation = await optional(
      api(`/hypotheses/${encodeURIComponent(id)}/evidence-validation`, isEvidenceValidation),
    );
    if (validation && validation.hypothesis_id !== id) validation = null;
    if (validated(record)) {
      // Both stores are keyed by the validated diagnosis; 404 means the stage has not run.
      [intervention, design] = await Promise.all([
        optional(api(`/diagnoses/${encodeURIComponent(id)}`, isInterventionRecord, undefined, "interventions")),
        optional(api(`/diagnoses/${encodeURIComponent(id)}`, isDesignResult, undefined, "designs")),
      ]);
      if (intervention && intervention.hypothesis_id !== id) intervention = null;
      if (design && design.diagnosis_id !== id) design = null;
      if (design?.training_design) {
        // The review is keyed by the diagnosis but belongs to one design run.
        alignment = await optional(
          api(`/diagnoses/${encodeURIComponent(id)}/alignment-review`, isAlignmentReview, undefined, "designs"),
          noCurrentReview,
        );
        if (alignment && (alignment.diagnosis_id !== id || alignment.run_id !== design.run_id)) alignment = null;
      }
    }
  }
  return { signal, record, validation, intervention, design, alignment };
}

/**
 * Home summarizes the backend's first-ordered signal. Pages that display one signal's
 * downstream artifacts (Training, Role-Play) pass the signal Home linked to; an unknown id
 * falls back to the first signal and is reported through `requested.found`.
 */
export async function loadHomeSources(signalId: string | null = null): Promise<HomeSources> {
  const [mode, signals] = await Promise.all([loadMode(), api("/signals", isSignalList)]);
  const requestedSignal = signalId ? (signals.find((signal) => signal.signal_id === signalId) ?? null) : null;
  const selected = requestedSignal ?? signals[0] ?? null;
  const priority = selected ? await loadInsight(selected) : null;
  return {
    mode,
    signals,
    priority,
    requested: signalId ? { signalId, found: requestedSignal !== null } : null,
  };
}

export async function loadHomeReadModel(signalId: string | null = null): Promise<HomeReadModel> {
  return buildHomeReadModel(await loadHomeSources(signalId));
}
