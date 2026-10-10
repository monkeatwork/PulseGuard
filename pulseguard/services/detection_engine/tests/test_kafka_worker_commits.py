"""REMEDIATION_TASK.md C1: a message that raises is never silently lost, and
offsets never advance past a message that was neither processed nor
preserved."""

from __future__ import annotations

from pulseguard_common.kafka_worker import DEAD_LETTERED, OK, RETRY, consumer_config, handle_message


class Msg:
    def __init__(self, offset, value=b"{}"):
        self._offset, self._value = offset, value

    def value(self):
        return self._value

    def topic(self):
        return "pulseguard.events.enriched"

    def partition(self):
        return 0

    def offset(self):
        return self._offset


class Consumer:
    def __init__(self):
        self.committed, self.seeks = [], []

    def commit(self, message=None, asynchronous=True):
        assert asynchronous is False
        self.committed.append(message.offset())

    def seek(self, tp):
        self.seeks.append(tp.offset)


def test_auto_commit_is_disabled():
    assert consumer_config("k:9092", "g")["enable.auto.commit"] is False


def test_success_commits_that_message():
    c = Consumer()
    assert handle_message(Msg(7), lambda v: None, lambda m, e: None, c) == OK
    assert c.committed == [7]


def test_failing_message_is_dead_lettered_before_its_offset_is_committed():
    c, dlq = Consumer(), []

    def sink(msg, err):
        assert c.committed == []  # preserved BEFORE the commit
        dlq.append((msg.offset(), str(err)))

    def boom(v):
        raise ValueError("malformed")

    assert handle_message(Msg(8, b"not json"), boom, sink, c) == DEAD_LETTERED
    assert dlq == [(8, "malformed")]
    assert c.committed == [8]


def test_if_the_dead_letter_write_fails_the_offset_is_not_advanced():
    c = Consumer()

    def boom(v):
        raise ValueError("malformed")

    def broken_sink(msg, err):
        raise ConnectionError("dlq down")

    assert handle_message(Msg(9), boom, broken_sink, c) == RETRY
    assert c.committed == []
    assert c.seeks == [9]  # re-read on the next poll
