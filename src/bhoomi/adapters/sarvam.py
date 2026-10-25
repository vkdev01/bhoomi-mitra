"""Sarvam AI adapters.

One class per capability, all sharing an HTTP client and the subscription key.
The chat adapter is the only one the agent loop depends on; speech and
translation are used by the web layer for the voice interface.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from typing import Any

from bhoomi.adapters.http import HttpJsonClient
from bhoomi.domain.errors import UpstreamUnavailableError
from bhoomi.domain.messages import Message, ModelTurn, ToolCall, ToolSpec


class SarvamLanguageModel:
    """Implements ``LanguageModel`` over Sarvam's chat completions endpoint."""

    def __init__(
        self,
        client: HttpJsonClient,
        *,
        model: str = "sarvam-105b",
        temperature: float = 0.2,
    ) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature

    def respond(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> ModelTurn:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [m.as_dict() for m in messages],
            "temperature": self._temperature,
        }
        if tools:
            body["tools"] = [t.as_dict() for t in tools]
            body["tool_choice"] = "auto"

        payload = self._client.post("v1/chat/completions", json_body=body)
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise UpstreamUnavailableError(
                f"unexpected chat response shape: {payload!r}"
            ) from exc

        calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            calls.append(
                ToolCall(
                    name=str(function.get("name", "")),
                    arguments=_load_arguments(function.get("arguments")),
                    call_id=str(raw.get("id") or function.get("name", "")),
                )
            )

        return ModelTurn(
            content=str(message.get("content") or ""),
            tool_calls=tuple(calls),
        )


class SarvamTranscriber:
    """Implements ``SpeechTranscriber`` over Sarvam's speech-to-text endpoint."""

    def __init__(
        self, client: HttpJsonClient, *, model: str = "saaras:v3", mode: str = "transcribe"
    ) -> None:
        self._client = client
        self._model = model
        self._mode = mode

    def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        language_code: str | None = None,
    ) -> str:
        boundary = "----bhoomiBoundary"
        parts: list[bytes] = []

        def field(name: str, value: str) -> None:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n".encode()
            )

        field("model", self._model)
        field("mode", self._mode)
        if language_code:
            field("language_code", language_code)
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\nContent-Type: audio/wav\r\n\r\n'
            ).encode()
        )
        parts.append(audio)
        parts.append(f"\r\n--{boundary}--\r\n".encode())

        payload = self._client.post_multipart(
            "speech-to-text",
            body=b"".join(parts),
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        transcript = (payload or {}).get("transcript")
        if not transcript:
            raise UpstreamUnavailableError("speech-to-text returned no transcript")
        return str(transcript)


class SarvamSynthesizer:
    """Implements ``SpeechSynthesizer`` over Sarvam's text-to-speech endpoint."""

    def __init__(
        self,
        client: HttpJsonClient,
        *,
        model: str = "bulbul:v3",
        speaker: str = "anushka",
        codec: str = "mp3",
    ) -> None:
        self._client = client
        self._model = model
        self._speaker = speaker
        self._codec = codec

    def synthesize(self, text: str, *, language_code: str) -> bytes:
        payload = self._client.post(
            "text-to-speech",
            json_body={
                "text": text,
                "target_language_code": language_code,
                "model": self._model,
                "speaker": self._speaker,
                "output_audio_codec": self._codec,
            },
        )
        audios = (payload or {}).get("audios") or []
        if not audios:
            raise UpstreamUnavailableError("text-to-speech returned no audio")
        return base64.b64decode(audios[0])


class SarvamTranslator:
    """Implements ``Translator`` over Sarvam's translate endpoint."""

    def __init__(self, client: HttpJsonClient, *, model: str = "mayura:v1") -> None:
        self._client = client
        self._model = model

    def translate(
        self,
        text: str,
        *,
        source_language_code: str,
        target_language_code: str,
    ) -> str:
        if source_language_code == target_language_code:
            return text
        payload = self._client.post(
            "translate",
            json_body={
                "input": text,
                "source_language_code": source_language_code,
                "target_language_code": target_language_code,
                "model": self._model,
            },
        )
        translated = (payload or {}).get("translated_text")
        if not translated:
            raise UpstreamUnavailableError("translate returned no text")
        return str(translated)


def _load_arguments(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return raw
    if not raw:
        return {}
    import json

    try:
        loaded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, Mapping) else {}
