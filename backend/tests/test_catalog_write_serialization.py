"""A nested catalog writer cannot roll back its caller's transaction."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from app.services.write_serialization import serialize_catalog_write


@pytest.mark.asyncio
async def test_catalog_lock_conflict_leaves_transaction_cleanup_to_the_caller():
    class Session:
        no_autoflush = nullcontext()
        rolled_back = False

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name='sqlite'))

        async def execute(self, statement):
            raise OperationalError(str(statement), {}, RuntimeError('database is locked'))

        async def rollback(self):
            self.rolled_back = True

    session = Session()
    with pytest.raises(HTTPException) as error:
        await serialize_catalog_write(session, 'product_models')
    assert error.value.status_code == 409
    assert not session.rolled_back
