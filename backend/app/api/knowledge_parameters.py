"""Maintain controlled parameter records and preview explicit configuration snapshots."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.knowledge_parameters import ParameterPreviewRequest, ParameterSpecCreate, ParameterSpecUpdate, ParameterTopicCreate
from app.services import knowledge_parameters as service

router = APIRouter()


async def _run(action):
    try:
        return await action
    except service.ParameterUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except service.ParameterNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except service.ParameterConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except service.ParameterError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get('/parameter-topics')
async def topics(db: AsyncSession = Depends(get_db)):
    return await _run(service.list_topics(db))


@router.post('/parameter-topics')
async def create_topic(data: ParameterTopicCreate, db: AsyncSession = Depends(get_db)):
    return await _run(service.create_topic(db, data.model_dump()))


@router.get('/parameter-topics/{topic_id}/specs')
async def specs(topic_id: int, db: AsyncSession = Depends(get_db)):
    return await _run(service.list_specs(db, topic_id))


@router.post('/parameter-topics/{topic_id}/specs')
async def create_spec(topic_id: int, data: ParameterSpecCreate, db: AsyncSession = Depends(get_db)):
    return await _run(service.save_spec(db, topic_id, data.model_dump()))


@router.put('/parameter-topics/{topic_id}/specs/{spec_id}')
async def update_spec(topic_id: int, spec_id: int, data: ParameterSpecUpdate, db: AsyncSession = Depends(get_db)):
    return await _run(service.save_spec(db, topic_id, data.model_dump(), spec_id))


@router.get('/parameter-snapshots/{config_version_id}')
async def snapshot_options(config_version_id: int, db: AsyncSession = Depends(get_db)):
    return await _run(service.snapshot_options(db, config_version_id))


@router.post('/parameter-topics/{topic_id}/preview')
async def preview(topic_id: int, data: ParameterPreviewRequest, db: AsyncSession = Depends(get_db)):
    return await _run(service.preview(db, topic_id, data.config_version_id, data.model_ids))
