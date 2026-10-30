"""Phase 7c, 16 section 2r item 5: short replies are heard.

In Rehman's C1 test a short soft reply -- "yes", a name -- could go unheard
entirely. 300 ms of audio from before the server decided the guest had started
is kept, so a quiet first syllable is not clipped. `silence_duration_ms` is
untouched at 500.

2r item 5 also set the start sensitivity to HIGH, on the reasoning that "the
handheld microphone keeps the room out". That microphone is not what the stall
runs on, and on a laptop or TV microphone HIGH made THE HOST answer the hall
rather than the guest, so the field is now `config.START_SENSITIVITY` and
defaults to LOW. The prefix padding is what keeps short replies heard.
"""

from datetime import datetime

from google.genai import types

import config
import live_session


def detection() -> types.AutomaticActivityDetection:
    built = live_session.build_live_config(datetime(2026, 10, 21, 19, 0, 0))
    return built.realtime_input_config.automatic_activity_detection


def test_the_start_of_speech_sensitivity_follows_the_config():
    """And its default is LOW, so THE HOST answers the guest, not the room.

    2r item 5 set this to HIGH because "the handheld microphone keeps the room
    out". On the laptop and TV microphones actually in use it does not, and HIGH
    had Gemini treating the queue behind the guest as a guest starting to talk.
    `prefix_padding_ms` below is what protects a short soft reply, so the bar
    here can be raised without giving that back.
    """
    found = detection().start_of_speech_sensitivity
    print("START_SENSITIVITY:", config.START_SENSITIVITY, "->", found)
    assert config.START_SENSITIVITY == "LOW"
    assert found == types.StartSensitivity.START_SENSITIVITY_LOW


def test_a_handheld_microphone_can_still_ask_for_high(monkeypatch):
    monkeypatch.setattr(config, "START_SENSITIVITY", "HIGH")
    found = detection().start_of_speech_sensitivity
    print("with HIGH:", found)
    assert found == types.StartSensitivity.START_SENSITIVITY_HIGH


def test_an_unreadable_sensitivity_falls_back_to_low(monkeypatch, caplog):
    """A typo in the environment must not take the stall down mid-gala, and of
    the two LOW is the safe one to land on."""
    import logging

    monkeypatch.setattr(config, "START_SENSITIVITY", "MEDUIM")
    with caplog.at_level(logging.WARNING, logger="live_session"):
        found = detection().start_of_speech_sensitivity

    print("with a typo:", found)
    print("warnings:", [record.getMessage() for record in caplog.records])
    assert found == types.StartSensitivity.START_SENSITIVITY_LOW
    assert "unknown START_SENSITIVITY 'MEDUIM' -- using LOW" in [
        record.getMessage() for record in caplog.records
    ]


def test_the_prefix_padding_is_three_hundred_milliseconds():
    print("PREFIX_PADDING_MS:", config.PREFIX_PADDING_MS)
    assert config.PREFIX_PADDING_MS == 300
    assert detection().prefix_padding_ms == 300


def test_the_silence_duration_is_unchanged_at_five_hundred():
    # 2r item 5 changes two fields and no more: a shorter or longer silence
    # would re-open the end-of-turn behaviour decided in 2j item 6.
    print("SILENCE_DURATION_MS:", config.SILENCE_DURATION_MS)
    assert config.SILENCE_DURATION_MS == 500
    assert detection().silence_duration_ms == 500


def test_the_end_of_speech_sensitivity_stays_at_the_server_default():
    found = detection().end_of_speech_sensitivity
    print("end_of_speech_sensitivity:", found)
    assert found is None


def test_automatic_detection_is_not_disabled():
    # The whole point is that the server does the detecting; a true here would
    # hand turn-taking back to the page.
    assert detection().disabled in (None, False)


def test_the_config_survives_a_resume_handle():
    # A rebuilt connection must carry the same two fields, or short replies
    # would be heard before a reconnection and missed after one.
    built = live_session.build_live_config(
        datetime(2026, 10, 21, 19, 0, 0), resume_handle="a-handle"
    )
    found = built.realtime_input_config.automatic_activity_detection
    assert found.start_of_speech_sensitivity == (
        types.StartSensitivity.START_SENSITIVITY_LOW
    )
    assert found.prefix_padding_ms == 300
    assert found.silence_duration_ms == 500
