# app/routers/bcc.py  — Business Command Centre
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc
from datetime import datetime, date, timedelta
from typing import Optional
from pathlib import Path
import shutil, uuid, json, logging

from app.database import get_db
from app.models import (
    User, AccountingRecord, AccountingCategory, TransactionType,
    InventoryItem, InventoryMovement, MovementType,
    JobPosting, JobApplication, ApplicationStatus, JobStatus, HRNotification,
    InternalNotification, KnowledgeChunk
)
from app.auth import require_user
from app.services.ai_service import ai_service
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["bcc"])
templates = Jinja2Templates(directory="app/templates")


# ═══════════════════════════════════════════════════════════════════════════════
#  BCC DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/bcc", response_class=HTMLResponse)
async def bcc_dashboard(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    # Quick stats
    total_income  = (await db.execute(
        select(func.sum(AccountingRecord.amount))
        .where(AccountingRecord.type == TransactionType.income)
    )).scalar() or 0

    total_expense = (await db.execute(
        select(func.sum(AccountingRecord.amount))
        .where(AccountingRecord.type == TransactionType.expense)
    )).scalar() or 0

    low_stock = (await db.execute(
        select(InventoryItem)
        .where(InventoryItem.is_active == True,
               InventoryItem.quantity <= InventoryItem.reorder_level)
    )).scalars().all()

    open_jobs = (await db.execute(
        select(func.count(JobPosting.id)).where(JobPosting.status == JobStatus.open)
    )).scalar() or 0

    pending_apps = (await db.execute(
        select(func.count(JobApplication.id))
        .where(JobApplication.status.in_([ApplicationStatus.received, ApplicationStatus.screening]))
    )).scalar() or 0

    recent_txns = (await db.execute(
        select(AccountingRecord).order_by(AccountingRecord.created_at.desc()).limit(8)
    )).scalars().all()

    return templates.TemplateResponse(request=request, name="bcc/dashboard.html", context={
        "user": current_user, "page": "bcc",
        "total_income": total_income, "total_expense": total_expense,
        "net": total_income - total_expense,
        "low_stock": low_stock, "open_jobs": open_jobs,
        "pending_apps": pending_apps, "recent_txns": recent_txns,
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  ACCOUNTING
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/bcc/accounting", response_class=HTMLResponse)
async def accounting_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    type_filter: str = None, month: str = None,
):
    stmt = select(AccountingRecord).order_by(AccountingRecord.date.desc())
    if type_filter in ("income", "expense"):
        stmt = stmt.where(AccountingRecord.type == type_filter)
    if month:
        try:
            y, m = map(int, month.split("-"))
            stmt = stmt.where(
                func.extract("year",  AccountingRecord.date) == y,
                func.extract("month", AccountingRecord.date) == m,
            )
        except Exception:
            pass
    stmt = stmt.limit(200)
    records = (await db.execute(stmt)).scalars().all()

    total_income  = sum(r.amount for r in records if r.type == TransactionType.income)
    total_expense = sum(r.amount for r in records if r.type == TransactionType.expense)

    categories = (await db.execute(select(AccountingCategory).order_by(AccountingCategory.name))).scalars().all()

    return templates.TemplateResponse(request=request, name="bcc/accounting.html", context={
        "user": current_user, "page": "bcc", "records": records,
        "total_income": total_income, "total_expense": total_expense,
        "net": total_income - total_expense,
        "categories": categories,
        "filters": {"type": type_filter, "month": month},
    })


@router.post("/bcc/accounting/record")
async def create_record(
    type: str = Form(...), amount: float = Form(...),
    category: str = Form(""), description: str = Form(...),
    reference: str = Form(""), date_str: str = Form(None),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    rec_date = datetime.utcnow()
    if date_str:
        try:
            rec_date = datetime.fromisoformat(date_str)
        except ValueError:
            pass
    db.add(AccountingRecord(
        type=TransactionType(type), amount=amount, category=category or "General",
        description=description, reference=reference,
        recorded_by=current_user.id, date=rec_date,
    ))
    await db.commit()
    return JSONResponse({"status": "recorded"})


@router.post("/bcc/accounting/ai-parse")
async def ai_parse_transaction(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Parse a natural language string into a structured transaction."""
    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "No text"}, status_code=400)

    msgs = [
        {"role": "system", "content": (
            "You are a financial data extraction AI. Parse the user's message into a transaction record.\n"
            "Return ONLY valid JSON with fields:\n"
            "  type: 'income' or 'expense'\n"
            "  amount: number (extract from text)\n"
            "  category: string (e.g. Transportation, Salaries, Sales, Utilities, Supplies, Marketing, Other)\n"
            "  description: string (clean 1-line description)\n"
            "  reference: string or empty\n"
            "If amount cannot be determined, return {\"error\": \"cannot parse amount\"}.\n"
            "Return ONLY JSON."
        )},
        {"role": "user", "content": text},
    ]
    result = await ai_service.chat_complete(msgs)
    try:
        clean = result.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)
        if "error" in data:
            return JSONResponse({"error": data["error"]}, status_code=422)
        return JSONResponse(data)
    except Exception:
        return JSONResponse({"error": "AI could not parse the transaction"}, status_code=422)


@router.delete("/bcc/accounting/{rec_id}")
async def delete_record(rec_id: int, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(require_user)):
    rec = (await db.execute(select(AccountingRecord).where(AccountingRecord.id == rec_id))).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404)
    await db.delete(rec)
    await db.commit()
    return JSONResponse({"status": "deleted"})


@router.get("/bcc/accounting/export/csv")
async def export_csv(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user)
):
    records = (await db.execute(
        select(AccountingRecord).order_by(AccountingRecord.date.desc())
    )).scalars().all()
    lines = ["Date,Type,Amount,Category,Description,Reference"]
    for r in records:
        d = r.date.strftime("%Y-%m-%d") if r.date else ""
        lines.append(f'{d},{r.type.value},{r.amount},"{r.category}","{r.description}","{r.reference or ""}"')
    content = "\n".join(lines)
    return StreamingResponse(iter([content]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=accounting_export.csv"})


# ═══════════════════════════════════════════════════════════════════════════════
#  INVENTORY
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/bcc/inventory", response_class=HTMLResponse)
async def inventory_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    search: str = None, category: str = None,
):
    stmt = select(InventoryItem).where(InventoryItem.is_active == True)
    if search:
        stmt = stmt.where(or_(
            InventoryItem.name.ilike(f"%{search}%"),
            InventoryItem.sku.ilike(f"%{search}%"),
            InventoryItem.category.ilike(f"%{search}%"),
        ))
    if category:
        stmt = stmt.where(InventoryItem.category == category)
    stmt = stmt.order_by(InventoryItem.name)
    items = (await db.execute(stmt)).scalars().all()

    categories = (await db.execute(
        select(InventoryItem.category).distinct().where(InventoryItem.category != None)
    )).scalars().all()

    low_stock = [i for i in items if i.quantity <= i.reorder_level]
    total_value = sum(i.quantity * i.cost_price for i in items)

    return templates.TemplateResponse(request=request, name="bcc/inventory.html", context={
        "user": current_user, "page": "bcc", "items": items,
        "categories": categories, "low_stock_count": len(low_stock),
        "total_value": total_value, "filters": {"search": search, "category": category},
    })


@router.post("/bcc/inventory/create")
async def create_item(
    name: str = Form(...), sku: str = Form(""), category: str = Form(""),
    description: str = Form(""), unit: str = Form("unit"),
    quantity: float = Form(0), reorder_level: float = Form(0),
    cost_price: float = Form(0), selling_price: float = Form(0),
    supplier: str = Form(""), location: str = Form(""),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    if not sku:
        sku = f"SKU-{uuid.uuid4().hex[:8].upper()}"
    existing = (await db.execute(
        select(InventoryItem).where(InventoryItem.sku == sku)
    )).scalar_one_or_none()
    if existing:
        return JSONResponse({"error": "SKU already exists"}, status_code=400)
    item = InventoryItem(
        name=name, sku=sku, category=category, description=description,
        unit=unit, quantity=quantity, reorder_level=reorder_level,
        cost_price=cost_price, selling_price=selling_price,
        supplier=supplier, location=location, created_by=current_user.id,
    )
    db.add(item)
    await db.flush()
    if quantity > 0:
        db.add(InventoryMovement(
            item_id=item.id, type=MovementType.stock_in, quantity=quantity,
            unit_cost=cost_price, notes="Initial stock", recorded_by=current_user.id,
        ))
    await db.commit()
    return JSONResponse({"status": "created", "id": item.id})


@router.post("/bcc/inventory/{item_id}/movement")
async def record_movement(
    item_id: int, movement_type: str = Form(...),
    quantity: float = Form(...), unit_cost: float = Form(None),
    reference: str = Form(""), notes: str = Form(""),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    item = (await db.execute(select(InventoryItem).where(InventoryItem.id == item_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404)
    if movement_type == "stock_in":
        item.quantity += quantity
    elif movement_type in ("stock_out", "return_in"):
        item.quantity = max(0, item.quantity + (quantity if movement_type == "return_in" else -quantity))
    elif movement_type == "adjustment":
        item.quantity = quantity
    db.add(InventoryMovement(
        item_id=item_id, type=MovementType(movement_type),
        quantity=quantity, unit_cost=unit_cost,
        reference=reference, notes=notes, recorded_by=current_user.id,
    ))
    await db.commit()
    return JSONResponse({"status": "recorded", "new_quantity": item.quantity})


@router.post("/bcc/inventory/{item_id}/update")
async def update_item(
    item_id: int, name: str = Form(...), category: str = Form(""),
    reorder_level: float = Form(0), cost_price: float = Form(0),
    selling_price: float = Form(0), supplier: str = Form(""), location: str = Form(""),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    item = (await db.execute(select(InventoryItem).where(InventoryItem.id == item_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404)
    item.name = name; item.category = category; item.reorder_level = reorder_level
    item.cost_price = cost_price; item.selling_price = selling_price
    item.supplier = supplier; item.location = location
    await db.commit()
    return JSONResponse({"status": "updated"})


@router.delete("/bcc/inventory/{item_id}")
async def delete_item(item_id: int, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(require_user)):
    item = (await db.execute(select(InventoryItem).where(InventoryItem.id == item_id))).scalar_one_or_none()
    if item:
        item.is_active = False
        await db.commit()
    return JSONResponse({"status": "archived"})


@router.get("/bcc/inventory/{item_id}/movements")
async def get_movements(item_id: int, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(require_user)):
    mvs = (await db.execute(
        select(InventoryMovement).where(InventoryMovement.item_id == item_id)
        .order_by(InventoryMovement.created_at.desc()).limit(50)
    )).scalars().all()
    return JSONResponse([{
        "id": m.id, "type": m.type.value, "quantity": m.quantity,
        "unit_cost": m.unit_cost, "notes": m.notes,
        "created_at": m.created_at.isoformat() if m.created_at else "",
    } for m in mvs])


# ═══════════════════════════════════════════════════════════════════════════════
#  HR — JOB POSTINGS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/bcc/hr", response_class=HTMLResponse)
async def hr_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    jobs = (await db.execute(
        select(JobPosting).order_by(JobPosting.created_at.desc())
    )).scalars().all()

    # App counts per job
    job_stats = {}
    for job in jobs:
        counts = {}
        for status in ApplicationStatus:
            c = (await db.execute(
                select(func.count(JobApplication.id))
                .where(JobApplication.job_id == job.id, JobApplication.status == status)
            )).scalar()
            counts[status.value] = c
        job_stats[job.id] = counts

    return templates.TemplateResponse(request=request, name="bcc/hr_jobs.html", context={
        "user": current_user, "page": "bcc", "jobs": jobs, "job_stats": job_stats,
    })


@router.post("/bcc/hr/jobs/create")
async def create_job(
    title: str = Form(...), department: str = Form(""),
    description: str = Form(...), requirements: str = Form(""),
    salary_range: str = Form(""), location: str = Form("On-site"),
    employment_type: str = Form("Full-time"), deadline: str = Form(None),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    dl = None
    if deadline:
        try: dl = datetime.fromisoformat(deadline)
        except: pass
    db.add(JobPosting(
        title=title, department=department, description=description,
        requirements=requirements, salary_range=salary_range,
        location=location, employment_type=employment_type,
        deadline=dl, created_by=current_user.id,
    ))
    await db.commit()
    return JSONResponse({"status": "created"})


@router.post("/bcc/hr/jobs/{job_id}/toggle")
async def toggle_job(job_id: int, db: AsyncSession = Depends(get_db),
                     current_user: User = Depends(require_user)):
    job = (await db.execute(select(JobPosting).where(JobPosting.id == job_id))).scalar_one_or_none()
    if not job: raise HTTPException(404)
    job.status = JobStatus.closed if job.status == JobStatus.open else JobStatus.open
    await db.commit()
    return JSONResponse({"status": job.status.value})


# ═══════════════════════════════════════════════════════════════════════════════
#  HR — APPLICATIONS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/bcc/hr/jobs/{job_id}/applications", response_class=HTMLResponse)
async def applications_page(
    job_id: int, request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user), status_filter: str = None,
):
    job = (await db.execute(select(JobPosting).where(JobPosting.id == job_id))).scalar_one_or_none()
    if not job: raise HTTPException(404)
    stmt = select(JobApplication).where(JobApplication.job_id == job_id)
    if status_filter:
        stmt = stmt.where(JobApplication.status == status_filter)
    stmt = stmt.order_by(JobApplication.ai_score.desc().nullslast(), JobApplication.created_at.desc())
    apps = (await db.execute(stmt)).scalars().all()
    return templates.TemplateResponse(request=request, name="bcc/hr_applications.html", context={
        "user": current_user, "page": "bcc", "job": job, "applications": apps,
        "status_filter": status_filter, "statuses": [s.value for s in ApplicationStatus],
    })


@router.post("/bcc/hr/jobs/{job_id}/apply")
async def submit_application(
    job_id: int, request: Request,
    applicant_name: str = Form(...), applicant_email: str = Form(""),
    applicant_phone: str = Form(""), cover_letter: str = Form(""),
    cv_file: UploadFile = File(None),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    job = (await db.execute(select(JobPosting).where(JobPosting.id == job_id))).scalar_one_or_none()
    if not job: raise HTTPException(404)

    cv_path = None; cv_text = ""
    if cv_file and cv_file.filename:
        upload_dir = Path(settings.UPLOAD_DIR) / "cvs"
        upload_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{uuid.uuid4()}_{cv_file.filename}"
        save_path = upload_dir / fname
        with open(save_path, "wb") as f:
            shutil.copyfileobj(cv_file.file, f)
        cv_path = str(save_path)
        # Extract text
        from app.services.document_service import extract_text_from_file, get_file_type
        ftype = get_file_type(cv_file.filename)
        if ftype != "unknown":
            cv_text = await extract_text_from_file(cv_path, ftype)

    app = JobApplication(
        job_id=job_id, applicant_name=applicant_name,
        applicant_email=applicant_email, applicant_phone=applicant_phone,
        cover_letter=cover_letter, cv_path=cv_path, cv_text=cv_text,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return JSONResponse({"status": "submitted", "id": app.id})


@router.post("/bcc/hr/applications/{app_id}/screen")
async def ai_screen_application(
    app_id: int, background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    """AI screens a CV against job requirements."""
    app = (await db.execute(select(JobApplication).where(JobApplication.id == app_id))).scalar_one_or_none()
    if not app: raise HTTPException(404)
    job = (await db.execute(select(JobPosting).where(JobPosting.id == app.job_id))).scalar_one_or_none()

    cv_content = app.cv_text or app.cover_letter or "No CV text available"
    msgs = [
        {"role": "system", "content": (
            "You are an expert HR AI. Screen this candidate against the job requirements.\n"
            "Return ONLY valid JSON with:\n"
            "  score: 0-100 match percentage\n"
            "  summary: 2-sentence candidate summary\n"
            "  strengths: [list of 3 key strengths]\n"
            "  gaps: [list of 1-3 gaps or concerns]\n"
            "  recommendation: one of 'shortlist' | 'consider' | 'reject'\n"
            "  reason: 2-sentence justification\n"
        )},
        {"role": "user", "content": (
            f"JOB: {job.title}\n"
            f"REQUIREMENTS:\n{job.requirements or job.description}\n\n"
            f"CANDIDATE CV:\n{cv_content[:3000]}\n\n"
            f"COVER LETTER:\n{app.cover_letter or 'None'}"
        )},
    ]
    result = await ai_service.chat_complete(msgs)
    try:
        clean = result.strip().replace("```json","").replace("```","").strip()
        data = json.loads(clean)
        app.ai_score = float(data.get("score", 50))
        app.ai_summary = data.get("summary", "")
        app.ai_recommendation = json.dumps(data)
        app.status = ApplicationStatus.screening
        await db.commit()
        return JSONResponse({"status": "screened", "data": data})
    except Exception as e:
        return JSONResponse({"error": f"AI parse error: {e}", "raw": result}, status_code=422)


@router.post("/bcc/hr/applications/{app_id}/bulk-screen")
async def bulk_screen(
    job_id: int = Form(...), background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    apps = (await db.execute(
        select(JobApplication).where(
            JobApplication.job_id == job_id,
            JobApplication.ai_score == None,
        )
    )).scalars().all()
    return JSONResponse({"queued": len(apps), "message": f"Screening {len(apps)} applications in background"})


@router.post("/bcc/hr/applications/{app_id}/update-status")
async def update_app_status(
    app_id: int, status: str = Form(...), interview_date: str = Form(None),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    app = (await db.execute(select(JobApplication).where(JobApplication.id == app_id))).scalar_one_or_none()
    if not app: raise HTTPException(404)
    app.status = ApplicationStatus(status)
    if interview_date:
        try: app.interview_date = datetime.fromisoformat(interview_date)
        except: pass
    if notes:
        app.interview_notes = notes
    await db.commit()
    return JSONResponse({"status": "updated"})


@router.post("/bcc/hr/applications/{app_id}/generate-message")
async def generate_hr_message(
    app_id: int, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    """AI generates a screening/interview/offer/rejection message for this applicant."""
    body = await request.json()
    msg_type = body.get("type", "screening")   # screening | interview | offer | rejection

    app = (await db.execute(select(JobApplication).where(JobApplication.id == app_id))).scalar_one_or_none()
    if not app: raise HTTPException(404)
    job = (await db.execute(select(JobPosting).where(JobPosting.id == app.job_id))).scalar_one_or_none()

    type_prompts = {
        "screening": "Write a professional screening acknowledgement email telling the candidate we received their application and will be in touch.",
        "interview": f"Write a professional interview invitation email. Interview date: {app.interview_date or 'TBD'}. Include the job title.",
        "offer":     "Write a professional job offer email congratulating the candidate and expressing excitement about them joining.",
        "rejection": "Write a kind, professional rejection email thanking the candidate for their time and encouraging future applications.",
    }
    msgs = [
        {"role": "system", "content": (
            "You are an HR communication specialist. Write professional, warm, concise emails. "
            "Use the candidate's name and job title. Do not use placeholder brackets."
        )},
        {"role": "user", "content": (
            f"Candidate: {app.applicant_name}\n"
            f"Job: {job.title if job else 'the position'}\n"
            f"Company: BOSS System / MindSync AI Consults\n\n"
            f"Task: {type_prompts.get(msg_type, type_prompts['screening'])}"
        )},
    ]
    result = await ai_service.chat_complete(msgs)

    # Save to HR notifications log
    db.add(HRNotification(
        application_id=app_id, type=msg_type,
        subject=f"{msg_type.title()} — {job.title if job else 'Position'}",
        body=result,
    ))
    if msg_type == "offer":   app.offer_sent = True
    if msg_type == "rejection": app.rejection_sent = True
    await db.commit()

    return JSONResponse({"message": result, "type": msg_type})


# ═══════════════════════════════════════════════════════════════════════════════
#  INTERNAL NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/notifications")
async def get_notifications(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    notifs = (await db.execute(
        select(InternalNotification)
        .where(InternalNotification.user_id == current_user.id)
        .order_by(InternalNotification.created_at.desc())
        .limit(30)
    )).scalars().all()
    unread = sum(1 for n in notifs if not n.is_read)
    return JSONResponse({
        "unread": unread,
        "notifications": [{
            "id": n.id, "title": n.title, "body": n.body,
            "type": n.type, "link": n.link,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else "",
        } for n in notifs],
    })


@router.post("/notifications/{notif_id}/read")
async def mark_notif_read(notif_id: int, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(require_user)):
    n = (await db.execute(
        select(InternalNotification)
        .where(InternalNotification.id == notif_id, InternalNotification.user_id == current_user.id)
    )).scalar_one_or_none()
    if n:
        n.is_read = True
        await db.commit()
    return JSONResponse({"status": "read"})


@router.post("/notifications/read-all")
async def mark_all_read(db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user)):
    notifs = (await db.execute(
        select(InternalNotification)
        .where(InternalNotification.user_id == current_user.id, InternalNotification.is_read == False)
    )).scalars().all()
    for n in notifs:
        n.is_read = True
    await db.commit()
    return JSONResponse({"status": "done"})


# ── Helper: create internal notification from anywhere ────────────────────────
async def create_notification(db, user_id: int, title: str, body: str,
                               type: str = "info", link: str = ""):
    db.add(InternalNotification(
        user_id=user_id, title=title, body=body, type=type, link=link,
    ))
    # Also try web push
    try:
        from app.routers.push import notify_user
        await notify_user(user_id=user_id, title=title, body=body, url=link or "/", db=db)
    except Exception:
        pass