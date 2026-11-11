"""End-to-end voice proof without a microphone: TTS(question) -> STT -> Hosted Agent -> TTS(answer).

Uses the caller's Azure session (az login): an Entra-issued Speech token on the AI Services
resource and the deployed agent's Responses endpoint. Writes question.wav and answer.wav into
--out and prints the transcript, the agent's answer, the response id and the timings.

    python3 scripts/voice_roundtrip.py --question "Quelle heure est-il à Paris ?" --out /tmp/voice
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import time
import urllib.request
from xml.sax.saxutils import escape

SPEECH = "https://fp-savant-azurian-2-resource.cognitiveservices.azure.com"
REGION = "italynorth"
AGENT = (
    "https://fp-savant-azurian-2-resource.services.ai.azure.com/api/projects/fp-savant-azurian-2"
    "/agents/sa2-agent/endpoint/protocols/openai/responses?api-version=v1"
)
VOICES = {"fr-FR": "fr-FR-DeniseNeural", "en-US": "en-US-AvaMultilingualNeural"}


def az_token(scope: str) -> str:
    return subprocess.check_output(
        ["az", "account", "get-access-token", "--scope", scope, "--query", "accessToken", "-o", "tsv"], text=True
    ).strip()


def post(url, data: bytes, headers: dict, timeout=120) -> bytes:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def speech_token() -> str:
    entra = az_token("https://cognitiveservices.azure.com/.default")
    return post(SPEECH + "/sts/v1.0/issueToken", b"", {"Authorization": f"Bearer {entra}"}).decode()


def tts(token: str, text: str, language: str) -> bytes:
    ssml = f'<speak version="1.0" xml:lang="{language}"><voice name="{VOICES[language]}">{escape(text)}</voice></speak>'
    return post(
        f"https://{REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
        ssml.encode(),
        {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "riff-16khz-16bit-mono-pcm",
        },
    )


def stt(token: str, audio: bytes, language: str) -> str:
    body = json.loads(
        post(
            f"https://{REGION}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
            f"?language={language}&format=simple",
            audio,
            {"Authorization": f"Bearer {token}", "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000"},
        )
    )
    if body.get("RecognitionStatus") != "Success":
        raise SystemExit(f"STT failed: {body.get('RecognitionStatus')}")
    return body["DisplayText"]


def ask_agent(text: str) -> tuple[str, str]:
    entra = az_token("https://ai.azure.com/.default")
    body = json.loads(
        post(
            AGENT,
            json.dumps({"input": text, "stream": False}).encode(),
            {"Authorization": f"Bearer {entra}", "Content-Type": "application/json"},
            timeout=240,
        )
    )
    answer = "".join(
        part.get("text", "")
        for item in body.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )
    return answer, body.get("id", "")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--question", required=True)
    parser.add_argument("--language", default="fr-FR", choices=sorted(VOICES))
    parser.add_argument("--out", default=".")
    args = parser.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    token = speech_token()
    timings = {}
    started = time.monotonic()
    question_audio = tts(token, args.question, args.language)
    (out / "question.wav").write_bytes(question_audio)
    t = time.monotonic()
    heard = stt(token, question_audio, args.language)
    timings["stt"] = time.monotonic() - t
    t = time.monotonic()
    answer, response_id = ask_agent(heard)
    timings["agent"] = time.monotonic() - t
    t = time.monotonic()
    (out / "answer.wav").write_bytes(tts(token, answer[:1200], args.language))
    timings["tts"] = time.monotonic() - t
    print(
        json.dumps(
            {
                "heard": heard,
                "answer": answer,
                "response_id": response_id,
                "seconds": {k: round(v, 1) for k, v in timings.items()},
                "total_seconds": round(time.monotonic() - started, 1),
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
