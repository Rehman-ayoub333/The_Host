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

    assert event_bus.PUBLISHED == [event]
    assert event_bus.PUBLISHED[0]["event_id"] == stamped_id
    assert event_bus.PUBLISHED[0]["timestamp"] == stamped_timestamp


def test_publish_threadsafe_behaves_like_publish():
    event_bus.publish_threadsafe({"type": "order_created", "session_id": "a1b2c3d4"})

    assert len(event_bus.PUBLISHED) == 1
    assert event_bus.PUBLISHED[0]["session_id"] == "a1b2c3d4"
    assert isinstance(event_bus.PUBLISHED[0]["event_id"], int)
