"""功能主数据 Excel 导入 API：模板下载、上传预览和确认更新。"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.feature_master_import import (
    FeatureImportError,
    apply_feature_import,
    build_feature_template_workbook,
    parse_import_workbook,
    preview_feature_import,
)

router = APIRouter()

EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _rows_from_upload(file: UploadFile):
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="只支持 .xlsx 格式，请使用「导出模板」生成的表格")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传的文件是空的")
    try:
        return parse_import_workbook(content)
    except FeatureImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/template")
async def download_template(db: AsyncSession = Depends(get_db)):
    """导出当前功能主数据，作为离线编辑和导入的模板。"""

    content = await build_feature_template_workbook(db)
    filename = quote("功能主数据导入模板.xlsx")
    return Response(
        content=content,
        media_type=EXCEL_MEDIA_TYPE,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.post("/preview")
async def preview_import(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """校验整份文件并返回新增/更新/无变化/错误的逐行结果，不写入数据库。"""

    rows = await _rows_from_upload(file)
    report = await preview_feature_import(db, rows)
    return {"file_name": file.filename, **report}


@router.post("")
async def run_import(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """在单个事务里导入整份文件；任一行校验失败时不写入任何数据。"""

    rows = await _rows_from_upload(file)
    report = await apply_feature_import(db, rows)
    if not report["applied"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "导入未执行：有校验未通过的数据行",
                "summary": report["summary"],
                "rows": [
                    {
                        "row_number": row["row_number"],
                        "errors": row["errors"],
                        "primary_cn_name": row["primary_cn_name"],
                        "group_name": row["group_name"],
                    }
                    for row in report["rows"]
                    if row["errors"]
                ],
            },
        )
    return {"file_name": file.filename, **report}
