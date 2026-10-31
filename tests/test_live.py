"""The notice bus behind the dashboard's live WhatsApp pane.

Written with asyncio.run() rather than an async-test plugin: the bus is
deliberately small enough not to need one.
"""
import asyncio

import pytest

from app import live


@pytest.fixture(autouse=True)
def no_leftover_subscribers():
    live._subscribers.clear()
    yield
    live._subscribers.clear()


def test_every_open_dashboard_hears_about_a_change():
    a, b = live.subscribe(), live.subscribe()
    assert live.publish("254712345678@c.us") == 2
    assert a.get_nowait() == ("activity", "254712345678@c.us")
    assert b.get_nowait() == ("activity", "254712345678@c.us")


def test_a_held_draft_is_told_apart_from_an_ordinary_message():
    queue = live.subscribe()
    live.publish("254712345678@c.us", kind="draft")
    assert queue.get_nowait() == ("draft", "254712345678@c.us")


def test_a_closed_dashboard_stops_hearing_about_them():
    queue = live.subscribe()
    live.unsubscribe(queue)
    assert live.publish("254712345678@c.us") == 0
    assert live.listeners() == 0
    live.unsubscribe(queue)        # unsubscribing twice is not an error


def test_a_dashboard_that_stopped_reading_does_not_grow_without_limit():
    queue = live.subscribe()
    for i in range(live.QUEUE_SIZE + 10):
        live.publish(f"{i}@c.us")
    assert queue.qsize() == live.QUEUE_SIZE
    # The newest notice survived; the oldest were dropped, which only costs lag.
    drained = [queue.get_nowait() for _ in range(live.QUEUE_SIZE)]
    assert drained[-1] == ("activity", f"{live.QUEUE_SIZE + 9}@c.us")


def test_waiting_for_a_change_wakes_as_soon_as_one_arrives():
    async def scenario():
        queue = live.subscribe()
        asyncio.get_running_loop().call_later(0.01, live.publish, "254712345678@c.us")
        return await asyncio.wait_for(queue.get(), timeout=2)

    assert asyncio.run(scenario()) == ("activity", "254712345678@c.us")
