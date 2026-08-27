"""confirm_token store tests (plan todo 14; QA qa/14-replay.log part).

Single-use semantics are THE replay defense: consume is the atomic GETDEL -
first take gets the record, every later take (a replayed confirm) gets None,
which todo 15's submit maps to 409. Locked here against FakeRedis.
"""

import pytest

from app.write.confirm import ConfirmRecord, confirm_key, consume_confirm, store_confirm
from tests.fake_redis import FakeRedis

RECORD = ConfirmRecord(
    student_no="M153000024",
    canonical_ops="-:M3046243:|+:GEAE2526:01",
    variant="ssform",
    form_url="https://selcrs.nsysu.edu.tw/menu4/addcourse/ssform.asp?X1=09",
)
TOKEN = "qa14-token-under-test"


@pytest.mark.anyio
async def test_store_then_consume_once_returns_the_record():
    redis = FakeRedis()
    await store_confirm(redis, TOKEN, RECORD, ttl=300)
    assert redis.remaining_ttl(confirm_key(TOKEN)) == 300

    taken = await consume_confirm(redis, TOKEN)
    assert taken == RECORD


@pytest.mark.anyio
async def test_second_consume_is_none_the_replay_path():
    redis = FakeRedis()
    await store_confirm(redis, TOKEN, RECORD, ttl=300)

    first = await consume_confirm(redis, TOKEN)
    second = await consume_confirm(redis, TOKEN)
    third = await consume_confirm(redis, TOKEN)

    assert first == RECORD
    assert second is None  # replay -> todo 15 maps to 409
    assert third is None
    assert redis.peek(confirm_key(TOKEN)) is None


@pytest.mark.anyio
async def test_consuming_a_never_minted_token_is_none():
    assert await consume_confirm(FakeRedis(), "no-such-token") is None


@pytest.mark.anyio
async def test_corrupt_payload_degrades_to_none():
    redis = FakeRedis()
    await redis.set(confirm_key(TOKEN), "{not json", ex=300)
    assert await consume_confirm(redis, TOKEN) is None
    assert redis.peek(confirm_key(TOKEN)) is None  # spent either way


@pytest.mark.anyio
async def test_repreview_of_the_same_token_refreshes_the_record():
    redis = FakeRedis()
    await store_confirm(redis, TOKEN, RECORD, ttl=300)
    refreshed = RECORD.model_copy(update={"variant": "stage5"})
    await store_confirm(redis, TOKEN, refreshed, ttl=300)
    assert await consume_confirm(redis, TOKEN) == refreshed
