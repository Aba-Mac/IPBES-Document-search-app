"""
Unit tests for tagging.verifier.

These tests validate:

* prompt generation
* Ollama client behaviour
* JSON response parsing
* verification result creation
* TagVerifier orchestration
* retry behaviour
* error handling

All LLM calls are mocked.
No Ollama server is required.
"""

from __future__ import annotations

import json

import pytest
import requests

from tagging.embeddings import SimilarityMatch
from tagging.verifier import OllamaClient
from tagging.verifier import SYSTEM_PROMPT
from tagging.verifier import TagVerifier
from tagging.verifier import VerificationError
from tagging.verifier import VerificationResult
from tagging.verifier import build_prompt
from tagging.verifier import get_client
from tagging.verifier import get_verifier
from tagging.verifier import parse_verification_response
from tagging.verifier import verify_candidate
from tagging.verifier import verify_candidates


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def candidate() -> SimilarityMatch:

    return SimilarityMatch(
        topic="data_management",
        similarity=0.74,
        confidence=0.74,
        matched_phrase="data management",
    )


@pytest.fixture
def accepted_response() -> str:

    return json.dumps(
        {
            "accepted": True,
            "confidence": 0.91,
            "reason": "The paragraph discusses managing data.",
        }
    )


@pytest.fixture
def rejected_response() -> str:

    return json.dumps(
        {
            "accepted": False,
            "confidence": 0.12,
            "reason": "The paragraph is unrelated.",
        }
    )


# ---------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------


def test_system_prompt_exists() -> None:

    assert "JSON" in SYSTEM_PROMPT

    assert "accepted" in SYSTEM_PROMPT


def test_build_prompt(
    candidate: SimilarityMatch,
) -> None:

    prompt = build_prompt(
        paragraph="Data management improves quality.",
        candidate=candidate,
    )

    assert "Data management improves quality." in prompt

    assert "data_management" in prompt

    assert "0.740" in prompt

    assert "data management" in prompt


# ---------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------


def test_parse_valid_response(
    accepted_response: str,
) -> None:

    result = parse_verification_response(
        accepted_response,
        topic="data_management",
        model="qwen2.5:7B-instruct",
    )

    assert isinstance(
        result,
        VerificationResult,
    )

    assert result.accepted is True

    assert result.topic == "data_management"

    assert result.confidence == pytest.approx(
        0.91
    )

    assert result.model == "qwen2.5:7B-instruct"

    assert result.layer == "llm"


def test_parse_rejected_response(
    rejected_response: str,
) -> None:

    result = parse_verification_response(
        rejected_response,
        topic="licensing",
        model="qwen2.5:7B-instruct",
    )

    assert result.accepted is False

    assert result.confidence == pytest.approx(
        0.12
    )


def test_parse_invalid_json() -> None:

    with pytest.raises(
        VerificationError
    ):

        parse_verification_response(
            "not json",
            topic="test",
            model="model",
        )


def test_parse_missing_field() -> None:

    payload = json.dumps(
        {
            "accepted": True,
            "confidence": 0.9,
        }
    )

    with pytest.raises(
        VerificationError
    ):

        parse_verification_response(
            payload,
            topic="test",
            model="model",
        )


def test_parse_confidence_clamped() -> None:

    payload = json.dumps(
        {
            "accepted": True,
            "confidence": 4,
            "reason": "test",
        }
    )

    result = parse_verification_response(
        payload,
        topic="test",
        model="model",
    )

    assert result.confidence == 1.0


# ---------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------


class FakeResponse:
    """
    Minimal requests response replacement.
    """

    def __init__(
        self,
        payload,
    ) -> None:

        self.payload = payload

    def raise_for_status(
        self,
    ) -> None:

        return None

    def json(
        self,
    ):

        return self.payload


class FakeSession:

    def __init__(
        self,
        response,
    ) -> None:

        self.response = response

        self.called = False

    def post(
        self,
        *args,
        **kwargs,
    ):

        self.called = True

        return FakeResponse(
            self.response
        )


def test_ollama_client_success(
    accepted_response: str,
) -> None:

    session = FakeSession(
        {
            "response": accepted_response
        }
    )

    client = OllamaClient(
        base_url="http://localhost:11434",
        model="qwen2.5:7B-instruct",
        session=session,
    )

    result = client.generate(
        system_prompt="system",
        user_prompt="user",
    )

    assert session.called is True

    assert json.loads(
        result
    )["accepted"] is True


def test_ollama_client_missing_response() -> None:

    session = FakeSession(
        {}
    )

    client = OllamaClient(
        session=session,
    )

    with pytest.raises(
        VerificationError
    ):

        client.generate(
            system_prompt="system",
            user_prompt="user",
        )


# ---------------------------------------------------------------------
# Ollama client failures
# ---------------------------------------------------------------------


class FailingSession:

    def post(
        self,
        *args,
        **kwargs,
    ):

        raise requests.RequestException(
            "connection failed"
        )


def test_ollama_client_connection_failure() -> None:

    client = OllamaClient(
        session=FailingSession(),
    )

    with pytest.raises(
        VerificationError
    ):

        client.generate(
            system_prompt="system",
            user_prompt="user",
        )


class StatusFailureResponse:

    def raise_for_status(
        self,
    ) -> None:

        raise requests.HTTPError(
            "server failure"
        )

    def json(
        self,
    ):

        return {}


class StatusFailureSession:

    def post(
        self,
        *args,
        **kwargs,
    ):

        return StatusFailureResponse()


def test_ollama_http_failure() -> None:

    client = OllamaClient(
        session=StatusFailureSession(),
    )

    with pytest.raises(
        VerificationError
    ):

        client.generate(
            system_prompt="system",
            user_prompt="user",
        )


class InvalidJSONResponse:

    def raise_for_status(
        self,
    ) -> None:

        return None

    def json(
        self,
    ):

        raise ValueError(
            "invalid"
        )


class InvalidJSONSession:

    def post(
        self,
        *args,
        **kwargs,
    ):

        return InvalidJSONResponse()


def test_ollama_invalid_json_failure() -> None:

    client = OllamaClient(
        session=InvalidJSONSession(),
    )

    with pytest.raises(
        VerificationError
    ):

        client.generate(
            system_prompt="system",
            user_prompt="user",
        )


# ---------------------------------------------------------------------
# TagVerifier
# ---------------------------------------------------------------------


class FakeClient:

    def __init__(
        self,
        response: str,
    ) -> None:

        self.response = response

        self.model = (
            "qwen2.5:7B-instruct"
        )

        self.calls = 0

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:

        self.calls += 1

        return self.response


def test_tag_verifier_accepts_candidate(
    candidate: SimilarityMatch,
    accepted_response: str,
) -> None:

    client = FakeClient(
        accepted_response
    )

    verifier = TagVerifier(
        client=client,
    )

    result = verifier.verify(
        "Data management improves quality.",
        candidate,
    )

    assert isinstance(
        result,
        VerificationResult,
    )

    assert result.accepted is True

    assert result.topic == (
        "data_management"
    )

    assert client.calls == 1


def test_tag_verifier_rejects_candidate(
    candidate: SimilarityMatch,
    rejected_response: str,
) -> None:

    verifier = TagVerifier(
        client=FakeClient(
            rejected_response
        )
    )

    result = verifier.verify(
        "A paragraph about unrelated topics.",
        candidate,
    )

    assert result.accepted is False

    assert result.confidence == pytest.approx(
        0.12
    )


def test_tag_verifier_model_name(
    candidate: SimilarityMatch,
    accepted_response: str,
) -> None:

    verifier = TagVerifier(
        client=FakeClient(
            accepted_response
        )
    )

    assert verifier.model_name == (
        "qwen2.5:7B-instruct"
    )


# ---------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------


class RetryClient:

    model = "qwen2.5:7B-instruct"

    def __init__(self):

        self.calls = 0

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:

        self.calls += 1

        if self.calls < 3:

            raise VerificationError(
                "temporary failure"
            )

        return json.dumps(
            {
                "accepted": True,
                "confidence": 0.9,
                "reason": "accepted",
            }
        )


def test_retry_succeeds_after_failure(
    candidate: SimilarityMatch,
) -> None:

    client = RetryClient()

    verifier = TagVerifier(
        client=client,
        max_retries=3,
    )

    result = verifier.verify(
        "paragraph",
        candidate,
    )

    assert result.accepted is True

    assert client.calls == 3


class AlwaysFailClient:

    model = "qwen2.5:7B-instruct"

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:

        raise VerificationError(
            "failure"
        )


def test_retry_exhaustion(
    candidate: SimilarityMatch,
) -> None:

    verifier = TagVerifier(
        client=AlwaysFailClient(),
        max_retries=2,
    )

    with pytest.raises(
        VerificationError
    ):

        verifier.verify(
            "paragraph",
            candidate,
        )


# ---------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------


def test_verify_candidate_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    candidate: SimilarityMatch,
) -> None:

    expected = VerificationResult(
        accepted=True,
        topic="test",
        confidence=1.0,
        reason="ok",
        model="model",
    )

    class FakeVerifier:

        def verify(
            self,
            paragraph,
            candidate,
        ):

            return expected

    monkeypatch.setattr(
        "tagging.verifier.get_verifier",
        lambda: FakeVerifier(),
    )

    result = verify_candidate(
        "paragraph",
        candidate,
    )

    assert result == expected


def test_verify_candidates_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    candidate: SimilarityMatch,
) -> None:

    expected = VerificationResult(
        accepted=True,
        topic="test",
        confidence=1.0,
        reason="ok",
        model="model",
    )

    class FakeVerifier:

        def verify(
            self,
            paragraph,
            candidate,
        ):

            return expected

    monkeypatch.setattr(
        "tagging.verifier.get_verifier",
        lambda: FakeVerifier(),
    )

    results = verify_candidates(
        "paragraph",
        [
            candidate,
            candidate,
        ],
    )

    assert results == [
        expected,
        expected,
    ]


# ---------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------


def test_get_client_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    import tagging.verifier as module

    module._default_client = None

    sentinel = object()

    monkeypatch.setattr(
        module,
        "OllamaClient",
        lambda: sentinel,
    )

    assert get_client() is sentinel

    assert get_client() is sentinel


def test_get_verifier_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    import tagging.verifier as module

    module._default_verifier = None

    sentinel = object()

    monkeypatch.setattr(
        module,
        "TagVerifier",
        lambda client: sentinel,
    )

    monkeypatch.setattr(
        module,
        "get_client",
        lambda: object(),
    )

    assert get_verifier() is sentinel

    assert get_verifier() is sentinel


# ---------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------


def test_verification_result_layer(
    candidate: SimilarityMatch,
    accepted_response: str,
) -> None:

    result = TagVerifier(
        client=FakeClient(
            accepted_response
        )
    ).verify(
        "paragraph",
        candidate,
    )

    assert result.layer == "llm"


def test_verification_confidence_bounds(
    candidate: SimilarityMatch,
) -> None:

    response = json.dumps(
        {
            "accepted": True,
            "confidence": -5,
            "reason": "test",
        }
    )

    result = TagVerifier(
        client=FakeClient(response)
    ).verify(
        "paragraph",
        candidate,
    )

    assert result.confidence == 0.0


def test_candidate_topic_preserved(
    candidate: SimilarityMatch,
    accepted_response: str,
) -> None:

    result = TagVerifier(
        client=FakeClient(
            accepted_response
        )
    ).verify(
        "paragraph",
        candidate,
    )

    assert result.topic == candidate.topic