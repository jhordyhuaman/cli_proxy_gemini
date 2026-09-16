import asyncio

import pytest

from mgm.transport import (
    AuthError,
    FakeTransport,
    InferenceBroker,
    Message,
    TransportError,
)


@pytest.fixture
def messages():
    return [Message(role="user", content="hola")]


def make_broker(script, sleeps=None, **kwargs):
    transport = FakeTransport(script=script, chunk_delay=kwargs.pop("chunk_delay", 0.0))
    recorded = [] if sleeps is None else sleeps

    async def fake_sleep(delay):
        recorded.append(delay)

    broker = InferenceBroker(transport, sleep=fake_sleep, **kwargs)
    return broker, recorded


async def collect(broker, messages):
    return [chunk.text async for chunk in broker.stream(messages)]


async def test_streams_chunks_through(messages):
    broker, _ = make_broker([["a", "b"]])
    assert await collect(broker, messages) == ["a", "b"]


async def test_retries_on_transport_error_with_backoff(messages):
    broker, sleeps = make_broker(
        [TransportError("caído"), TransportError("sigue caído"), "ok"],
        base_delay=1.0,
    )
    assert await collect(broker, messages) == ["ok"]
    assert sleeps == [1.0, 2.0]


async def test_auth_error_is_not_retried(messages):
    broker, sleeps = make_broker([AuthError("cookie vencida"), "ok"])
    with pytest.raises(AuthError):
        await collect(broker, messages)
    assert sleeps == []


async def test_gives_up_after_max_retries(messages):
    broker, sleeps = make_broker(
        [TransportError("x")] * 4,
        max_retries=2,
        base_delay=1.0,
    )
    with pytest.raises(TransportError):
        await collect(broker, messages)
    assert sleeps == [1.0, 2.0]


async def test_no_retry_after_first_chunk_yielded(messages):
    broker, sleeps = make_broker([["parcial", TransportError("a mitad")]])
    chunks = []
    with pytest.raises(TransportError):
        async for chunk in broker.stream(messages):
            chunks.append(chunk.text)
    assert chunks == ["parcial"]
    assert sleeps == []


async def test_single_queue_serializes_streams(messages):
    broker, _ = make_broker(
        [["A1", "A2", "A3"], ["B1", "B2", "B3"]],
        chunk_delay=0.01,
    )

    async def consume():
        return await collect(broker, messages)

    first, second = await asyncio.gather(consume(), consume())
    assert sorted([first, second], key=lambda c: c[0]) == [
        ["A1", "A2", "A3"],
        ["B1", "B2", "B3"],
    ]


async def test_health_passthrough():
    broker, _ = make_broker([])
    health = await broker.health()
    assert health.ok
