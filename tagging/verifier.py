"""
LLM verification layer for semantic topic tagging.

This module implements the third stage of the topic-tagging pipeline.

Pipeline
--------
1. Anchor layer proposes deterministic topic candidates.
2. Embedding layer computes cosine similarity.
3. Candidates whose similarity falls inside the configurable
   low-confidence band are verified by a local Ollama model.

The verifier never invents new topics.

It only answers the question:

    "Does this paragraph genuinely belong to this candidate topic?"

The verifier returns a structured decision together with an updated
confidence score.

Database persistence is handled by tagging.pipeline.

Configuration is supplied through core.config.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import requests

from core.config import settings
from tagging.embeddings import SimilarityMatch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------


class VerificationError(RuntimeError):
    """Raised when the verification service cannot return a valid result."""


# ---------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class VerificationResult:
    """
    Result returned by the verifier.

    Attributes
    ----------
    accepted
        True if the LLM accepts the topic.

    topic
        Candidate topic.

    confidence
        Final confidence assigned by the verifier.

    reason
        Short explanation returned by the LLM.

    layer
        Always ``"llm"``.

    model
        Ollama model used for verification.
    """

    accepted: bool
    topic: str
    confidence: float
    reason: str
    model: str
    layer: str = "llm"


# ---------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------


SYSTEM_PROMPT = """
You verify semantic topic tags.

You never invent new topics.

You only decide whether the supplied topic accurately describes the
paragraph.

Respond ONLY as JSON.

Required schema:

{
  "accepted": true,
  "confidence": 0.87,
  "reason": "short explanation"
}

Rules:

- confidence must be between 0 and 1
- accepted must be true or false
- do not include markdown
- do not include commentary
""".strip()


def build_prompt(
    paragraph: str,
    candidate: SimilarityMatch,
) -> str:
    """
    Build the user prompt.

    Parameters
    ----------
    paragraph
        Paragraph text.

    candidate
        Candidate topic from the embedding layer.
    """

    return f"""
Paragraph

{paragraph}

Candidate topic

{candidate.topic}

Embedding similarity

{candidate.similarity:.3f}

Matched anchor

{candidate.matched_phrase}

Does the candidate topic accurately describe the paragraph?

Return JSON only.
""".strip()


# ---------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------


class OllamaClient:
    """
    Lightweight Ollama HTTP client.

    Uses the native /api/generate endpoint.

    A client instance is reusable and thread-safe provided that
    the underlying requests.Session is not modified externally.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        session: requests.Session | None = None,
    ) -> None:

        self.base_url = (
            base_url
            or settings.ollama_base_url
        ).rstrip("/")

        self.model = (
            model
            or settings.ollama_model
        )

        self.timeout = (
            timeout
            or settings.ollama_timeout_seconds
        )

        self.session = (
            session
            if session is not None
            else requests.Session()
        )

    @property
    def endpoint(self) -> str:
        """Return the Ollama generate endpoint."""

        return f"{self.base_url}/api/generate"

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """
        Execute a generation request.

        Returns
        -------
        str
            Raw model response.

        Raises
        ------
        VerificationError
            If the request fails or the response is malformed.
        """

        payload = {
            "model": self.model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "options": {
                "temperature": 0.0,
            },
        }

        logger.debug(
            "Submitting verification request to Ollama."
        )

        try:

            response = self.session.post(
                self.endpoint,
                json=payload,
                timeout=self.timeout,
            )

            response.raise_for_status()

        except requests.RequestException as exc:

            raise VerificationError(
                "Unable to contact Ollama."
            ) from exc

        try:

            body: dict[str, Any] = response.json()

        except ValueError as exc:

            raise VerificationError(
                "Ollama returned invalid JSON."
            ) from exc

        if "response" not in body:

            raise VerificationError(
                "Missing 'response' field in Ollama reply."
            )

        return str(body["response"])


# ---------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------


def parse_verification_response(
    text: str,
    *,
    topic: str,
    model: str,
) -> VerificationResult:
    """
    Parse the JSON returned by the LLM.

    Raises
    ------
    VerificationError
        If parsing fails or required fields are absent.
    """

    try:

        payload = json.loads(text)

    except json.JSONDecodeError as exc:

        raise VerificationError(
            "Verifier returned invalid JSON."
        ) from exc

    try:

        accepted = bool(payload["accepted"])
        confidence = float(payload["confidence"])
        reason = str(payload["reason"])

    except KeyError as exc:

        raise VerificationError(
            "Missing required verification field."
        ) from exc

    confidence = max(
        0.0,
        min(
            1.0,
            confidence,
        ),
    )

    return VerificationResult(
        accepted=accepted,
        topic=topic,
        confidence=confidence,
        reason=reason,
        model=model,
    )


# ---------------------------------------------------------------------
# Verification service
# ---------------------------------------------------------------------


class TagVerifier:
    """
    Verify low-confidence semantic topic candidates using a local
    Ollama model.

    This service is intentionally stateless apart from its client
    dependency, allowing it to be reused throughout a batch run.
    """

    def __init__(
        self,
        client: OllamaClient | None = None,
        *,
        max_retries: int | None = None,
    ) -> None:

        self._client = client or OllamaClient()

        self._max_retries = (
            max_retries
            if max_retries is not None
            else settings.ollama_max_retries
        )

    # --------------------------------------------------------------

    @property
    def model_name(self) -> str:
        """Return the configured Ollama model name."""

        return self._client.model

    # --------------------------------------------------------------

    def verify(
        self,
        paragraph: str,
        candidate: SimilarityMatch,
    ) -> VerificationResult:
        """
        Verify a candidate topic.

        Parameters
        ----------
        paragraph
            Paragraph text.

        candidate
            Candidate topic generated by the embedding layer.

        Returns
        -------
        VerificationResult

        Raises
        ------
        VerificationError
            If all retry attempts fail.
        """

        prompt = build_prompt(
            paragraph=paragraph,
            candidate=candidate,
        )

        last_error: Exception | None = None

        for attempt in range(
            1,
            self._max_retries + 1,
        ):

            try:

                raw = self._client.generate(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=prompt,
                )

                result = parse_verification_response(
                    raw,
                    topic=candidate.topic,
                    model=self.model_name,
                )

                logger.debug(
                    "Verifier accepted=%s "
                    "topic=%s confidence=%.3f",
                    result.accepted,
                    result.topic,
                    result.confidence,
                )

                return result

            except VerificationError as exc:

                logger.warning(
                    "Verification attempt %d/%d failed: %s",
                    attempt,
                    self._max_retries,
                    exc,
                )

                last_error = exc

        assert last_error is not None

        raise last_error


# ---------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------


_default_client: OllamaClient | None = None
_default_verifier: TagVerifier | None = None


def get_client() -> OllamaClient:
    """
    Return the process-wide Ollama client.
    """

    global _default_client

    if _default_client is None:
        _default_client = OllamaClient()

    return _default_client


def get_verifier() -> TagVerifier:
    """
    Return the process-wide verifier instance.
    """

    global _default_verifier

    if _default_verifier is None:

        _default_verifier = TagVerifier(
            client=get_client(),
        )

    return _default_verifier


# ---------------------------------------------------------------------
# Convenience API
# ---------------------------------------------------------------------


def verify_candidate(
    paragraph: str,
    candidate: SimilarityMatch,
) -> VerificationResult:
    """
    Verify a single candidate topic.
    """

    return get_verifier().verify(
        paragraph,
        candidate,
    )


def verify_candidates(
    paragraph: str,
    candidates: list[SimilarityMatch],
) -> list[VerificationResult]:
    """
    Verify multiple candidate topics.

    Parameters
    ----------
    paragraph
        Paragraph text.

    candidates
        Candidate topics requiring verification.

    Returns
    -------
    list[VerificationResult]

        Only verified candidates are returned. Ordering is preserved.
    """

    verifier = get_verifier()

    results: list[VerificationResult] = []

    for candidate in candidates:

        results.append(
            verifier.verify(
                paragraph,
                candidate,
            )
        )

    return results


# ---------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------

__all__ = [
    "OllamaClient",
    "SYSTEM_PROMPT",
    "TagVerifier",
    "VerificationError",
    "VerificationResult",
    "build_prompt",
    "get_client",
    "get_verifier",
    "parse_verification_response",
    "verify_candidate",
    "verify_candidates",
]