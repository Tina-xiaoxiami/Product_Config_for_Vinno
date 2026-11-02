"""Linux browser-test fixture using production API routers and an isolated DB."""
import json
import os
from pathlib import Path
import sys
from contextlib import asynccontextmanager

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
if os.environ.get('PROBE_E2E') != '1':
    raise RuntimeError('E2E fixture requires PROBE_E2E=1 and a disposable database')
database = os.environ.get('DATABASE_URL', '')
from sqlalchemy.engine import make_url
url = make_url(database)
temporary_root = Path('/tmp').resolve()


def disposable_path(value):
    path = Path(value).resolve()
    if not path.is_relative_to(temporary_root) or not path.name.startswith('probe-e2e'):
        raise RuntimeError('E2E fixture refuses non-disposable paths')
    return path


if url.drivername != 'sqlite+aiosqlite' or not url.database:
    raise RuntimeError('E2E fixture refuses non-disposable databases')
disposable_path(url.database)
subseries_file = disposable_path(os.environ['WHITEPAPER_SUBSERIES_FILE'])

from fastapi import FastAPI
from app.database import engine, async_session, Base
from app.api import probe_workspace, models, drafts, series, feature_standards
from app.api import measurements
from app.api import config, versions, enums, probe_categories, probe_models, applications, features, template_features, probe_config, registration, knowledge
from app.services.overseas_registration_history import migrate_overseas_registration_history_schema
from app.models import ProductSeries, ProductModel, ConfigItem, ConfigValue
from app.models.probe import ProbeCategory, ProbeModel, ProbeModelVariant, FeatureGroup, Feature, ProductProbeConfig, TemplateFeature


@asynccontextmanager
async def lifespan(app):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    migrate_overseas_registration_history_schema(url.database)
    async with async_session() as db:
        db.add_all([
            ProductSeries(id=1, name='国内'), ProductSeries(id=2, name='海外'),
            ProductModel(id=10, series_id=1, name='VINNO 10'),
            ProductModel(id=11, series_id=1, name='VINNO 6'),
            ProductModel(id=20, series_id=2, name='ULTIMUS 9'),
            ProbeCategory(id=1, name='凸阵'), ProbeModel(id=1, category_id=1, model_number='P1'),
            ProbeModelVariant(id=1, probe_model_id=1, internal_model='P1a', ipn='P-1'),
            FeatureGroup(id=1, name='成像'), Feature(id=1, group_id=1, name='造影', config_item_id=201),
            TemplateFeature(category_id=1, feature_id=1, default_support='supported'),
            ConfigItem(id=200, category='Probes', row_index=1, rd_name='P1', ipn='P-1'),
            ConfigItem(id=201, category='Optional Features', row_index=2, rd_name='造影', ipn='F-1'),
            ProductProbeConfig(product_model_id=10, probe_model_id=1, feature_id=1,
                               defined_status='supported', current_status='supported', priority='标2'),
        ])
        for model in (10, 11, 20):
            db.add(ConfigValue(item_id=200, model_id=model, final_config='N/A' if model == 11 else 'X',
                               current_config='N/A' if model == 11 else 'X', selection_config='O'))
            db.add(ConfigValue(item_id=201, model_id=model, final_config='X', current_config='X', selection_config='O'))
        await db.commit()
    subseries_file.write_text(json.dumps({
        'sub_series': [
            {'name': 'V10与V6', 'series': '国内', 'models': ['VINNO 10', 'VINNO 6']},
            {'name': 'ULTIMUS', 'series': '海外', 'models': ['ULTIMUS 9']},
        ], 'sub_series_combinations': [{'name': 'V系列与ULTIMUS', 'sub_series': ['V10与V6', 'ULTIMUS']}],
    }))
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(probe_workspace.router, prefix='/api/probes/workspaces')
app.include_router(models.router, prefix='/api/models')
app.include_router(drafts.router, prefix='/api/drafts')
app.include_router(series.router, prefix='/api/series')
app.include_router(feature_standards.router, prefix='/api/features/standards')
app.include_router(measurements.router, prefix='/api/measurements')
app.include_router(config.router, prefix='/api/config')
app.include_router(versions.router, prefix='/api/versions')
app.include_router(enums.router, prefix='/api/enums')
app.include_router(probe_categories.router, prefix='/api/probe-categories')
app.include_router(probe_models.router, prefix='/api/probe-models')
app.include_router(applications.router, prefix='/api/applications')
app.include_router(features.router, prefix='/api/features')
app.include_router(template_features.router, prefix='/api/template-features')
app.include_router(probe_config.router, prefix='/api/probes/config')
app.include_router(registration.router, prefix='/api/registrations')
app.include_router(knowledge.router, prefix='/api/knowledge')
