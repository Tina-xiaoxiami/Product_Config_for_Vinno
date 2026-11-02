"""Measurement library endpoints; imports create immutable source snapshots."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.database import get_db
from app.services.measurements import MAX_UPLOAD_BYTES, MeasurementImportError, import_measurements, measurement_library

router = APIRouter()


@router.get("")
async def get_measurements(batch_id: int | None = Query(default=None, ge=1), db: AsyncSession = Depends(get_db)):
    try:
        return await measurement_library(db, batch_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="测量库版本不存在") from exc


@router.post("/import")
async def import_workbook(file: UploadFile = File(...), version: str = Form(...), db: AsyncSession = Depends(get_db)):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        return await import_measurements(db, content, file.filename or "measurements.xlsx", version)
    except MeasurementImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
