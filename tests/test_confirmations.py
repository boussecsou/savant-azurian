from savant.confirmations import confirmation_text, generic_confirmation, result_text, say

PAGE = "40feba09656f814b9365c25afdbcf977"
OTHER = "40feba09656f8100aaaaaaaaaaaaaaaa"
LINK = f"https://www.notion.so/{PAGE}"


def delete(ids, labels=None, name="notion-delete-pages", key="page_ids"):
    return {"name": name, "args": {key: ids, "user_confirmed": True}, "labels": labels or {}}


def test_a_deletion_is_asked_in_the_owners_language_with_the_title():
    fr = confirmation_text(delete([PAGE], {PAGE: "Rapport technique — état du VPS"}), "fr")
    assert fr == f"Tu veux que je mette la page [Rapport technique — état du VPS]({LINK}) à la corbeille ?"
    en = confirmation_text(delete([PAGE], {PAGE: "VPS report"}), "en")
    assert en == f"Do you want me to move the page [VPS report]({LINK}) to the trash?"


def test_without_a_title_the_question_still_names_the_page_and_never_shows_a_bare_url():
    fr = confirmation_text(delete([PAGE]), "fr")
    assert fr == f"Tu veux que je mette [cette page]({LINK}) à la corbeille ?"
    assert "https" not in fr.replace(f"]({LINK})", "")


def test_several_pages_and_databases_are_counted():
    many = confirmation_text(delete([PAGE, OTHER], {PAGE: "A"}), "fr")
    assert many.startswith("Tu veux que je mette ces 2 pages à la corbeille : [A](") and "[2](" in many
    database = confirmation_text(delete([PAGE], {PAGE: "Tâches"}, "notion-delete-databases", "database_ids"), "fr")
    assert "la base de données [Tâches](" in database and "avec toutes ses lignes" in database
    assert "and all its rows" in confirmation_text(
        delete([PAGE], None, "notion-delete-databases", "database_ids"), "en"
    )


def test_an_edit_is_worded_from_the_exact_arguments():
    replace = {
        "name": "notion-update-page",
        "labels": {PAGE: "Notes"},
        "args": {"page_id": PAGE, "command": "replace_content", "new_str": "Bonjour"},
    }
    assert (
        confirmation_text(replace, "fr")
        == f"Tu veux que je remplace tout le contenu de [Notes]({LINK}) par « Bonjour » ?"
    )
    update = {
        "name": "notion-update-page",
        "labels": {},
        "args": {
            "page_id": PAGE,
            "command": "update_content",
            "content_updates": [{"old_str": "a", "new_str": "b"}, {"old_str": "c", "new_str": ""}],
        },
    }
    assert confirmation_text(update, "en") == (
        f"In [this page]({LINK}), do you want me to replace “a” with “b”, then remove “c”?"
    )


def test_anything_else_falls_back_to_a_complete_localized_question():
    operation = {"name": "notion-create-pages", "args": {"pages": ["x"]}}
    assert confirmation_text(operation, "fr") is None
    assert (
        generic_confirmation(operation, "fr")
        == 'Tu confirmes l\'opération `notion-create-pages` avec ces paramètres : {"pages": ["x"]} ?'
    )
    assert generic_confirmation(operation, None).startswith("Do you confirm `notion-create-pages`")


def test_a_malformed_id_is_never_turned_into_a_link():
    assert confirmation_text(delete(["not-an-id"]), "fr") is None


def test_outcomes_follow_the_language():
    assert say("cancelled", "fr") == "C'est annulé, je n'ai rien modifié."


def test_the_outcome_is_a_plain_sentence_about_what_was_done():
    titled = delete([PAGE], {PAGE: "ADR-017 — Azure AI Search"})
    assert (
        result_text(titled, "fr", False) == "C'est fait, j'ai mis la page « ADR-017 — Azure AI Search » à la corbeille."
    )
    assert result_text(titled, "en", False) == "Done: I moved the page “ADR-017 — Azure AI Search” to the trash."
    assert result_text(delete([PAGE]), "fr", False) == "C'est fait, j'ai mis la page à la corbeille."
    assert result_text(delete([PAGE, OTHER]), "fr", False) == "C'est fait, j'ai mis les 2 pages à la corbeille."
    assert (
        result_text(delete([PAGE], name="notion-delete-databases", key="database_ids"), "en", False)
        == "Done: I moved the database to the trash."
    )
    edit = {"name": "notion-update-page", "args": {"page_id": PAGE}, "labels": {PAGE: "Plan"}}
    assert result_text(edit, "fr", False) == "C'est fait, j'ai modifié la page « Plan »."
    assert result_text({"name": "code_interpreter", "args": {}}, "fr", False) == "C'est fait."
    assert result_text(titled, "fr", True).startswith("Ça n'a pas marché")
    # Read aloud as is: no link, no URL.
    assert "http" not in result_text(titled, "fr", False)
