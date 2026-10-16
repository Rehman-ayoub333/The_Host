import event_bus


def test_stamp_adds_an_id_and_timestamp_and_never_touches_session_id():
    event = {"type": "recommendation", "item": "Chicken Burger"}

    stamped = event_bus.stamp(event)

    assert stamped is event
    assert isinstance(stamped["event_id"], int)
    assert stamped["event_id"] >= 1
    assert stamped["timestamp"]
    assert "session_id" not in stamped


def test_event_ids_increase():
    first = event_bus.stamp({"type": "a"})["event_id"]
    second = event_bus.stamp({"type": "b"})["event_id"]
    assert second > first


def test_publish_stamps_an_unstamped_event():
    event_bus.publish({"type": "order_updated", "session_id": None})

    assert len(event_bus.PUBLISHED) == 1
    published = event_bus.PUBLISHED[0]
    assert isinstance(published["event_id"], int)
    assert published["timestamp"]


def test_publish_keeps_an_event_id_that_was_already_stamped():
    """03 section 2: one shape, two delivery paths, the same event_id on both."""
    event = event_bus.stamp({"type": "agent_state_changed", "state": "LISTENING"})
    stamped_id = event["event_id"]
    stamped_timestamp = event["timestamp"]

    event_bus.publish(event)

    assert list(event_bus.PUBLISHED) == [event]
    assert event_bus.PUBLISHED[0]["event_id"] == stamped_id
    assert event_bus.PUBLISHED[0]["timestamp"] == stamped_timestamp


def test_publish_threadsafe_behaves_like_publish():
    event_bus.publish_threadsafe({"type": "order_created", "session_id": "a1b2c3d4"})

    assert len(event_bus.PUBLISHED) == 1
    assert event_bus.PUBLISHED[0]["session_id"] == "a1b2c3d4"
    assert isinstance(event_bus.PUBLISHED[0]["event_id"], int)


def test_a_heartbeat_is_never_given_an_event_id():
    event_bus.publish({"type": "heartbeat"})

    beat = event_bus.PUBLISHED[0]
    assert "event_id" not in beat
    assert beat["timestamp"]


def test_published_is_bounded():
    for index in range(600):
        event_bus.publish({"type": "agent_state_changed", "state": "LISTENING", "n": index})
    assert len(event_bus.PUBLISHED) == 500
    assert event_bus.PUBLISHED[-1]["n"] == 599


def test_register_and_unregister_track_observers():
    first, second = object(), object()
    event_bus.register(first, "dashboard")
    event_bus.register(second, "smd")
    assert event_bus.sockets() == {first: "dashboard", second: "smd"}

    event_bus.unregister(first)
    assert event_bus.sockets() == {second: "smd"}
    event_bus.unregister(first)  # unregistering twice is harmless
    assert event_bus.sockets() == {second: "smd"}


# --------------------------------------------------------------- filter_for


def test_the_dashboard_sees_every_event_unchanged():
    for event_type in (
        "memory_updated", "agent_activity", "vision_update", "system_status_changed",
        "order_created", "visitor_identified", "speech_transcript", "heartbeat",
    ):
        event = {"type": event_type, "final": False, "order": {"guest_name": "Ahmed"}}
        assert event_bus.filter_for("dashboard", event) is event


def test_smd_never_receives_a_private_event():
    for event_type in (
        "memory_updated", "agent_activity", "vision_update", "system_status_changed",
        "speech_transcript",
    ):
        assert event_bus.filter_for("smd", {"type": event_type}) is None


def test_smd_never_receives_an_unknown_event_type():
    assert event_bus.filter_for("smd", {"type": "something_new"}) is None


def test_smd_receives_no_transcript_at_all():
    """16 section 2o item 2: transcripts reach the operator only."""
    partial = {"type": "speech_transcript", "role": "agent", "text": "Let me", "final": False}
    final = {"type": "speech_transcript", "role": "agent", "text": "Let me check", "final": True}

    assert event_bus.filter_for("smd", partial) is None
    assert event_bus.filter_for("smd", final) is None


def test_the_dashboard_still_receives_both_transcript_kinds_unchanged():
    partial = {"type": "speech_transcript", "role": "visitor", "text": "A chicken", "final": False}
    final = {"type": "speech_transcript", "role": "visitor", "text": "A chicken burger", "final": True}

    assert event_bus.filter_for("dashboard", partial) is partial
    assert event_bus.filter_for("dashboard", final) is final


def test_speech_transcript_is_listed_as_never_for_smd():
    assert "speech_transcript" in event_bus.SMD_NEVER
    assert "speech_transcript" not in event_bus.SMD_ALLOWED


def test_smd_receives_a_reduced_visitor_identified():
    event = {
        "type": "visitor_identified", "name": "Ahmed", "returning": True, "visits": 3,
        "favorite_item": "Chicken Burger", "last_order": "Chicken Burger",
        "event_id": 7, "timestamp": "2026-10-08T12:00:00", "session_id": "a1b2c3d4",
    }

    view = event_bus.filter_for("smd", event)

    assert view == {
        "type": "visitor_identified", "name": "Ahmed", "returning": True,
        "event_id": 7, "timestamp": "2026-10-08T12:00:00", "session_id": "a1b2c3d4",
    }
    # The original is untouched.
    assert event["visits"] == 3


def test_smd_order_objects_lose_the_guest_name():
    for event_type in ("order_created", "order_updated"):
        event = {
            "type": event_type,
            "order": {"id": 27, "guest_name": "Ahmed", "status": "CONFIRMED"},
            "session_id": "a1b2c3d4",
        }

        view = event_bus.filter_for("smd", event)

        assert "guest_name" not in view["order"]
        assert view["order"]["id"] == 27
        assert event["order"]["guest_name"] == "Ahmed"


def test_smd_snapshot_orders_lose_the_guest_name():
    event = {
        "type": "state_snapshot",
        "active_orders": [{"id": 27, "guest_name": "Ahmed"}, {"id": 28, "guest_name": None}],
    }

    view = event_bus.filter_for("smd", event)

    assert all("guest_name" not in order for order in view["active_orders"])
    assert event["active_orders"][0]["guest_name"] == "Ahmed"


def test_smd_receives_order_ready_with_the_customer_name():
    event = {"type": "order_ready", "order_id": 27, "customer_name": "Ahmed"}
    assert event_bus.filter_for("smd", event) == event
