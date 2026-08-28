"""Plans API tests (plan todo 11, QA qa/11-plans-api.log).

Runs against the REAL compose Postgres (same skip-when-unreachable policy as
test_auth_db.py / test_query_api.py). Test identities live under QA11TEST*
student numbers only (cascade-delete teardown); the catalog course used for
the join-embed case lives under year_sem=9998 and is wiped after. Sessions
are seeded directly against FakeRedis - no password ever exists in this file.
"""

import uuid
from dataclasses import dataclass

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.auth.sessions import create_site_session
from app.config import Settings
from app.db import build_engine, build_session_factory
from app.main import create_app
from app.models.courses import Course
from app.models.students import Student
from tests.fake_redis import FakeRedis

ME = "QA11TEST01"
OTHER = "QA11TEST02"
TEST_YEAR_SEM = "9998"

EMBED_COURSE = {  # one catalog row for the GET-items join-embed case
    "year_sem": TEST_YEAR_SEM,
    "code": "QA110001",
    "dept": "資訊工程學系",
    "grade": "3",
    "class_": "甲",
    "name_zh": "演算法",
    "credit": 3,
    "compulsory": False,
    "teacher": "測試教師",
    "room": "測101",
    "class_time": ["12", "", "34", "", "", "", ""],
}


def _engine_factory():
    engine = build_engine(Settings())
    return engine, build_session_factory(engine)


def _run(step):
    """Run one DB step on a fresh engine inside its own event loop."""

    async def wrapped():
        engine, factory = _engine_factory()
        try:
            return await step(factory)
        finally:
            await engine.dispose()

    return anyio.run(wrapped)


def _db_available() -> bool:
    async def probe(factory) -> bool:
        async with factory() as session:
            await session.execute(select(1))  # laziness-safe: must actually dial
        return True

    try:
        return _run(probe)
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="compose Postgres unreachable")


async def _wipe(factory) -> None:
    async with factory() as session, session.begin():
        await session.execute(delete(Course).where(Course.year_sem == TEST_YEAR_SEM))
        await session.execute(
            delete(Student).where(Student.student_no.in_((ME, OTHER)))
        )


async def _fresh_seed(factory) -> uuid.UUID:
    """Every test starts from: two students (no plans) + one catalog course."""
    await _wipe(factory)
    async with factory() as session, session.begin():
        session.add_all([Student(student_no=ME), Student(student_no=OTHER)])
        course = Course(**EMBED_COURSE)
        session.add(course)
        await session.flush()
        return course.id


@dataclass
class Harness:
    client: TestClient
    course_id: uuid.UUID

    @property
    def redis(self) -> FakeRedis:
        return self.client.app.state.redis

    def auth(self, student_no: str = ME) -> dict[str, str]:
        """A live site-session cookie jar for student_no (no password here)."""
        session_id = anyio.run(create_site_session, self.redis, student_no)
        return {"session_id": session_id}

    def create_plan(self, name: str, student_no: str = ME) -> dict:
        response = self.client.post(
            "/api/plans", json={"name": name}, cookies=self.auth(student_no)
        )
        assert response.status_code == 201, response.text
        return response.json()


@pytest.fixture
def harness():
    app = create_app(Settings())
    with TestClient(app) as test_client:
        test_client.app.state.redis = FakeRedis()
        course_id = _run(_fresh_seed)
        yield Harness(client=test_client, course_id=course_id)
        _run(_wipe)


# ---------- session gate ----------


def test_all_routes_require_a_site_session(harness):
    pid = str(uuid.uuid4())
    assert harness.client.get("/api/plans").status_code == 401
    assert harness.client.post("/api/plans", json={"name": "x"}).status_code == 401
    assert harness.client.patch(f"/api/plans/{pid}", json={"name": "y"}).status_code == 401
    assert harness.client.delete(f"/api/plans/{pid}").status_code == 401
    assert harness.client.get(f"/api/plans/{pid}/items").status_code == 401
    assert (
        harness.client.put(f"/api/plans/{pid}/items", json={"items": []}).status_code
        == 401
    )
    assert harness.client.post(f"/api/plans/{pid}/clone").status_code == 401


# ---------- CRUD + primary invariant ----------


def test_first_plan_is_auto_primary_second_is_not(harness):
    first = harness.create_plan("志願A")
    second = harness.create_plan("志願B")
    assert first["is_primary"] is True and first["item_count"] == 0
    assert second["is_primary"] is False
    plans = harness.client.get("/api/plans", cookies=harness.auth()).json()
    assert [p["name"] for p in plans] == ["志願A", "志願B"]
    assert sum(1 for p in plans if p["is_primary"]) == 1


def test_clone_copies_items_and_stays_non_primary(harness):
    base = harness.create_plan("BASE")
    second = harness.create_plan("OTHER")
    put = harness.client.put(
        f"/api/plans/{base['id']}/items",
        json={"items": [{"course_id": str(harness.course_id), "priority": 1}]},
        cookies=harness.auth(),
    )
    assert put.status_code == 200, put.text

    cloned = harness.client.post(
        f"/api/plans/{base['id']}/clone", cookies=harness.auth()
    )
    assert cloned.status_code == 201, cloned.text
    copy = cloned.json()
    assert copy["name"] == "BASE 副本"
    assert copy["is_primary"] is False
    assert copy["item_count"] == 1
    items = harness.client.get(
        f"/api/plans/{copy['id']}/items", cookies=harness.auth()
    ).json()
    assert [(i["course_id"], i["priority"]) for i in items] == [(str(harness.course_id), 1)]

    again = harness.client.post(
        f"/api/plans/{second['id']}/clone", cookies=harness.auth()
    ).json()
    assert again["is_primary"] is False and again["item_count"] == 0


def test_clone_of_foreign_plan_is_a_flat_404(harness):
    foreign = harness.create_plan("MINE")
    other_cookies = harness.auth(student_no=OTHER)
    response = harness.client.post(f"/api/plans/{foreign['id']}/clone", cookies=other_cookies)
    assert response.status_code == 404
    assert response.json()["detail"] == "plan_not_found"


def test_rename_and_set_primary_are_individual_patches(harness):
    a = harness.create_plan("A")
    b = harness.create_plan("B")
    seen = harness.client.patch(
        f"/api/plans/{b['id']}", json={"name": "B改名"}, cookies=harness.auth()
    )
    assert seen.status_code == 200 and seen.json()["name"] == "B改名"
    flipped = harness.client.patch(
        f"/api/plans/{b['id']}", json={"is_primary": True}, cookies=harness.auth()
    )
    assert flipped.status_code == 200 and flipped.json()["is_primary"] is True
    plans = harness.client.get("/api/plans", cookies=harness.auth()).json()
    by_id = {p["id"]: p for p in plans}
    assert by_id[a["id"]]["is_primary"] is False  # unset in the same transaction
    assert by_id[b["id"]]["is_primary"] is True


def test_patch_validation_is_explicit(harness):
    a = harness.create_plan("A")
    unset = harness.client.patch(
        f"/api/plans/{a['id']}", json={"is_primary": False}, cookies=harness.auth()
    )
    assert unset.status_code == 400
    assert unset.json()["detail"] == "cannot_unset_primary"
    empty = harness.client.patch(
        f"/api/plans/{a['id']}", json={}, cookies=harness.auth()
    )
    assert empty.status_code == 400 and empty.json()["detail"] == "empty_patch"
    blank = harness.client.patch(
        f"/api/plans/{a['id']}", json={"name": "  "}, cookies=harness.auth()
    )
    assert blank.status_code == 400 and blank.json()["detail"] == "name_required"


def test_delete_primary_promotes_oldest_remaining(harness):
    a = harness.create_plan("A")
    b = harness.create_plan("B")
    c = harness.create_plan("C")
    harness.client.patch(
        f"/api/plans/{b['id']}", json={"is_primary": True}, cookies=harness.auth()
    )
    deleted = harness.client.delete(f"/api/plans/{b['id']}", cookies=harness.auth())
    assert deleted.status_code == 200
    assert deleted.json()["promoted_plan_id"] == a["id"]
    plans = harness.client.get("/api/plans", cookies=harness.auth()).json()
    assert [(p["name"], p["is_primary"]) for p in plans] == [("A", True), ("C", False)]

    gone = harness.client.delete(f"/api/plans/{c['id']}", cookies=harness.auth())
    assert gone.json()["promoted_plan_id"] is None  # non-primary delete promotes nobody


# ---------- ownership ----------


def test_foreign_plans_are_flat_404_everywhere(harness):
    mine = harness.create_plan("我的")
    foreign = harness.client.get("/api/plans", cookies=harness.auth(OTHER)).json()
    assert foreign == []  # invisible, not merely refused
    for response in (
        harness.client.patch(
            f"/api/plans/{mine['id']}", json={"name": "偷改"}, cookies=harness.auth(OTHER)
        ),
        harness.client.delete(f"/api/plans/{mine['id']}", cookies=harness.auth(OTHER)),
        harness.client.get(
            f"/api/plans/{mine['id']}/items", cookies=harness.auth(OTHER)
        ),
        harness.client.put(
            f"/api/plans/{mine['id']}/items",
            json={"items": []},
            cookies=harness.auth(OTHER),
        ),
    ):
        assert response.status_code == 404
        assert response.json()["detail"] == "plan_not_found"
    missing = harness.client.get(
        f"/api/plans/{uuid.uuid4()}/items", cookies=harness.auth()
    )
    assert missing.status_code == 404


# ---------- items: replace-all + validation + join embed ----------


def test_put_replaces_the_whole_list_and_get_orders_nulls_last(harness):
    pid = harness.create_plan("A")["id"]
    put = harness.client.put(
        f"/api/plans/{pid}/items",
        json={
            "items": [
                {"course_id": str(uuid.uuid4()), "priority": 2},
                {"course_id": str(uuid.uuid4())},
                {"course_id": str(uuid.uuid4()), "priority": 1},
            ]
        },
        cookies=harness.auth(),
    )
    assert put.status_code == 200, put.text
    got = harness.client.get(f"/api/plans/{pid}/items", cookies=harness.auth()).json()
    assert [i["priority"] for i in got] == [1, 2, None]
    assert [i["course"] for i in got] == [None, None, None]  # unknown ids accepted

    kept = put.json()[0]["course_id"]
    again = harness.client.put(
        f"/api/plans/{pid}/items",
        json={"items": [{"course_id": kept, "priority": 5}]},
        cookies=harness.auth(),
    )
    assert [i["course_id"] for i in again.json()] == [kept]
    assert harness.client.get(f"/api/plans/{pid}/items", cookies=harness.auth()).json()[
        0
    ]["priority"] == 5
    listed = harness.client.get("/api/plans", cookies=harness.auth()).json()
    assert listed[0]["item_count"] == 1


def test_put_items_embeds_the_catalog_course(harness):
    pid = harness.create_plan("A")["id"]
    course_id = str(harness.course_id)
    harness.client.put(
        f"/api/plans/{pid}/items",
        json={"items": [{"course_id": course_id, "priority": 1}]},
        cookies=harness.auth(),
    )
    (item,) = harness.client.get(
        f"/api/plans/{pid}/items", cookies=harness.auth()
    ).json()
    assert item["course"]["id"] == course_id
    assert item["course"]["name_zh"] == "演算法"
    assert item["course"]["class_time"][0] == "12"
    # A non-UUID id is likewise accepted and embeds nothing.
    harness.client.put(
        f"/api/plans/{pid}/items",
        json={"items": [{"course_id": "not-a-uuid"}]},
        cookies=harness.auth(),
    )
    assert harness.client.get(f"/api/plans/{pid}/items", cookies=harness.auth()).json()[
        0
    ]["course"] is None


def test_put_items_rejects_duplicates_and_out_of_range(harness):
    pid = harness.create_plan("A")["id"]
    one, two = str(uuid.uuid4()), str(uuid.uuid4())
    dup_course = harness.client.put(
        f"/api/plans/{pid}/items",
        json={"items": [{"course_id": one}, {"course_id": one}]},
        cookies=harness.auth(),
    )
    assert dup_course.status_code == 400
    assert dup_course.json()["detail"] == "duplicate_course_id"
    dup_priority = harness.client.put(
        f"/api/plans/{pid}/items",
        json={
            "items": [
                {"course_id": one, "priority": 3},
                {"course_id": two, "priority": 3},
            ]
        },
        cookies=harness.auth(),
    )
    assert dup_priority.status_code == 400
    assert dup_priority.json()["detail"] == "duplicate_priority"
    for bad in (0, 21, 100):
        out_of_range = harness.client.put(
            f"/api/plans/{pid}/items",
            json={"items": [{"course_id": one, "priority": bad}]},
            cookies=harness.auth(),
        )
        assert out_of_range.status_code == 422
    over_max = harness.client.put(
        f"/api/plans/{pid}/items",
        json={"items": [{"course_id": str(uuid.uuid4())} for _ in range(101)]},
        cookies=harness.auth(),
    )
    assert over_max.status_code == 422
    # Null priorities repeat freely; an empty list clears the plan.
    many_null = harness.client.put(
        f"/api/plans/{pid}/items",
        json={"items": [{"course_id": one}, {"course_id": two}]},
        cookies=harness.auth(),
    )
    assert many_null.status_code == 200
    cleared = harness.client.put(
        f"/api/plans/{pid}/items", json={"items": []}, cookies=harness.auth()
    )
    assert cleared.status_code == 200 and cleared.json() == []
    assert (
        harness.client.get(f"/api/plans/{pid}/items", cookies=harness.auth()).json()
        == []
    )
