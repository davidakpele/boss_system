# app/routers/documents.py
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pathlib import Path
from app.database import get_db
from app.models import Document, KnowledgeChunk, User, AuditLog, DocStatus, AccessLevel, ComplianceRecord, RiskItem
from app.auth import require_user
from app.services.document_service import extract_text_from_file, chunk_text, get_file_type
from app.services.ai_service import ai_service
from app.config import settings
import shutil, uuid, logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["knowledge"])
templates = Jinja2Templates(directory="app/templates")


# ─── background: embed + risk-detect a document ───────────────────────────────
async def _post_approve_background(doc_id: int, content: str, department: str):
    """Run after document approval: generate embeddings and detect risks."""
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        # 1. Embed all chunks for this document
        chunks = (await db.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id)
        )).scalars().all()
        for chunk in chunks:
            if not chunk.embedding:
                emb = await ai_service.embed_and_store_chunk(chunk.content)
                if emb:
                    chunk.embedding = emb
        await db.commit()

        # 2. AI Risk Detection
        risks = await ai_service.detect_risks_from_text(content, source_label=f"document:{doc_id}")
        for r in risks:
            # Don't duplicate
            existing = (await db.execute(
                select(RiskItem).where(
                    RiskItem.title == r["title"],
                    RiskItem.source_type == "document",
                    RiskItem.source_id == doc_id,
                )
            )).scalar_one_or_none()
            if not existing:
                db.add(RiskItem(
                    title=r["title"],
                    description=r.get("description", ""),
                    category=r.get("category", "Operational"),
                    likelihood=r["likelihood"],
                    impact=r["impact"],
                    risk_score=r["risk_score"],
                    mitigation_plan=r.get("mitigation_plan", ""),
                    auto_detected=True,
                    source_type="document",
                    source_id=doc_id,
                ))
        if risks:
            await db.commit()
            logger.info(f"AI detected {len(risks)} risks from document {doc_id}")


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
    return templates.TemplateResponse(request=request, name="knowledge/index.html", context={
        "user": current_user, "chunks": chunks, "departments": departments,
        "page": "knowledge_base", "filters": {"department": department, "search": search},
    })


@router.get("/documents", response_class=HTMLResponse)
async def documents_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    status_filter: str = None, dept: str = None,
):
    if current_user.role in ("super_admin", "admin"):
        stmt = select(Document, User.full_name).join(User, Document.author_id == User.id)
    elif current_user.role == "manager":
        stmt = (select(Document, User.full_name).join(User, Document.author_id == User.id)
                .where(Document.access_level.in_([AccessLevel.all_staff, AccessLevel.restricted])))
    else:
        stmt = (select(Document, User.full_name).join(User, Document.author_id == User.id)
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
    return templates.TemplateResponse(request=request, name="documents/index.html", context={
        "user": current_user, "documents": docs_with_authors, "departments": departments,
        "page": "documents", "filters": {"status": status_filter, "dept": dept},
    })


@router.get("/documents/new", response_class=HTMLResponse)
async def new_document_form(request: Request, current_user: User = Depends(require_user)):
    return templates.TemplateResponse(request=request, name="documents/new.html",
                                      context={"user": current_user, "page": "documents"})


@router.post("/documents/new")
async def create_document(
    background_tasks: BackgroundTasks,
    request: Request,
    title: str = Form(...), content: str = Form(""),
    description: str = Form(""), department: str = Form(...),
    access_level: str = Form("all_staff"), file: UploadFile = File(None),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    file_path = file_type = extracted_content = None

    if file and file.filename:
        ext = get_file_type(file.filename)
        if ext == "unknown":
            return JSONResponse({"error": "Unsupported file type"}, status_code=400)
        upload_dir = Path(settings.UPLOAD_DIR) / "documents"
        upload_dir.mkdir(parents=True, exist_ok=True)
        save_path = upload_dir / f"{uuid.uuid4()}_{file.filename}"
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
        title=title, content=full_content, description=description, department=department,
        access_level=AccessLevel(access_level),
        status=DocStatus.approved if is_admin else DocStatus.pending,
        author_id=current_user.id, approved_by=current_user.id if is_admin else None,
        file_path=file_path, file_type=file_type,
        original_filename=file.filename if file else None,
    )
    db.add(doc)
    await db.flush()

    if doc.status == DocStatus.approved and full_content:
        chunks = chunk_text(full_content, chunk_size=400, overlap=50)
        for ct in chunks[:20]:
            summary = await ai_service.summarize_text(ct)
            db.add(KnowledgeChunk(
                document_id=doc.id, source_type="document",
                content=ct, summary=summary, department=department,
            ))
        # compliance
        try:
            for item in (await ai_service.extract_compliance_from_document(full_content))[:10]:
                db.add(ComplianceRecord(
                    document_id=doc.id, regulation_type=item.get("regulation_type", "General"),
                    requirement=item.get("requirement", ""), risk_level=item.get("risk_level", "medium"),
                    status="identified",
                ))
            doc.is_compliance = True
        except Exception as e:
            logger.error(f"Compliance extraction: {e}")

        # Schedule background embedding + risk detection
        background_tasks.add_task(_post_approve_background, doc.id, full_content, department)

    db.add(AuditLog(user_id=current_user.id, action="create_document", resource_type="document",
                    resource_id=doc.id, details={"title": title, "department": department}))
    await db.commit()
    return RedirectResponse("/documents", status_code=302)


@router.post("/documents/{doc_id}/approve")
async def approve_document(
    doc_id: int, background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    if current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403)
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404)
    doc.status = DocStatus.approved
    doc.approved_by = current_user.id
    if doc.content:
        for chunk in chunk_text(doc.content, chunk_size=400)[:20]:
            db.add(KnowledgeChunk(document_id=doc.id, source_type="document",
                                  content=chunk, department=doc.department))
    db.add(AuditLog(user_id=current_user.id, action="approve_document", resource_type="document",
                    resource_id=doc_id, details={"title": doc.title}))
    await db.commit()
    if doc.content:
        background_tasks.add_task(_post_approve_background, doc.id, doc.content, doc.department or "")
    return JSONResponse({"status": "approved"})


@router.post("/documents/{doc_id}/reject")
async def reject_document(
    doc_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    if current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403)
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if doc:
        doc.status = DocStatus.rejected
        await db.commit()
    return JSONResponse({"status": "rejected"})