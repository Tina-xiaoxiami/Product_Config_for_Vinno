"""Version preflight shared by main configuration and probe publication."""
from sqlalchemy import select
from fastapi import HTTPException
from app.models import ConfigVersion, ConfigDraft, DraftBatch
from app.utils import generate_next_version


async def resolve_version_number(db, series_id, requested):
    latest = await db.scalar(select(ConfigVersion).where(
        ConfigVersion.series_id == series_id).order_by(ConfigVersion.id.desc()).limit(1))
    number = requested or generate_next_version(latest.version_number if latest else None)
    if await db.scalar(select(ConfigVersion.id).where(
            ConfigVersion.series_id == series_id, ConfigVersion.version_number == number)):
        raise HTTPException(400, f'版本号 {number} 在该系列中已存在')
    return number


async def ensure_no_pending_drafts(db, series_id):
    pending = await db.scalar(select(ConfigDraft.id).join(DraftBatch).where(
        ConfigDraft.series_id == series_id, DraftBatch.status == 'draft').limit(1))
    if pending is not None:
        raise HTTPException(400, '当前系列存在未提交草稿，请先提交或废弃草稿')
