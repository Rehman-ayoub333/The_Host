"""Phase 7c, 16 section 2r item 5: short replies are heard.

In Rehman's C1 test a short soft reply -- "yes", a name -- could go unheard
entirely. Two fields answer that: the server may start listening more readily
(the handheld microphone keeps the room out), and 300 ms of audio from before
it decided the guest had started is kept, so a quiet first syllable is not
clipped. `silence_duration_ms` is untouched at 500.
"""

from datetime import datetime

from google.genai import types

import config
import live_session


def detection() -> types.AutomaticActivityDetection:
    built = live_session.build_live_config(datetime(2026, 10, 21, 19, 0, 0))
    return built.realtime_input_config.automatic_activity_detection


def test_the_start_of_speech_sensitivity_is_high():
    found = detection().start_of_speech_sensitivity
    print("start_of_speech_sensitivity:", found)
    assert found == types.StartSensitivity.START_SENSITIVITY_HIGH


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
        types.StartSensitivity.START_SENSITIVITY_HIGH
    )
    assert found.prefix_padding_ms == 300
    assert found.silence_duration_ms == 500
