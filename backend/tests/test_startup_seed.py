"""Seeding an empty database on startup.

Why this exists: the deployed backend was serving a schema with nothing in it — 0 workers,
0 reports, 0 hotspots — so every screen rendered blank and the app looked broken even though
every endpoint answered 200. A free hosting tier has an ephemeral filesystem, so without a
persistent disk each deploy starts from nothing.

The rule this file pins is the dangerous half: seeding runs ONLY when the database is empty.
On anything holding real reports it must be a no-op, or a redeploy would bury a site's actual
safety data under demo rows.
"""

import asyncio
import pytest

from safety import llm, store


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "startup.db")
    monkeypatch.setattr(store, "PHOTO_DIR", tmp_path / "photos")
    store.init()
    return tmp_path


def _run_startup():
    import main
    asyncio.get_event_loop().run_until_complete(main.lifespan(None).__aenter__())


def test_an_empty_database_is_seeded_so_the_app_is_never_blank(db):
    assert store.count() == 0
    _run_startup()
    assert store.count() > 0
    assert store.count_users("WORKER") > 0
    assert store.count_users("SAFETY_ADMIN") == 1


def test_a_database_with_reports_is_left_alone(db):
    """The half that matters: a redeploy must never bury real data under demo rows."""
    report_id = store.save_report(
        {"report_text": "A real report somebody filed.", "source": "user"},
        {"risk_level": "HIGH", "risk_score": 70, "hazards": ["Oil spill"]})
    before = store.count()

    _run_startup()

    assert store.count() == before
    survived = store.get_report(report_id)
    assert survived is not None
    assert survived["report"]["report_text"] == "A real report somebody filed."


def test_startup_still_creates_the_schema(db, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "brand-new.db")
    _run_startup()
    with store.connect() as conn:
        tables = {row["name"] for row in
                  conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for required in ("safety_user", "safety_report", "worker_route_event", "safety_notification"):
        assert required in tables


def test_a_seeding_failure_does_not_stop_the_api_serving(db, monkeypatch):
    """An empty demo is better than no service at all."""
    from safety import people

    def _explode(*_args, **_kwargs):
        raise RuntimeError("seed source unavailable")

    monkeypatch.setattr(people, "seed_demo_data", _explode)
    _run_startup()          # must not raise
    assert store.count() == 0
