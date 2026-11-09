import pytest

from savant.language import clean_label, detect_language, language_note


@pytest.mark.parametrize("text,expected", [
    ("Je confirme.", "fr"),
    ("Oui", "fr"),
    ("Supprime le rapport technique de mon VPS", "fr"),
    ("Tu peux supprimer le rendez-vous Google Meet ?", "fr"),
    ("yes, go ahead", "en"),
    ("Delete the technical report please", "en"),
    ("ok", None),
    ("", None),
    (None, None),
])
def test_language_follows_the_words_and_accents(text, expected):
    assert detect_language(text) == expected


def test_a_title_is_made_safe_to_show_in_a_sentence_and_a_link():
    assert clean_label("Rapport technique — état du VPS") == "Rapport technique — état du VPS"
    assert clean_label("a [b](http://x) `c`\n<d>") == "a b http://x c d"
    assert clean_label("  \n\t ") is None
    assert clean_label(12) is None
    long = clean_label("x" * 200)
    assert long is not None and len(long) == 80 and long.endswith("…")


def test_the_note_names_the_language_of_the_latest_message_and_forbids_mixing():
    note = language_note(["Résume", "Salut, tu peux m'aider ?"])
    assert "French" in note and "English" not in note
    assert "Never mix" in note
    assert "English" in language_note(["Please summarize the report", "Salut"])


def test_a_message_with_no_signal_keeps_the_language_of_the_conversation():
    # "ok" says nothing: the earlier turn decides (newest first).
    assert "English" in language_note(["ok", "Delete the technical report please"])
    assert "French" in language_note(["ok", "Supprime le rapport technique"])


def test_without_any_signal_there_is_no_note():
    assert language_note(["ok", "", None]) == ""
    assert language_note([]) == ""
