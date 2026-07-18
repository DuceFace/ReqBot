from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True, scope="session")
def block_live_services():
    """Guard: any test that forgets to mock QdrantClient fails fast instead of hitting live infra."""
    with patch("qdrant_client.QdrantClient", side_effect=RuntimeError("Live Qdrant called in tests")):
        yield
