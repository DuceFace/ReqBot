from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True, scope="session")
def block_live_services():
    """Guard: any test that forgets to mock QdrantClient fails fast instead of hitting live infra.

    Skips silently if qdrant_client is not installed so config/docs/normalize tests can
    still run in environments that only have test dependencies installed.
    """
    try:
        with patch("qdrant_client.QdrantClient", side_effect=RuntimeError("Live Qdrant called in tests")):
            yield
    except ModuleNotFoundError:
        yield
