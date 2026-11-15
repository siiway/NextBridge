from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from services.db import MessageDB, _Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    with patch.object(MessageDB, "_run_migrations"):
        db = MessageDB(engine=engine)
    _Base.metadata.create_all(engine)
    yield db
    engine.dispose()
