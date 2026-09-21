"""Cloud Translation and Text-to-Speech wrappers with free-tier friendly defaults.

* Cloud Translation Basic (v2) offers 500,000 characters per month at no cost.
* Text-to-Speech Standard voices offer 4 million characters per month at no
  cost; WaveNet/Neural2 voices offer 1 million. Standard voices are therefore
  the default and can be upgraded with ``TTS_VOICE_TIER=wavenet``.

Set ``ALERTS_MOCK_GOOGLE_APIS=true`` for local development: translation becomes
an identity function tagged with the target language and no audio is
synthesised, in which case the caller falls back to Twilio's built-in speech.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from vayusetu_common.retry import retry_with_backoff

logger = logging.getLogger(__name__)

# BCP-47 locale and voice name prefixes for the Indian languages supported by
# Cloud Text-to-Speech. English uses the Indian English voice.
LANGUAGE_VOICES: Dict[str, Dict[str, str]] = {
    "en": {"locale": "en-IN", "standard": "en-IN-Standard-A", "wavenet": "en-IN-Wavenet-A", "label": "English"},
    "hi": {"locale": "hi-IN", "standard": "hi-IN-Standard-A", "wavenet": "hi-IN-Wavenet-A", "label": "Hindi"},
    "bn": {"locale": "bn-IN", "standard": "bn-IN-Standard-A", "wavenet": "bn-IN-Wavenet-A", "label": "Bengali"},
    "ta": {"locale": "ta-IN", "standard": "ta-IN-Standard-A", "wavenet": "ta-IN-Wavenet-A", "label": "Tamil"},
    "te": {"locale": "te-IN", "standard": "te-IN-Standard-A", "wavenet": "te-IN-Standard-A", "label": "Telugu"},
    "mr": {"locale": "mr-IN", "standard": "mr-IN-Standard-A", "wavenet": "mr-IN-Wavenet-A", "label": "Marathi"},
    "gu": {"locale": "gu-IN", "standard": "gu-IN-Standard-A", "wavenet": "gu-IN-Wavenet-A", "label": "Gujarati"},
    "kn": {"locale": "kn-IN", "standard": "kn-IN-Standard-A", "wavenet": "kn-IN-Wavenet-A", "label": "Kannada"},
    "ml": {"locale": "ml-IN", "standard": "ml-IN-Standard-A", "wavenet": "ml-IN-Wavenet-A", "label": "Malayalam"},
    "pa": {"locale": "pa-IN", "standard": "pa-IN-Standard-A", "wavenet": "pa-IN-Wavenet-A", "label": "Punjabi"},
}

SUPPORTED_LANGUAGES = tuple(LANGUAGE_VOICES.keys())


def normalise_language(code: Optional[str]) -> str:
    """Reduce a language tag to the supported two-letter code (default English)."""
    if not code:
        return "en"
    primary = code.strip().lower().replace("_", "-").split("-")[0]
    return primary if primary in LANGUAGE_VOICES else "en"


@dataclass
class TranslatedText:
    text: str
    language: str
    source_language: str
    translated: bool


class Translator:
    """Translate English alert text into the authority's preferred language."""

    def __init__(self, mock: bool = False, client: Optional[Any] = None) -> None:
        self.mock = mock
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from google.cloud import translate_v2

            self._client = translate_v2.Client()
        return self._client

    def translate(self, text: str, target_language: str, source_language: str = "en") -> TranslatedText:
        target = normalise_language(target_language)
        if target == source_language:
            return TranslatedText(text=text, language=target, source_language=source_language, translated=False)
        if self.mock:
            return TranslatedText(text=f"[{target}] {text}", language=target, source_language=source_language, translated=True)
        translated = self._translate_remote(text, target, source_language)
        return TranslatedText(text=translated, language=target, source_language=source_language, translated=True)

    @retry_with_backoff(max_attempts=4, base_delay=1.0, max_delay=20.0, operation_name="cloud_translation")
    def _translate_remote(self, text: str, target: str, source: str) -> str:
        result = self.client.translate(text, target_language=target, source_language=source, format_="text")
        translated = result.get("translatedText") if isinstance(result, dict) else None
        if not translated:
            raise RuntimeError("Cloud Translation returned an empty result")
        import html

        return html.unescape(translated)


@dataclass
class SynthesizedSpeech:
    audio_bytes: bytes
    content_type: str
    voice_name: str
    locale: str


class SpeechSynthesizer:
    """Synthesise MP3 audio for a voice call."""

    def __init__(self, voice_tier: str = "standard", mock: bool = False, client: Optional[Any] = None, speaking_rate: float = 0.92) -> None:
        self.voice_tier = "wavenet" if voice_tier.lower() == "wavenet" else "standard"
        self.mock = mock
        self.speaking_rate = speaking_rate
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from google.cloud import texttospeech

            self._client = texttospeech.TextToSpeechClient()
        return self._client

    def voice_for(self, language: str) -> tuple[str, str]:
        config = LANGUAGE_VOICES[normalise_language(language)]
        return config["locale"], config[self.voice_tier]

    def synthesize(self, text: str, language: str) -> Optional[SynthesizedSpeech]:
        """Return MP3 audio, or None in mock mode (caller uses Twilio <Say>)."""
        locale, voice_name = self.voice_for(language)
        if self.mock:
            logger.info("TTS mock mode; skipping synthesis", extra={"voice": voice_name})
            return None
        audio = self._synthesize_remote(text, locale, voice_name)
        return SynthesizedSpeech(audio_bytes=audio, content_type="audio/mpeg", voice_name=voice_name, locale=locale)

    @retry_with_backoff(max_attempts=4, base_delay=1.0, max_delay=20.0, operation_name="text_to_speech")
    def _synthesize_remote(self, text: str, locale: str, voice_name: str) -> bytes:
        from google.cloud import texttospeech

        response = self.client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=text),
            voice=texttospeech.VoiceSelectionParams(language_code=locale, name=voice_name),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=self.speaking_rate,
                effects_profile_id=["telephony-class-application"],
            ),
        )
        if not response.audio_content:
            raise RuntimeError("Text-to-Speech returned no audio")
        return bytes(response.audio_content)
