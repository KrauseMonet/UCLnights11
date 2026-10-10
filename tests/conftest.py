"""A throwaway Postgres for the tests that need one, started from the `pgserver` dev
dependency (Postgres binaries on PyPI, so no system install is needed) and migrated
with the real migrations. Tests that do not ask for `database` never start it."""

import tempfile

import pytest


@pytest.fixture(scope="session")
def database():
    pgserver = pytest.importorskip("pgserver")
    from tools.migrate import migrate

    with tempfile.TemporaryDirectory() as tmp:
        server = pgserver.get_server(tmp, cleanup_mode="stop")
        url = server.get_uri()
        migrate(url)
        yield url
        server.cleanup()
