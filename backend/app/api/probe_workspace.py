"""Probe totals use shared subseries and the main configuration version store."""
import io
import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import ConfigVersion
from app.models.probe_workspace import ProbeWorkspace, ProbeWorkspaceRelease
from app.services import probe_workspace as service
from app.services.probe_workbook import export_workbook, import_workbook

router = APIRouter()


class ScopeInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    groups: list[str] = Field(default_factory=list, max_length=100)
    combinations: list[str] = Field(default_factory=list, max_length=100)


class DraftInput(BaseModel):
    revision: int = Field(ge=1)
    data: dict
    refresh_scope: bool = False


class RevisionInput(BaseModel):
    revision: int = Field(ge=1)


class PublishInput(BaseModel):
    version_number: str | None = Field(default=None, min_length=1, max_length=20)
    description: str = Field(default='', max_length=4000)
    signature: str | None = None


async def workspace(db, workspace_id):
    item = await db.get(ProbeWorkspace, workspace_id)
    if item is None:
        raise HTTPException(404, '共同总集不存在')
    return item


def view(item):
    published = json.loads(item.published_data) if item.published_data else None
    return {'id': item.id, 'name': item.name, 'revision': item.revision,
            'has_draft': item.draft_data is not None,
            'published_data': published,
            'data': json.loads(item.draft_data) if item.draft_data else published}


async def change(db, item, revision, **values):
    changed = await db.execute(update(ProbeWorkspace).where(
        ProbeWorkspace.id == item.id, ProbeWorkspace.revision == revision
    ).values(**values, revision=revision + 1).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise HTTPException(409, '草稿已被其他操作修改，请刷新后重新核对')
    await db.refresh(item)


@router.get('')
async def list_workspaces(db=Depends(get_db)):
    return [view(item) for item in (await db.scalars(select(ProbeWorkspace).order_by(ProbeWorkspace.id))).all()]


@router.get('/catalog')
async def get_catalog(db=Depends(get_db)):
    return await service.catalog(db)


@router.post('')
async def create_workspace(data: ScopeInput, db=Depends(get_db)):
    if not data.name.strip():
        raise HTTPException(422, '总集名称不能为空')
    scope = await service.shared_scope(db, data.groups, data.combinations)
    document = await service.initial_document(db, scope)
    await service.ensure_no_overlap(db, document)
    item = ProbeWorkspace(name=data.name.strip(), draft_data=service.encode(document))
    db.add(item)
    await db.flush()
    await service.reserve_members(db, item, document)
    await db.commit()
    await db.refresh(item)
    return view(item)


@router.get('/{workspace_id}')
async def get_workspace(workspace_id: int, db=Depends(get_db)):
    return view(await workspace(db, workspace_id))


@router.put('/{workspace_id}/draft')
async def save_draft(workspace_id: int, data: DraftInput, db=Depends(get_db)):
    item = await workspace(db, workspace_id)
    document = await service.validate_document(db, data.data, refresh=data.refresh_scope)
    await service.ensure_no_overlap(db, document, item.id)
    await change(db, item, data.revision, draft_data=service.encode(document))
    await service.reserve_members(db, item, document)
    await db.commit()
    return view(item)


@router.post('/{workspace_id}/discard')
async def discard(workspace_id: int, data: RevisionInput, db=Depends(get_db)):
    item = await workspace(db, workspace_id)
    # An unpublished workspace retains only its scope, without legacy suggestions.
    empty = {'scope': json.loads(item.draft_data)['scope'], 'rows': [], 'overrides': {}} if not item.published_data else None
    await change(db, item, data.revision, draft_data=None if empty is None else service.encode(empty))
    await service.reserve_members(db, item, empty or json.loads(item.published_data), published=True)
    await db.commit()
    return view(item)


@router.get('/{workspace_id}/results')
async def results(workspace_id: int, db=Depends(get_db)):
    item = await workspace(db, workspace_id)
    document = view(item)['data']
    if item.draft_data is None:
        latest = await db.scalar(select(ProbeWorkspaceRelease).where(
            ProbeWorkspaceRelease.workspace_id == item.id).order_by(ProbeWorkspaceRelease.id.desc()).limit(1))
        if latest:
            frozen = json.loads(latest.snapshot_data)
            return {'results': frozen['results'], 'diff': service.document_diff(document, document)}
    snapshots, _, cat = await service.context(db, document)
    return {'results': service.calculate_results(document, snapshots, cat),
            'diff': service.document_diff(view(item)['published_data'], document)}


async def publication_preview(db, item, data):
    if not item.draft_data:
        raise HTTPException(400, '没有待发布的草稿')
    document = await service.validate_document(db, json.loads(item.draft_data))
    if not document['rows'] and not item.published_data:
        raise HTTPException(422, '请先录入共同总集')
    await service.ensure_no_overlap(db, document, item.id)
    snapshots, numbers, cat = await service.context(db, document, publishing=True, version_number=data.version_number)
    latest = await db.scalar(select(ProbeWorkspaceRelease).where(
        ProbeWorkspaceRelease.workspace_id == item.id).order_by(ProbeWorkspaceRelease.id.desc()).limit(1))
    if latest:
        previous = json.loads(latest.snapshot_data)
        if previous['data'] == document and previous['source_snapshots'] == snapshots and previous['catalog'] == cat:
            raise HTTPException(400, '总集、机型差异与来源配置均无变化，无需创建版本')
    result = {'data': document, 'source_snapshots': snapshots, 'version_numbers': numbers,
              'results': service.calculate_results(document, snapshots, cat),
              'catalog': cat, 'revision': item.revision, 'description': data.description,
              'diff': service.document_diff(view(item)['published_data'], document)}
    result['signature'] = service.signature(result)
    return result


@router.post('/{workspace_id}/preview')
async def preview(workspace_id: int, data: PublishInput, db=Depends(get_db)):
    return await publication_preview(db, await workspace(db, workspace_id), data)


@router.post('/{workspace_id}/publish')
async def publish(workspace_id: int, data: PublishInput, db=Depends(get_db)):
    item = await workspace(db, workspace_id)
    # Acquire SQLite's write lock before re-reading source facts and signature.
    await db.execute(update(ProbeWorkspace).where(ProbeWorkspace.id == item.id).values(revision=ProbeWorkspace.revision))
    await db.refresh(item)
    checked = await publication_preview(db, item, data)
    if not data.signature or data.signature != checked['signature']:
        raise HTTPException(409, '草稿、配置或发布范围已变化，请重新核对发布预览')
    # Optimistic write lock before any version is created. All writes commit together.
    await change(db, item, checked['revision'], published_data=service.encode(checked['data']), draft_data=None)
    await service.reserve_members(db, item, checked['data'], published=True)
    version_ids = {}
    for sid, snapshot in checked['source_snapshots'].items():
        series_data = await service.attach_published_probes(db, snapshot, replacement=(item.id, checked['data']))
        version = ConfigVersion(series_id=int(sid), version_number=checked['version_numbers'][sid],
                                version_name=f'探头配置 · {item.name}', description=data.description,
                                snapshot_data=service.encode(series_data), row_count=len(snapshot['items']))
        db.add(version)
        try:
            await db.flush()
        except IntegrityError as error:
            await db.rollback()
            raise HTTPException(409, '版本号已被占用，请重新核对发布预览') from error
        version_ids[sid] = version.id
    checked['config_version_ids'] = version_ids
    number = data.version_number or ' / '.join(f'{sid}:{v}' for sid, v in checked['version_numbers'].items())
    release = ProbeWorkspaceRelease(workspace_id=item.id, version_number=number,
                                   description=data.description, snapshot_data=service.encode(checked))
    db.add(release)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, '发布版本已存在，请刷新重试') from error
    return {'id': release.id, 'version_number': number, 'config_version_ids': version_ids}


@router.get('/{workspace_id}/releases')
async def releases(workspace_id: int, db=Depends(get_db)):
    await workspace(db, workspace_id)
    return [{'id': r.id, 'workspace_id': r.workspace_id, 'version_number': r.version_number,
             'description': r.description, 'created_at': r.created_at}
            for r in (await db.scalars(select(ProbeWorkspaceRelease).where(
                ProbeWorkspaceRelease.workspace_id == workspace_id).order_by(ProbeWorkspaceRelease.id.desc()))).all()]


async def release_for(db, workspace_id, release_id):
    release = await db.get(ProbeWorkspaceRelease, release_id)
    if release is None or release.workspace_id != workspace_id:
        raise HTTPException(404, '发布版本不存在')
    return release


@router.get('/{workspace_id}/releases/{release_id}')
async def release_detail(workspace_id: int, release_id: int, db=Depends(get_db)):
    release = await release_for(db, workspace_id, release_id)
    return {'id': release.id, 'version_number': release.version_number, 'snapshot': json.loads(release.snapshot_data)}


@router.post('/{workspace_id}/releases/{release_id}/restore')
async def restore(workspace_id: int, release_id: int, data: RevisionInput, db=Depends(get_db)):
    item = await workspace(db, workspace_id)
    release = await release_for(db, workspace_id, release_id)
    document = json.loads(release.snapshot_data)['data']
    await service.ensure_no_overlap(db, document, item.id)
    # Historical membership is preserved in history, but a new publication must
    # explicitly re-resolve today's membership before it can be saved.
    await change(db, item, data.revision, draft_data=service.encode(document))
    await service.reserve_members(db, item, document)
    await db.commit()
    return view(item)


@router.get('/{workspace_id}/compare')
async def compare(workspace_id: int, before: int, after: int, db=Depends(get_db)):
    left = json.loads((await release_for(db, workspace_id, before)).snapshot_data)
    right = json.loads((await release_for(db, workspace_id, after)).snapshot_data)
    old = {(r['model_id'], r['key']): r for r in left['results']}
    new = {(r['model_id'], r['key']): r for r in right['results']}
    return {'diff': service.document_diff(left['data'], right['data']), 'changes': [
        {'model_id': key[0], 'key': key[1], 'before': old.get(key), 'after': new.get(key)}
        for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)]}


@router.get('/{workspace_id}/export')
async def export(workspace_id: int, release_id: int | None = None, db=Depends(get_db)):
    item = await workspace(db, workspace_id)
    if release_id is not None:
        payload = json.loads((await release_for(db, workspace_id, release_id)).snapshot_data)
    else:
        document = view(item)['data']
        if item.draft_data is None:
            latest = await db.scalar(select(ProbeWorkspaceRelease).where(
                ProbeWorkspaceRelease.workspace_id == item.id).order_by(ProbeWorkspaceRelease.id.desc()).limit(1))
            payload = json.loads(latest.snapshot_data)
        else:
            snapshots, _, cat = await service.context(db, document)
            payload = {'data': document, 'results': service.calculate_results(document, snapshots, cat), 'catalog': cat, 'source_snapshots': snapshots}
    content = export_workbook(payload, item.id, item.revision)
    return StreamingResponse(io.BytesIO(content), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                             headers={'Content-Disposition': 'attachment; filename="probe-configuration.xlsx"'})


@router.post('/{workspace_id}/import-preview')
async def import_preview(workspace_id: int, file: UploadFile = File(...), db=Depends(get_db)):
    item = await workspace(db, workspace_id)
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, '文件不能超过 10MB')
    document = import_workbook(content, file.filename, item.id, item.revision)
    document = await service.validate_document(db, document)
    return {'data': document, 'revision': item.revision,
            'diff': service.document_diff(view(item)['data'], document)}
