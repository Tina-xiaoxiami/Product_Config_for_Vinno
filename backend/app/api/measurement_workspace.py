"""Versioned measurement management; imports and research remain separate stores."""
import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.measurement_workspace import MeasurementWorkspace
from app.schemas.measurement_workspace import (
    EditInput, InitializeInput, PreviewInput, PublishInput, RevisionInput, UndoInput,
)
from app.services import measurement_workspace as service

router = APIRouter()


@router.get('')
async def for_batch(batch_id: int = Query(ge=1), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    item = await db.scalar(select(MeasurementWorkspace).where(MeasurementWorkspace.batch_id == batch_id))
    return await service.view(db, item) if item else {'initialized': False}


@router.post('/initialize')
async def initialize(data: InitializeInput, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await service.initialize(db, data)


@router.get('/{workspace_id}')
async def get_workspace(workspace_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await service.view(db, await service.workspace(db, workspace_id))


@router.post('/{workspace_id}/edit')
async def edit(workspace_id: int, data: EditInput, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await service.edit(db, await service.workspace(db, workspace_id), data)


@router.post('/{workspace_id}/undo')
async def undo(workspace_id: int, data: UndoInput, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await service.undo(db, await service.workspace(db, workspace_id), data)


@router.post('/{workspace_id}/discard')
async def discard(workspace_id: int, data: RevisionInput, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    item = await service.workspace(db, workspace_id)
    service.check_revision(item, data.revision)
    return await service.save(db, item, data.revision, json.loads(item.published_data))


@router.post('/{workspace_id}/preview')
async def preview(workspace_id: int, data: PreviewInput, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await service.preview(db, await service.workspace(db, workspace_id), data)


@router.post('/{workspace_id}/publish')
async def publish(workspace_id: int, data: PublishInput, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await service.publish(db, await service.workspace(db, workspace_id), data)


@router.get('/{workspace_id}/versions/{version_id}')
async def version(workspace_id: int, version_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    item = await service.workspace(db, workspace_id)
    return service.version_data(await service.version_for(db, item, version_id), include_data=True)


@router.get('/{workspace_id}/compare')
async def compare(workspace_id: int, from_version_id: int = Query(ge=1), to_version_id: int = Query(ge=1), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    item = await service.workspace(db, workspace_id)
    before = await service.version_for(db, item, from_version_id)
    after = await service.version_for(db, item, to_version_id)
    changes = service.document_diff(json.loads(before.snapshot_data), json.loads(after.snapshot_data))
    return {'from_version_id': before.id, 'to_version_id': after.id, 'changes': changes, 'change_count': len(changes)}


@router.post('/{workspace_id}/restore/{version_id}')
async def restore(workspace_id: int, version_id: int, data: RevisionInput, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    item = await service.workspace(db, workspace_id)
    service.check_revision(item, data.revision)
    previous = await service.version_for(db, item, version_id)
    return await service.save(db, item, data.revision, json.loads(previous.snapshot_data))


@router.post('/{workspace_id}/sync-evidence')
async def sync_evidence(workspace_id: int, data: RevisionInput, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await service.sync_evidence(db, await service.workspace(db, workspace_id), data.revision)
