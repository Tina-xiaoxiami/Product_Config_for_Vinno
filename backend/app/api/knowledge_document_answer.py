"""Explicit opt-in document drafts; ordinary QA and parameters stay deterministic."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.integrations.guideline_evidence import capabilities
from app.schemas.knowledge import KnowledgeQueryScope
from app.services.knowledge_document_answer import document_answer
from app.services.knowledge_scope import KnowledgeScopeError
from app.services.knowledge_release_history import ReleaseHistoryError

router = APIRouter(prefix='/document-answer')


class DocumentAnswerRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=2, max_length=500)
    scope: KnowledgeQueryScope


@router.get('/capabilities')
async def availability():
    return capabilities()


@router.post('')
async def answer(data: DocumentAnswerRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await document_answer(db, data.question.strip(), data.scope.model_dump())
    except (KnowledgeScopeError, ReleaseHistoryError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
