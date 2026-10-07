"""Tests for lib.delete_queue: the Clean Up screen's persisted
to-be-deleted list, keyed per server login."""

from lib import delete_queue


def test_queue_key_normalizes_server_url():
    assert delete_queue.queue_key("HTTP://Jelly:8096/", "u1") == "http://jelly:8096|u1"


def test_load_empty_or_invalid_returns_empty_list():
    assert delete_queue.load("", "k") == []
    assert delete_queue.load("not json", "k") == []
    assert delete_queue.load("[1, 2]", "k") == []
    assert delete_queue.load('{"k": "oops"}', "k") == []


def test_save_then_load_round_trips_in_order():
    raw = delete_queue.save("", "k", ["b", "a"])
    assert delete_queue.load(raw, "k") == ["b", "a"]


def test_save_keeps_other_servers_queues():
    raw = delete_queue.save("", "server-a", ["1"])
    raw = delete_queue.save(raw, "server-b", ["2"])
    assert delete_queue.load(raw, "server-a") == ["1"]
    assert delete_queue.load(raw, "server-b") == ["2"]


def test_saving_empty_queue_drops_the_key():
    raw = delete_queue.save("", "k", ["1"])
    raw = delete_queue.save(raw, "k", [])
    assert raw == "{}"
