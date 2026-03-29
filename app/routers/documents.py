from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pathlib import Path
from app.database import get_db
from app.models import Document, KnowledgeChunk, User, AuditLog, DocStatus, AccessLevel, ComplianceRecord
from app.auth import require_user
from app.services.document_service import extract_text_from_file, chunk_text, get_file_type
from app.services.ai_service import ai_service
from app.config import settings
import shutil
import uuid
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["knowledge"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/knowledge-base", response_class=HTMLResponse)
async def knowledge_base(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    department: str = None,
    search: str = None,
):
    stmt = select(KnowledgeChunk).order_by(KnowledgeChunk.created_at.desc())
    if department:
        stmt = stmt.where(KnowledgeChunk.department == department)
    if search:
        stmt = stmt.where(KnowledgeChunk.content.contains(search))
    stmt = stmt.limit(50)

    chunks = (await db.execute(stmt)).scalars().all()
    departments = (await db.execute(
        select(KnowledgeChunk.department).distinct().where(KnowledgeChunk.department != None)
    )).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="knowledge/index.html",
        context={
            "user": current_user,
            "chunks": chunks,
            "departments": departments,
            "page": "knowledge_base",
            "filters": {"department": department, "search": search},
        }
    )


@router.get("/documents", response_class=HTMLResponse)
async def documents_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    status_filter: str = None,
    dept: str = None,
):
    if current_user.role in ("super_admin", "admin"):
        stmt = select(Document, User.full_name).join(User, Document.author_id == User.id)
    elif current_user.role == "manager":
        stmt = (select(Document, User.full_name)
                .join(User, Document.author_id == User.id)
                .where(Document.access_level.in_([AccessLevel.all_staff, AccessLevel.restricted])))
    else:
        stmt = (select(Document, User.full_name)
                .join(User, Document.author_id == User.id)
                .where(Document.access_level == AccessLevel.all_staff))

    if status_filter:
        stmt = stmt.where(Document.status == status_filter)
    if dept:
        stmt = stmt.where(Document.department == dept)
    stmt = stmt.order_by(Document.created_at.desc())

    docs_with_authors = (await db.execute(stmt)).all()
    departments = (await db.execute(
        select(Document.department).distinct().where(Document.department != None)
    )).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="documents/index.html",
        context={
            "user": current_user,
            "documents": docs_with_authors,
            "departments": departments,
            "page": "documents",
            "filters": {"status": status_filter, "dept": dept},
        }
    )


@router.get("/documents/new", response_class=HTMLResponse)
async def new_document_form(
    request: Request,
    current_user: User = Depends(require_user),
):
    return templates.TemplateResponse(
        request=request,
        name="documents/new.html",
        context={"user": current_user, "page": "documents"}
    )


@router.post("/documents/new")
async def create_document(
    request: Request,
    title: str = Form(...),
    content: str = Form(""),
    description: str = Form(""),
    department: str = Form(...),
    access_level: str = Form("all_staff"),
    file: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    file_path = None
    file_type = None
    extracted_content = ""

    if file and file.filename:
        ext = get_file_type(file.filename)
        if ext == "unknown":
            return JSONResponse({"error": "Unsupported file type"}, status_code=400)

        upload_dir = Path(settings.UPLOAD_DIR) / "documents"
        upload_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4()}_{file.filename}"
        save_path = upload_dir / filename

        with open(save_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        file_path = str(save_path)
        file_type = ext
        extracted_content = await extract_text_from_file(file_path, file_type)

    full_content = content
    if extracted_content:
        full_content = (content + "\n\n" + extracted_content).strip() if content else extracted_content

    is_admin = current_user.role in ("super_admin", "admin")
    doc = Document(
        title=title,
        content=full_content,
        description=description,
        department=department,
        access_level=AccessLevel(access_level),
        status=DocStatus.approved if is_admin else DocStatus.pending,
        author_id=current_user.id,
        approved_by=current_user.id if is_admin else None,
        file_path=file_path,
        file_type=file_type,
        original_filename=file.filename if file else None,
    )
    db.add(doc)
    await db.flush()

    if doc.status == DocStatus.approved and full_content:
        chunks = chunk_text(full_content, chunk_size=400, overlap=50)
        for chunk_text_content in chunks[:20]:
            summary = await ai_service.summarize_text(chunk_text_content)
            db.add(KnowledgeChunk(
                document_id=doc.id, source_type="document",
                content=chunk_text_content, summary=summary, department=department,
            ))

        try:
            compliance_items = await ai_service.extract_compliance_from_document(full_content)
            for item in compliance_items[:10]:
                db.add(ComplianceRecord(
                    document_id=doc.id,
                    regulation_type=item.get("regulation_type", "General"),
                    requirement=item.get("requirement", ""),
                    risk_level=item.get("risk_level", "medium"),
                    status="identified",
                ))
                doc.is_compliance = True
        except Exception as e:
            logger.error(f"Compliance extraction error: {e}")

    db.add(AuditLog(
        user_id=current_user.id, action="create_document",
        resource_type="document", resource_id=doc.id,
        details={"title": title, "department": department},
    ))
    await db.commit()
    return RedirectResponse("/documents", status_code=302)


@router.post("/documents/{doc_id}/approve")
async def approve_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")

    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc.status = DocStatus.approved
    doc.approved_by = current_user.id

    if doc.content:
        for chunk in chunk_text(doc.content, chunk_size=400)[:20]:
            db.add(KnowledgeChunk(document_id=doc.id, source_type="document", content=chunk, department=doc.department))

    db.add(AuditLog(
        user_id=current_user.id, action="approve_document",
        resource_type="document", resource_id=doc_id,
        details={"title": doc.title},
    ))
    await db.commit()
    return JSONResponse({"status": "approved"})


@router.post("/documents/{doc_id}/reject")
async def reject_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")

    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if doc:
        doc.status = DocStatus.rejected
        await db.commit()
    return JSONResponse({"status": "rejected"})