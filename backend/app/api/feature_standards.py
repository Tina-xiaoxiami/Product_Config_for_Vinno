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
    """核对白皮书正文里的功能名称：分别与标准表和配置管理描述比对。

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
