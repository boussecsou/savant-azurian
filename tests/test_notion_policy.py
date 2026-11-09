import copy

import pytest
from langchain_core.tools import StructuredTool

from savant.tools.notion_policy import (
    catalog_tools, protected_tool_names, requires_approval, tool_annotations,
    tool_fingerprint,
)


def tool(name="notion-fetch", annotations=None, *, metadata=None):
    async def invoke(**kwargs):
        return "ok"
    return StructuredTool.from_function(
        coroutine=invoke, name=name, description="Exact description",
        args_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        metadata=metadata if metadata is not None else {"mcp": {"tool": {"annotations": annotations or {}}}},
    )


@pytest.mark.parametrize("annotations", [{}, {"readOnlyHint": False}, {"read_only_hint": False}, {"readOnlyHint": "true"}, {"readOnlyHint": 1}, {"readOnlyHint": True, "read_only_hint": False}])
def test_missing_invalid_or_conflicting_hints_are_protected(annotations):
    assert requires_approval(tool(annotations=annotations))


@pytest.mark.parametrize("annotations", [{"readOnlyHint": True}, {"read_only_hint": True}])
def test_explicit_read_hint_supports_new_and_wire_names(annotations):
    assert not requires_approval(tool(annotations=annotations))


@pytest.mark.parametrize("name", ["notion-delete-pages", "notion-update-page", "notion-calendar-cancel-events", "notion-send-message-to-session", "update-enabled-skills"])
def test_known_writes_cannot_be_downgraded(name):
    assert requires_approval(tool(name, {"readOnlyHint": True}))


def test_new_tools_default_protected_but_explicit_official_reads_are_usable():
    assert requires_approval(tool("notion-new-operation"))
    assert not requires_approval(tool("notion-new-read", {"readOnlyHint": True}))


def test_legacy_adapter_metadata_and_preservation():
    metadata = {"readOnlyHint": True, "_meta": {"opaque": "value"}}
    candidate = tool(metadata=metadata)
    before = copy.deepcopy(candidate.metadata)
    assert not requires_approval(candidate)
    assert catalog_tools([candidate])[candidate.name] is candidate
    assert candidate.metadata == before


def test_nested_missing_annotations_does_not_fall_back_to_unrelated_metadata():
    assert requires_approval(tool(metadata={"mcp": {}, "readOnlyHint": True}))


def test_fingerprint_covers_every_consent_relevant_field():
    candidate = tool(annotations={"read_only_hint": True})
    original = tool_fingerprint(candidate)
    for field, value in [("name", "notion-other"), ("description", "Changed"),
                         ("args_schema", {"type": "object", "additionalProperties": False}),
                         ("metadata", {"mcp": {"tool": {"annotations": {"read_only_hint": False}}}})]:
        changed = candidate.model_copy(update={field: value})
        assert tool_fingerprint(changed) != original
    assert tool_fingerprint(candidate.model_copy(deep=True)) == original


def test_catalog_rejects_duplicates_and_classifies_without_losing_entries():
    read = tool(annotations={"readOnlyHint": True})
    write = tool("notion-update-page")
    unknown = tool("notion-future-tool")
    assert set(catalog_tools([read, write, unknown])) == {read.name, write.name, unknown.name}
    assert protected_tool_names([read, write, unknown]) == {write.name, unknown.name}
    with pytest.raises(ValueError, match="unique"):
        catalog_tools([read, read.model_copy()])
