from datetime import UTC, datetime

from savant import identity
from savant.identity import current_time_context


def test_clock_uses_the_owner_timezone():
    now = datetime(2026, 1, 15, 12, 3, tzinfo=UTC)
    assert (
        current_time_context(now)
        == "\nCurrent date and time (Africa/Casablanca): Thursday 15 January 2026, 13:03 (UTC+01:00)."
    )


def test_clock_follows_the_moroccan_ramadan_offset():
    now = datetime(2026, 2, 25, 12, 0, tzinfo=UTC)
    assert "12:00 (UTC+00:00)" in current_time_context(now)


def test_clock_falls_back_to_labelled_utc_without_a_tz_database(monkeypatch):
    def missing(_):
        raise identity.ZoneInfoNotFoundError("Africa/Casablanca")

    monkeypatch.setattr(identity, "ZoneInfo", missing)
    now = datetime(2026, 11, 5, 16, 3, tzinfo=UTC)
    assert "(UTC): Thursday 05 November 2026, 16:03 (UTC+00:00)" in current_time_context(now)


def test_the_stable_identity_carries_no_clock():
    assert "Current date" not in identity.BASE_IDENTITY


def test_the_identity_reads_for_intent_and_keeps_changes_behind_confirmation():
    base = identity.BASE_IDENTITY
    assert "Read for intent" in base and '"savon" is Savant' in base
    assert "Anticipate the obvious next step" in base
    # Initiative never reaches a write: the confirmation layers stay the lock.
    assert "still goes through the owner's" in base


def test_voice_style_asks_for_punctuated_speech_and_english_words():
    style = identity.VOICE_STYLE
    assert "voice assistant" in style
    assert "comma or a period at every natural breath" in style
    assert "English" in style and "no Markdown" in style
