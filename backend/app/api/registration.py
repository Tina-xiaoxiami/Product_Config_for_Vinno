"""国内注册红线与产品策略查询 API。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.registration import (
    ConfiguredRegistrationModelList,
    RegistrationModelList,
    RegistrationProbeStrategyList,
)
from app.services.registration_query import (
    list_configured_registration_models,
    list_product_registration_probes,
    list_registration_models,
)


router = APIRouter()


@router.get("/configured-models", response_model=ConfiguredRegistrationModelList)
async def configured_registration_models(
    country_code: str = Query("CN", pattern="^[A-Z]{2}$"),
    db: AsyncSession = Depends(get_db),
):
    items = await list_configured_registration_models(
        db,
        country_code=country_code,
    )
    return ConfiguredRegistrationModelList(items=items, total=len(items))


@router.get("/models", response_model=RegistrationModelList)
async def registration_models(
    country_code: str = Query("CN", pattern="^[A-Z]{2}$"),
    q: str | None = Query(None, max_length=200),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_registration_models(
        db,
        country_code=country_code,
        query=q,
        skip=skip,
        limit=limit,
    )
    return RegistrationModelList(items=items, total=total, skip=skip, limit=limit)


@router.get("/probes", response_model=RegistrationProbeStrategyList)
async def product_registration_probes(
    product_model_id: int = Query(..., ge=1),
    q: str | None = Query(None, max_length=200),
    registration_status: str | None = Query(
        None,
        pattern="^(registered|unregistered)$",
    ),
    effective_status: str | None = Query(
        None,
        pattern="^(X|O|Δ|#|未定义)$",
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await list_product_registration_probes(
        db,
        product_model_id=product_model_id,
        query=q,
        registration_status=registration_status,
        effective_status=effective_status,
        skip=skip,
        limit=limit,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="产品型号尚未关联注册基础型号")
    return RegistrationProbeStrategyList(**result)

