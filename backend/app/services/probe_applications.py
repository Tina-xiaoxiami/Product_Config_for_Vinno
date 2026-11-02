"""Resolve probe applications from the authoritative category associations."""
from sqlalchemy import func, select

from app.models.probe import Application, CategoryApplication, ProbeModel


async def model_application_counts(db, category_ids):
    rows = await db.execute(select(CategoryApplication.category_id,
        func.count(func.distinct(CategoryApplication.application_id)))
        .join(Application, Application.id == CategoryApplication.application_id)
        .where(CategoryApplication.category_id.in_(category_ids))
        .group_by(CategoryApplication.category_id))
    return dict(rows.all())


async def model_applications(db, model_id):
    rows = await db.execute(select(Application.id, Application.name, CategoryApplication.probe_type)
        .join(CategoryApplication, CategoryApplication.application_id == Application.id)
        .join(ProbeModel, ProbeModel.category_id == CategoryApplication.category_id)
        .where(ProbeModel.id == model_id).order_by(Application.sort_order, Application.id))
    items = {}
    for row in rows:
        item = items.setdefault(row.id, {'id': row.id, 'name': row.name, 'probe_types': []})
        item['probe_types'].append(row.probe_type)
    for item in items.values():
        item['probe_types'] = sorted(set(item['probe_types']))
    return list(items.values())


async def application_probe_usage(db, app_ids):
    rows = await db.execute(select(CategoryApplication.application_id,
        func.count(func.distinct(ProbeModel.id)))
        .join(ProbeModel, ProbeModel.category_id == CategoryApplication.category_id)
        .where(CategoryApplication.application_id.in_(app_ids))
        .group_by(CategoryApplication.application_id))
    return dict(rows.all())


async def application_probes(db, app_id):
    rows = await db.execute(select(ProbeModel.id, ProbeModel.model_number, CategoryApplication.probe_type)
        .join(CategoryApplication, CategoryApplication.category_id == ProbeModel.category_id)
        .where(CategoryApplication.application_id == app_id).order_by(ProbeModel.model_number, ProbeModel.id))
    items = {}
    for row in rows:
        item = items.setdefault(row.id, {'probe_id': row.id, 'model_number': row.model_number, 'probe_types': []})
        item['probe_types'].append(row.probe_type)
    for item in items.values():
        item['probe_types'] = sorted(set(item['probe_types']))
    return list(items.values())
