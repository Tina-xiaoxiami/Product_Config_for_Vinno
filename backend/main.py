"""
FastAPI 主入口
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.api import series, models, config, versions, drafts, import_export, enums, version_cleanup
from app.api import probe_categories, probe_models as probe_models_api, applications, features, template_features, probe_config, probe_import
from app.api import knowledge
from app.api import registration

app = FastAPI(
    title="产品配置管理系统",
    description="产品配置数据的版本管理和对比分析",
    version="1.0.0"
)

# CORS配置 - 从环境变量读取允许的域名
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3006,http://127.0.0.1:3006").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(series.router, prefix="/api/series", tags=["产品系列"])
app.include_router(models.router, prefix="/api/models", tags=["产品型号"])
app.include_router(config.router, prefix="/api/config", tags=["配置数据"])
app.include_router(versions.router, prefix="/api/versions", tags=["版本管理"])
app.include_router(drafts.router, prefix="/api/drafts", tags=["草稿管理"])
app.include_router(import_export.router, prefix="/api/import-export", tags=["导入导出"])
app.include_router(enums.router, prefix="/api/enums", tags=["枚举值"])
app.include_router(version_cleanup.router, prefix="/api/version-cleanup", tags=["版本清理"])
app.include_router(probe_categories.router, prefix="/api/probe-categories", tags=["探头类别"])
app.include_router(probe_models_api.router, prefix="/api/probe-models", tags=["探头型号"])
app.include_router(applications.router, prefix="/api/applications", tags=["应用定义"])
app.include_router(features.router, prefix="/api/features", tags=["功能管理"])
app.include_router(template_features.router, prefix="/api/template-features", tags=["模板配置"])
app.include_router(probe_config.router, prefix="/api/probes/config", tags=["探头配置"])
app.include_router(probe_import.router, prefix="/api/probes", tags=["探头导入"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["产品知识库"])
app.include_router(
    registration.router,
    prefix="/api/knowledge/registration",
    tags=["注册与产品策略"],
)


@app.on_event("startup")
async def startup():
    """启动时初始化数据库"""
    await init_db()


@app.get("/")
async def root():
    return {"message": "产品配置管理系统 API"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8086)
