"""Which language the owner writes in, and a safe label for text read from Notion.

Server-written sentences (confirmation questions, outcomes) follow the owner's language. The
detection is a cheap word and accent count, not a model call: it must be instant and can never
fail. No signal (a bare "ok") returns None, so the caller keeps the language already in use.
"""

from __future__ import annotations

import re
import unicodedata

_FRENCH_WORDS = frozenset(
    "je tu il elle nous vous ils le la les un une des du de est pas oui non merci supprime supprimer "
    "confirme confirmer annule annuler accord stp svp peux peut veux voudrais ce cette cet mon ma mes ton "
    "ta tes et pour avec dans sur que qui bien bon voila ca ça super vas lance fais fait efface retire "
    "rapport page rendez-vous aussi mais ou où quoi comment pourquoi quel quelle quels quelles ai suis "
    "sont c j l d s n qu m t".split()
)
_ENGLISH_WORDS = frozenset(
    "the you your is are was yes no please delete remove go ahead do does it this that with for and to my "
    "can could would want confirm cancel sure okay thanks thank what which who how why have has i me we "
    "they of in on at be not just report page meeting also but or".split()
)
_ACCENTS = frozenset("àâäçéèêëîïôöùûüÿœ")


def detect_language(text: object) -> str | None:
    """ "fr" or "en" when the text leans clearly one way, else None."""
    if not isinstance(text, str) or not text.strip():
        return None
    lowered = text.lower()
    words = re.findall(r"[^\W\d_]+", lowered)
    french = 2 * sum(1 for ch in lowered if ch in _ACCENTS) + sum(1 for w in words if w in _FRENCH_WORDS)
    english = sum(1 for w in words if w in _ENGLISH_WORDS)
    if french > english:
        return "fr"
    if english > french:
        return "en"
    return None


_LANGUAGE_NAMES = {"fr": "French", "en": "English"}


def language_note(user_texts) -> str:
    """A per-turn instruction to answer in ONE language: the owner's, read from their messages.

    `user_texts` are the owner's messages, newest first. A message with no signal ("ok", a bare name)
    keeps the language of the earlier ones; with no signal at all there is no note (the model decides).
    A one-word request ("Résume") once drew an answer that drifted into Spanish halfway through.
    """
    for text in user_texts:
        name = _LANGUAGE_NAMES.get(detect_language(text) or "")
        if name:
            return (
                f"\nLanguage: the owner writes in {name}. Answer entirely in {name}. Never mix in another "
                "language, not even one word or phrase (names, titles and quoted text excepted)."
            )
    return ""


def clean_label(value: object, limit: int = 80) -> str | None:
    """A title taken from Notion, made safe to show inside a sentence and a Markdown link.

    Titles are untrusted data: no control characters, no brackets, parentheses, backticks or angle
    brackets that could break a link or inject markup, bounded length.
    """
    if not isinstance(value, str):
        return None
    text = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in value)
    text = re.sub(r"[\[\]()<>`]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
