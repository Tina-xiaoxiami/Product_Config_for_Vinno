"""Release-note applicability maintenance and read-only historical tracing."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.knowledge_release_history import ReleaseBindingCreate, ReleaseTraceRequest, ReleaseCoverageRequest
from app.services.knowledge_release_coverage import release_coverage
from app.services.knowledge_scope import KnowledgeScopeError
from app.services.knowledge_release_history import (
    ReleaseHistoryError, ReleaseHistoryConflict, ReleaseHistoryUnavailable,
    list_release_documents, list_release_bindings, create_release_bindings,
    deactivate_release_binding, trace_release_history,
)

router = APIRouter(prefix='/release-history', tags=['历史Release Note追溯'])


@router.post('/coverage')
async def coverage(data: ReleaseCoverageRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await release_coverage(db, data.scope.model_dump() if data.scope is not None else None)
    except (ReleaseHistoryError, KnowledgeScopeError) as error:
        raise _http_error(error) from error


def _http_error(error):
    status = 503 if isinstance(error, ReleaseHistoryUnavailable) else 409 if isinstance(error, ReleaseHistoryConflict) else 422
    return HTTPException(status_code=status, detail=str(error))


@router.get('/documents')
async def documents(q: str | None = None, skip: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    return await list_release_documents(db, query=q, skip=skip, limit=limit)


@router.get('/bindings')
async def bindings(product_model_id: int | None = Query(None, gt=0), include_inactive: bool = False, db: AsyncSession = Depends(get_db)):
    return await list_release_bindings(db, product_model_id=product_model_id, include_inactive=include_inactive)


@router.post('/bindings')
async def bind(data: ReleaseBindingCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await create_release_bindings(db, data.model_dump())
    except (ReleaseHistoryError, KnowledgeScopeError) as error:
        raise _http_error(error) from error


@router.delete('/bindings/{binding_id}')
async def deactivate(binding_id: int, expected_revision: int = Query(..., ge=1), db: AsyncSession = Depends(get_db)):
    try:
        return await deactivate_release_binding(db, binding_id, expected_revision)
    except ReleaseHistoryError as error:
        raise _http_error(error) from error


@router.post('/trace')
async def trace(data: ReleaseTraceRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await trace_release_history(db, data.query, data.scope.model_dump(), release_line=data.release_line)
    except (ReleaseHistoryError, KnowledgeScopeError) as error:
        raise _http_error(error) from error
