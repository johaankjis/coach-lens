"""AWS-6 orchestration: one immutable, idempotent alignment review per stored design run.

    stored DesignResult (AWS-5, ready_for_alignment_review)
      -> allowlisted semantic view                 alignment_review.build_alignment_view
      -> AlignmentValidatorProvider (one call)     alignment_bedrock.BedrockAlignmentValidator
      -> strict parse + reference validation       alignment_review.parse_alignment_response
      -> AlignmentReview (design_aligned | design_questioned)

The review reads the stored, human-validated diagnosis, the stored AWS-4 decision, and the
stored AWS-5 package through `DesignService.get`, which re-runs the approval gate. It never
writes to the design service. A failed, refused, or blocked call stores nothing and may be
retried; a repeated request returns the stored record without another provider call.
"""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Protocol

from app.diagnostics.models import ProviderMetadata

from .alignment_bedrock import PROVIDER_NAME, BedrockAlignmentValidator
from .alignment_review import (ERROR_MESSAGES, AlignmentOutputError, AlignmentReview,
                               AlignmentReviewError, build_alignment_view, design_digest,
                               parse_alignment_response, to_alignment_review)
from .models import DesignResult
from .service import DesignService


class AlignmentValidatorProvider(Protocol):
    async def review(self, request: dict) -> object: ...


class UnavailableAlignmentValidator:
    async def review(self, request: dict) -> object:
        raise AlignmentReviewError("alignment_validator_unavailable")


class ControlledAlignmentValidator:
    """Test and demo double: returns the supplied response verbatim. Performs no inference."""

    controlled_fixture = True

    def __init__(self, response: object):
        self.response = response
        self.requests: list[dict] = []

    async def review(self, request: dict) -> object:
        self.requests.append(deepcopy(request))
        return self.response


def alignment_provider_kind(provider: object) -> str:
    """Classify the installed object from the object, never from a label (M3 `provider_kind`)."""
    if isinstance(provider, UnavailableAlignmentValidator):
        return "unavailable"
    if getattr(provider, "controlled_fixture", False) is True:
        return "controlled_fixture"
    return "provider"


def _metadata(provider: object) -> ProviderMetadata:
    mode = "controlled_fixture" if alignment_provider_kind(provider) == "controlled_fixture" else "provider"
    if isinstance(provider, BedrockAlignmentValidator):
        return ProviderMetadata(provider=PROVIDER_NAME, model=provider.model_id,
                                invocation_region=provider.region, generated_at=datetime.now(timezone.utc),
                                generation_mode=mode)
    return ProviderMetadata(provider="controlled fixture" if mode == "controlled_fixture" else "external provider",
                            generated_at=datetime.now(timezone.utc), generation_mode=mode)


class AlignmentReviewService:
    def __init__(self, designs: DesignService, validator: AlignmentValidatorProvider):
        self.designs = designs
        self.validator = validator
        self._reviews: dict[str, AlignmentReview] = {}
        self._lock = asyncio.Lock()

    def _current(self, hypothesis_id: str, result: DesignResult) -> AlignmentReview:
        review = self._reviews.get(hypothesis_id)
        if review is None:
            raise AlignmentReviewError("alignment_review_not_found")
        if (result.training_design is None or review.run_id != result.run_id or
                review.design_digest != design_digest(result.training_design)):
            raise AlignmentReviewError("alignment_review_stale")
        return review.model_copy(deep=True)

    def get(self, hypothesis_id: str) -> AlignmentReview:
        # The design service re-runs the approval gate and refuses a missing design run.
        return self._current(hypothesis_id, self.designs.get(hypothesis_id))

    def _criterion(self, result: DesignResult) -> str:
        return self.designs.diagnostics.signals[result.approved_diagnosis.signal_id].criterion

    async def _invoke(self, request: dict) -> str:
        try:
            raw = await self.validator.review(deepcopy(request))
        except AlignmentReviewError as exc:
            if exc.code in ("alignment_validator_unavailable", "alignment_privacy_blocked"):
                raise AlignmentReviewError(exc.code) from exc
            code = "invalid_alignment_output" if isinstance(exc, AlignmentOutputError) else "alignment_validator_failure"
            raise AlignmentReviewError(code) from exc
        except Exception as exc:
            raise AlignmentReviewError("alignment_validator_failure") from exc
        if isinstance(raw, str):
            return raw
        # Fixture adapters pass mappings through the same strict parser as model text.
        try:
            return json.dumps(raw)
        except (TypeError, ValueError) as exc:
            raise AlignmentOutputError("invalid_alignment_output") from exc

    async def review(self, hypothesis_id: str) -> AlignmentReview:
        async with self._lock:
            result = self.designs.get(hypothesis_id)
            if hypothesis_id in self._reviews:
                return self._current(hypothesis_id, result)
            view = build_alignment_view(result, self._criterion(result))
            if isinstance(self.validator, UnavailableAlignmentValidator):
                raise AlignmentReviewError("alignment_validator_unavailable")
            text = await self._invoke(view.request)
            parsed = parse_alignment_response(text, view)
            # Designs are immutable, but re-read after the call anyway so the record can never
            # describe a package other than the one currently stored.
            after = self.designs.get(hypothesis_id)
            if after.training_design is None or design_digest(after.training_design) != view.design_digest:
                raise AlignmentReviewError("alignment_review_stale")
            review = to_alignment_review(parsed, after, view, _metadata(self.validator),
                                         datetime.now(timezone.utc))
            self._reviews[hypothesis_id] = review
            return review.model_copy(deep=True)


__all__ = ["ERROR_MESSAGES", "AlignmentReviewService", "AlignmentValidatorProvider",
           "ControlledAlignmentValidator", "UnavailableAlignmentValidator", "alignment_provider_kind"]
