"""功能名称标准表 API：导入标准定义、查询核对结果和功能名称提示标记。"""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.whitepaper_name_audit import (
    audit_whitepaper_names,
    list_whitepaper_documents,
)
from app.services.feature_name_standards import (
    FeatureNameStandardError,
    audit_feature_names,
    feature_name_standard_flags,
    parse_standard_table,
    replace_feature_name_standards,
)

router = APIRouter()


@router.get("/flags")
async def feature_name_flags(db: AsyncSession = Depends(get_db)):
    """返回功能名称提示标记，供前端在任意显示功能名称的位置调用。"""

    return await feature_name_standard_flags(db)


@router.get("")
async def feature_name_standards(db: AsyncSession = Depends(get_db)):
    """返回标准定义与功能主数据的完整核对结果。"""

    audit = await audit_feature_names(db)
    return {
        "standard_count": audit["standard_count"],
        "summary": audit["summary"],
        "last_imported_at": audit["last_imported_at"],
        "source_file": audit["source_file"],
        "standards": audit["standards"],
        "uncovered_features": audit["uncovered_features"],
    }


@router.get("/whitepaper-documents")
async def whitepaper_documents(db: AsyncSession = Depends(get_db)):
    """可用于名称核对的白皮书清单。"""

    return {"items": await list_whitepaper_documents(db)}


@router.get("/whitepaper-names")
async def whitepaper_names(
    document_id: int | None = Query(default=None),
    include_matched: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """核对白皮书正文名称是否符合标准表，配置侧仅显示IPN链接。

    不指定 document_id 时只返回按白皮书汇总的概览；指定时返回该白皮书的逐条差异。
    """

    report = await audit_whitepaper_names(
        db, document_id=document_id, include_matched=include_matched
    )
    if document_id is None:
        report = {**report, "entries": []}
    return report


@router.post("/import")
async def import_feature_name_standards(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """导入功能名称标准表（.xlsx/.csv/.tsv），整表覆盖后返回新的核对结果。"""

    content = await file.read()
    try:
        standards = parse_standard_table(content)
    except FeatureNameStandardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    imported = await replace_feature_name_standards(
        db, standards, source_file=file.filename
    )
    audit = await audit_feature_names(db)
    return {
        "imported": imported["imported"],
        "source_file": imported["source_file"],
        "summary": audit["summary"],
    }


from pydantic import BaseModel, Field
from app.services.feature_name_reviews import review_detail, confirm_differences, revoke_confirmation, apply_standard_names

class NameReviewInput(BaseModel):
    checks: dict[str,str] = Field(min_length=1,max_length=2)
    note: str = Field(default='',max_length=1000)
    confirmed_by: str = Field(default='local_user',min_length=1,max_length=100)

@router.get('/reviews/{feature_id}')
async def get_name_reviews(feature_id: int, db: AsyncSession = Depends(get_db)):
    return await review_detail(db,feature_id)

@router.post('/reviews/{feature_id}')
async def confirm_name_reviews(feature_id: int, data: NameReviewInput, db: AsyncSession = Depends(get_db)):
    return await confirm_differences(db,feature_id,data.checks,data.note,data.confirmed_by)

@router.post('/reviews/{feature_id}/{review_id}/revoke')
async def revoke_name_review(feature_id: int, review_id: int, db: AsyncSession = Depends(get_db)):
    return await revoke_confirmation(db,feature_id,review_id)


class StandardNameInput(BaseModel):
    fingerprint: str = Field(min_length=64, max_length=64)
    note: str = Field(default='', max_length=1000)
    confirmed_by: str = Field(default='local_user', min_length=1, max_length=100)


@router.post('/reviews/{feature_id}/apply-standard')
async def apply_feature_standard(feature_id: int, data: StandardNameInput, db: AsyncSession = Depends(get_db)):
    return await apply_standard_names(db, feature_id, data.fingerprint, data.note, data.confirmed_by)


class DisplayNameInput(BaseModel):
    name: str = Field(default='', max_length=200)


@router.put('/reviews/{feature_id}/display-name')
async def update_display_name(feature_id: int, data: DisplayNameInput, db: AsyncSession = Depends(get_db)):
    from app.services.feature_name_reviews import set_display_name
    return await set_display_name(db, feature_id, data.name)
