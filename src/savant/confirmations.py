"""Sentences the server writes to the owner, in the owner's language (French or English).

The confirmation question for a protected Notion operation is built here from the exact, validated
arguments and, for readability, the title of the page read from Notion. The model never words it:
what the owner is asked to approve is always what will run. The semantic judge reads this same
text. The text is plain enough to be read aloud: links carry the title, never a bare URL.
"""

from __future__ import annotations

import json
import re

NOTION_ID = re.compile(
    r"(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\Z", re.IGNORECASE
)

MESSAGES = {
    "cancelled": {"fr": "C'est annulé, je n'ai rien modifié.", "en": "Cancelled, nothing was changed."},
    "unclear": {
        "fr": "Je ne peux pas te présenter cette opération clairement. Demande-moi quelque chose de plus petit.",
        "en": "I can't present this operation clearly. Narrow it to something smaller.",
    },
}


def say(key: str, lang: str | None) -> str:
    return MESSAGES[key]["fr" if lang == "fr" else "en"]


def result_text(operation: dict, lang: str | None, failed: bool) -> str:
    """What the owner hears once a confirmed operation has run, worded from the validated operation.

    Written by the server, never by the model, which does not read the tool's raw answer after a
    protected write. Plain enough to be read aloud: titles in quotes, no link.
    """
    fr = lang == "fr"
    if failed:
        return (
            "Ça n'a pas marché. Vérifie le résultat avant de réessayer."
            if fr
            else "That did not work. Check the result before retrying."
        )
    name, args = operation.get("name", ""), operation.get("args") or {}
    labels = operation.get("labels") if isinstance(operation.get("labels"), dict) else {}
    if name in {"notion-delete-pages", "notion-delete-databases"}:
        pages = name == "notion-delete-pages"
        ids = args.get("page_ids" if pages else "database_ids")
        ids = ids if isinstance(ids, list) else []
        title = labels.get(ids[0]) if len(ids) == 1 else None
        if fr:
            noun = "la page" if pages else "la base de données"
            if len(ids) > 1:
                what = f"les {len(ids)} pages" if pages else f"les {len(ids)} bases de données"
            else:
                what = f"{noun} « {title} »" if title else noun
            return f"C'est fait, j'ai mis {what} à la corbeille."
        noun = "the page" if pages else "the database"
        if len(ids) > 1:
            what = f"the {len(ids)} pages" if pages else f"the {len(ids)} databases"
        else:
            what = f"{noun} “{title}”" if title else noun
        return f"Done: I moved {what} to the trash."
    if name == "notion-update-page":
        title = labels.get(args.get("page_id")) if isinstance(args.get("page_id"), str) else None
        if fr:
            return f"C'est fait, j'ai modifié la page « {title} »." if title else "C'est fait, j'ai modifié la page."
        return f"Done: I updated the page “{title}”." if title else "Done: I updated the page."
    from .tools import toolbox_policy

    inner = toolbox_policy.outlook_operation(toolbox_policy.effective_call(name, args)[0])
    if inner in toolbox_policy.OUTLOOK_SENDS:
        return "C'est fait, le mail est parti." if fr else "Done: the email is sent."
    if inner in toolbox_policy.OUTLOOK_DELETES:
        return "C'est fait, le mail est supprimé." if fr else "Done: the email is deleted."
    return "C'est fait." if fr else "Done."


def _link(label: str, notion_id: str) -> str:
    return f"[{label}](https://www.notion.so/{notion_id.replace('-', '')})"


def _targets(ids: list[str], labels: dict, noun_fr: str, noun_en: str, lang: str) -> str:
    """Links for the targets: the title when known, else 'this page' (or numbers for several)."""
    if len(ids) == 1:
        title = labels.get(ids[0])
        fallback = f"cette {noun_fr}" if lang == "fr" else f"this {noun_en}"
        article = (f"la {noun_fr} " if lang == "fr" else f"the {noun_en} ") if title else ""
        return article + _link(title or fallback, ids[0])
    return ", ".join(_link(labels.get(value) or str(i + 1), value) for i, value in enumerate(ids))


def confirmation_text(operation: dict, lang: str | None) -> str | None:
    """The question for a Notion delete or edit, or None for any other operation."""
    lang = "fr" if lang == "fr" else "en"
    name, args = operation["name"], operation["args"]
    labels = operation.get("labels") if isinstance(operation.get("labels"), dict) else {}
    if name in {"notion-delete-pages", "notion-delete-databases"}:
        pages = name == "notion-delete-pages"
        ids = args.get("page_ids" if pages else "database_ids")
        if not (isinstance(ids, list) and ids and all(isinstance(i, str) and NOTION_ID.fullmatch(i) for i in ids)):
            return None
        noun_fr, noun_en = ("page", "page") if pages else ("base de données", "database")
        links = _targets(ids, labels, noun_fr, noun_en, lang)
        n = len(ids)
        if lang == "fr":
            if n == 1:
                tail = "" if pages else ", avec toutes ses lignes"
                return f"Tu veux que je mette {links} à la corbeille{tail} ?"
            what = f"ces {n} pages" if pages else f"ces {n} bases de données"
            tail = "" if pages else ", avec toutes leurs lignes"
            return f"Tu veux que je mette {what} à la corbeille{tail} : {links} ?"
        if n == 1:
            tail = "" if pages else " and all its rows"
            return f"Do you want me to move {links}{tail} to the trash?"
        what = f"these {n} pages" if pages else f"these {n} databases"
        tail = "" if pages else " and all their rows"
        return f"Do you want me to move {what}{tail} to the trash: {links}?"
    if name == "notion-update-page" and isinstance(args.get("page_id"), str) and NOTION_ID.fullmatch(args["page_id"]):
        page_id = args["page_id"]
        title = labels.get(page_id)
        page = _link(title or ("cette page" if lang == "fr" else "this page"), page_id)
        command = args.get("command")
        if command == "replace_content" and isinstance(args.get("new_str"), str):
            if lang == "fr":
                return f"Tu veux que je remplace tout le contenu de {page} par « {args['new_str']} » ?"
            return f"Do you want me to replace the whole content of {page} with “{args['new_str']}”?"
        updates = args.get("content_updates")
        if command == "update_content" and isinstance(updates, list):
            pairs = [
                (u.get("old_str", ""), u.get("new_str", ""), u.get("replace_all_matches") is True)
                for u in updates
                if isinstance(u, dict)
            ]
            if (
                pairs
                and all(isinstance(a, str) and isinstance(b, str) for a, b, _ in pairs)
                and sum(len(a) + len(b) for a, b, _ in pairs) <= 300
            ):
                if lang == "fr":
                    parts = [
                        (f"remplace « {a} » par « {b} »" if b else f"supprime « {a} »")
                        + (" (partout)" if every else "")
                        for a, b, every in pairs
                    ]
                    return f"Dans {page}, tu veux que je " + " puis ".join(parts) + " ?"
                parts = [
                    (f"replace “{a}” with “{b}”" if b else f"remove “{a}”") + (" (everywhere)" if every else "")
                    for a, b, every in pairs
                ]
                return f"In {page}, do you want me to " + ", then ".join(parts) + "?"
    return None


def generic_confirmation(operation: dict, lang: str | None) -> str:
    """A bounded, complete fallback that keeps the exact scope of any other operation."""
    encoded = json.dumps(operation["args"], ensure_ascii=False, sort_keys=True)
    if lang == "fr":
        return f"Tu confirmes l'opération `{operation['name']}` avec ces paramètres : {encoded} ?"
    return f"Do you confirm `{operation['name']}` with these parameters: {encoded}?"
