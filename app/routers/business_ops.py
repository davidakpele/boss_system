# app/routers/business_ops.py
from fastapi import APIRouter, Depends, Request, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from datetime import datetime, date, timedelta, timezone
from typing import Optional
from app.database import get_db
from app.models import (
    User, Task, MeetingRoom, MeetingAttendee, Announcement, AnnouncementRead,
    LeaveRequest, ReportingLine, Channel, Message
)
from app.auth import require_user
from app.services.ai_service import ai_service
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["business_ops"])
templates = Jinja2Templates(directory="app/templates")


# ═══════════════════════════════════════════════
#  TASK MANAGER
# ═══════════════════════════════════════════════

@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    dept: str = None,
):
    dept_filter = dept or current_user.department
    stmt = select(Task, User.full_name, User.avatar_color).outerjoin(
        User, Task.assigned_to == User.id
    ).order_by(Task.position.asc(), Task.created_at.desc())
    if dept_filter and current_user.role not in ("super_admin", "admin"):
        stmt = stmt.where(or_(Task.department == dept_filter, Task.assigned_to == current_user.id))
    rows = (await db.execute(stmt)).all()

    board = {"todo": [], "in_progress": [], "done": []}
    for task, aname, acolor in rows:
        board[task.status].append({"task": task, "assignee_name": aname, "assignee_color": acolor})

    all_users = (await db.execute(select(User).where(User.is_active == True).order_by(User.full_name))).scalars().all()
    depts = (await db.execute(select(User.department).distinct().where(User.department != None))).scalars().all()

    return templates.TemplateResponse(request=request, name="business/tasks.html", context={
        "user": current_user, 
        "board": board, 
        "all_users": all_users,
        "departments": depts, 
        "current_dept": dept_filter, 
        "page": "tasks",
        "now": datetime.now(), 
    })

@router.post("/tasks/create")
async def create_task(
    title: str = Form(...), description: str = Form(""),
    department: str = Form(""), priority: str = Form("medium"),
    assigned_to: int = Form(None), due_date: str = Form(None),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    due = None
    if due_date:
        try:
            due = datetime.fromisoformat(due_date)
        except ValueError:
            pass

    task = Task(
        title=title, description=description, department=department or current_user.department,
        priority=priority, assigned_to=assigned_to or None,
        created_by=current_user.id, due_date=due, status="todo",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return JSONResponse({"status": "created", "id": task.id})


@router.post("/tasks/{task_id}/move")
async def move_task(
    task_id: int, status: str = Form(...),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    if status not in ("todo", "in_progress", "done"):
        raise HTTPException(status_code=400, detail="Invalid status")
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404)
    task.status = status
    await db.commit()
    return JSONResponse({"status": "moved", "new_status": status})


@router.post("/tasks/{task_id}/update")
async def update_task(
    task_id: int, title: str = Form(...), description: str = Form(""),
    priority: str = Form("medium"), assigned_to: int = Form(None),
    due_date: str = Form(None), status: str = Form("todo"),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404)
    task.title = title; task.description = description
    task.priority = priority; task.assigned_to = assigned_to or None; task.status = status
    if due_date:
        try:
            task.due_date = datetime.fromisoformat(due_date)
        except ValueError:
            pass
    await db.commit()
    return JSONResponse({"status": "updated"})


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404)
    if task.created_by != current_user.id and current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403)
    await db.delete(task)
    await db.commit()
    return JSONResponse({"status": "deleted"})


@router.post("/tasks/{task_id}/ai-priority")
async def ai_suggest_priority(
    task_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404)

    msgs = [
        {"role": "system", "content": (
            "You are a business task prioritization AI. Given a task title and description, "
            "suggest a priority level (low/medium/high/urgent) and a brief 1-sentence reason. "
            "Respond in JSON: {\"priority\": \"high\", \"reason\": \"...\"}"
        )},
        {"role": "user", "content": f"Task: {task.title}\nDescription: {task.description or 'N/A'}\nDue: {task.due_date or 'Not set'}"}
    ]
    result = await ai_service.chat_complete(msgs)
    try:
        import json
        clean = result.strip().replace("```json","").replace("```","").strip()
        data = json.loads(clean)
        task.priority = data.get("priority", task.priority)
        task.ai_priority_reason = data.get("reason", "")
        await db.commit()
        return JSONResponse({"priority": task.priority, "reason": task.ai_priority_reason})
    except Exception:
        return JSONResponse({"priority": task.priority, "reason": "Could not parse AI response"})


# ═══════════════════════════════════════════════
#  MEETING ROOM SCHEDULER
# ═══════════════════════════════════════════════

@router.get("/meetings", response_class=HTMLResponse)
async def meetings_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    # Meetings where user is organizer or attendee
    my_meeting_ids = (await db.execute(
        select(MeetingAttendee.meeting_id).where(MeetingAttendee.user_id == current_user.id)
    )).scalars().all()

    stmt = (
        select(MeetingRoom)
        .where(or_(
            MeetingRoom.organizer_id == current_user.id,
            MeetingRoom.id.in_(my_meeting_ids),
        ))
        .order_by(MeetingRoom.start_time.asc())
    )
    meetings = (await db.execute(stmt)).scalars().all()

    all_users = (await db.execute(select(User).where(User.is_active == True).order_by(User.full_name))).scalars().all()
    channels = (await db.execute(select(Channel).where(Channel.channel_type == "department"))).scalars().all()

    # Enrich with attendee data
    enriched = []
    for m in meetings:
        attendees = (await db.execute(
            select(MeetingAttendee, User.full_name, User.avatar_color)
            .join(User, MeetingAttendee.user_id == User.id)
            .where(MeetingAttendee.meeting_id == m.id)
        )).all()
        organizer = (await db.execute(select(User).where(User.id == m.organizer_id))).scalar_one_or_none()
        enriched.append({"meeting": m, "attendees": attendees, "organizer": organizer})

    return templates.TemplateResponse(request=request, name="business/meetings.html", context={
        "user": current_user, "meetings": enriched, "all_users": all_users,
        "channels": channels, "page": "meetings",
        "now": datetime.now(timezone.utc),
    })


@router.post("/meetings/create")
async def create_meeting(
    title: str = Form(...), description: str = Form(""),
    start_time: str = Form(...), end_time: str = Form(...),
    location: str = Form(""), agenda: str = Form(""),
    attendee_ids: str = Form(""), channel_id: int = Form(None),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    meeting = MeetingRoom(
        title=title, description=description,
        organizer_id=current_user.id,
        start_time=datetime.fromisoformat(start_time),
        end_time=datetime.fromisoformat(end_time),
        location=location, agenda=agenda,
        channel_id=channel_id or None,
    )
    db.add(meeting)
    await db.flush()

    # Add organizer as attendee
    db.add(MeetingAttendee(meeting_id=meeting.id, user_id=current_user.id, status="accepted"))
    # Add other attendees
    for uid in attendee_ids.split(","):
        uid = uid.strip()
        if uid.isdigit() and int(uid) != current_user.id:
            db.add(MeetingAttendee(meeting_id=meeting.id, user_id=int(uid), status="invited"))

    await db.commit()
    return JSONResponse({"status": "created", "id": meeting.id})


@router.post("/meetings/{meeting_id}/generate-agenda")
async def generate_meeting_agenda(
    meeting_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    meeting = (await db.execute(select(MeetingRoom).where(MeetingRoom.id == meeting_id))).scalar_one_or_none()
    if not meeting:
        raise HTTPException(status_code=404)

    context = f"Meeting: {meeting.title}\nDescription: {meeting.description or 'N/A'}"

    # Pull recent channel messages if linked
    if meeting.channel_id:
        msgs = (await db.execute(
            select(Message, User.full_name)
            .join(User, Message.sender_id == User.id)
            .where(Message.channel_id == meeting.channel_id, Message.message_type == "text")
            .order_by(Message.created_at.desc()).limit(30)
        )).all()
        if msgs:
            context += "\n\nRecent channel discussion:\n"
            for m, name in reversed(msgs):
                context += f"{name}: {m.content}\n"

    prompt_msgs = [
        {"role": "system", "content": (
            "You are a professional meeting facilitator. Generate a structured meeting agenda "
            "with time allocations. Format as:\n"
            "1. [Time] Topic — brief description\n"
            "2. [Time] Topic — brief description\n"
            "Keep it practical and time-boxed. Total should fit the meeting duration."
        )},
        {"role": "user", "content": context},
    ]
    agenda = await ai_service.chat_complete(prompt_msgs)
    if agenda:
        meeting.agenda = agenda
        meeting.ai_agenda_generated = True
        await db.commit()
    return JSONResponse({"agenda": agenda or "Could not generate agenda"})


@router.post("/meetings/{meeting_id}/rsvp")
async def rsvp_meeting(
    meeting_id: int, status: str = Form(...),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    attendee = (await db.execute(
        select(MeetingAttendee).where(
            MeetingAttendee.meeting_id == meeting_id,
            MeetingAttendee.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if attendee:
        attendee.status = status
        await db.commit()
    return JSONResponse({"status": status})


@router.delete("/meetings/{meeting_id}")
async def delete_meeting(
    meeting_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    meeting = (await db.execute(select(MeetingRoom).where(MeetingRoom.id == meeting_id))).scalar_one_or_none()
    if not meeting:
        raise HTTPException(status_code=404)
    if meeting.organizer_id != current_user.id and current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403)
    await db.execute(MeetingAttendee.__table__.delete().where(MeetingAttendee.meeting_id == meeting_id))
    await db.delete(meeting)
    await db.commit()
    return JSONResponse({"status": "deleted"})


# ═══════════════════════════════════════════════
#  ANNOUNCEMENT BOARD
# ═══════════════════════════════════════════════

@router.get("/announcements", response_class=HTMLResponse)
async def announcements_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    now = datetime.utcnow()
    announcements = (await db.execute(
        select(Announcement)
        .where(Announcement.is_active == True)
        .where(or_(Announcement.expires_at == None, Announcement.expires_at > now))
        .order_by(Announcement.created_at.desc())
    )).scalars().all()

    # Which ones has this user read?
    read_ids = set((await db.execute(
        select(AnnouncementRead.announcement_id).where(AnnouncementRead.user_id == current_user.id)
    )).scalars().all())

    # Read counts
    enriched = []
    for ann in announcements:
        rc = (await db.execute(
            select(func.count(AnnouncementRead.id)).where(AnnouncementRead.announcement_id == ann.id)
        )).scalar()
        author = (await db.execute(select(User).where(User.id == ann.created_by))).scalar_one_or_none()
        enriched.append({"ann": ann, "read_count": rc, "is_read": ann.id in read_ids, "author": author})

    return templates.TemplateResponse(request=request, name="business/announcements.html", context={
        "user": current_user, "announcements": enriched, "read_ids": read_ids, "page": "announcements",
    })


@router.post("/announcements/create")
async def create_announcement(
    title: str = Form(...), content: str = Form(...),
    priority: str = Form("normal"), expires_at: str = Form(None),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    if current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403)
    exp = None
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at)
        except ValueError:
            pass
    ann = Announcement(title=title, content=content, priority=priority,
                       created_by=current_user.id, expires_at=exp)
    db.add(ann)
    await db.commit()
    return JSONResponse({"status": "created"})


@router.post("/announcements/{ann_id}/read")
async def mark_read(
    ann_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    existing = (await db.execute(
        select(AnnouncementRead).where(
            AnnouncementRead.announcement_id == ann_id,
            AnnouncementRead.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if not existing:
        db.add(AnnouncementRead(announcement_id=ann_id, user_id=current_user.id))
        await db.commit()
    return JSONResponse({"status": "read"})


@router.delete("/announcements/{ann_id}")
async def delete_announcement(
    ann_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    if current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403)
    ann = (await db.execute(select(Announcement).where(Announcement.id == ann_id))).scalar_one_or_none()
    if ann:
        ann.is_active = False
        await db.commit()
    return JSONResponse({"status": "archived"})


@router.get("/announcements/unread-count")
async def unread_count(db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user)):
    now = datetime.utcnow()
    total = (await db.execute(
        select(func.count(Announcement.id))
        .where(Announcement.is_active == True)
        .where(or_(Announcement.expires_at == None, Announcement.expires_at > now))
    )).scalar()
    read = (await db.execute(
        select(func.count(AnnouncementRead.id)).where(AnnouncementRead.user_id == current_user.id)
    )).scalar()
    return JSONResponse({"unread": total - read})


# ═══════════════════════════════════════════════
#  EMPLOYEE DIRECTORY
# ═══════════════════════════════════════════════

@router.get("/directory", response_class=HTMLResponse)
async def directory_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    search: str = None, dept: str = None,
):
    stmt = select(User).where(User.is_active == True)
    if search:
        stmt = stmt.where(or_(
            User.full_name.ilike(f"%{search}%"),
            User.email.ilike(f"%{search}%"),
            User.department.ilike(f"%{search}%"),
        ))
    if dept:
        stmt = stmt.where(User.department == dept)
    stmt = stmt.order_by(User.department, User.full_name)
    users = (await db.execute(stmt)).scalars().all()

    # Load reporting lines
    lines = {r.employee_id: r.manager_id for r in (await db.execute(select(ReportingLine))).scalars().all()}
    manager_map = {}
    for uid, mid in lines.items():
        if mid:
            mgr = (await db.execute(select(User).where(User.id == mid))).scalar_one_or_none()
            if mgr:
                manager_map[uid] = mgr

    depts = (await db.execute(
        select(User.department).distinct().where(User.department != None)
    )).scalars().all()

    # Group by department
    by_dept = {}
    for u in users:
        d = u.department or "General"
        by_dept.setdefault(d, []).append(u)

    return templates.TemplateResponse(request=request, name="business/directory.html", context={
        "user": current_user, "by_dept": by_dept, "all_users": users,
        "manager_map": manager_map, "departments": depts,
        "filters": {"search": search, "dept": dept}, "page": "directory",
    })


@router.post("/directory/set-manager")
async def set_manager(
    employee_id: int = Form(...), manager_id: int = Form(None),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    if current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403)
    existing = (await db.execute(
        select(ReportingLine).where(ReportingLine.employee_id == employee_id)
    )).scalar_one_or_none()
    if existing:
        existing.manager_id = manager_id or None
    else:
        db.add(ReportingLine(employee_id=employee_id, manager_id=manager_id or None))
    await db.commit()
    return JSONResponse({"status": "updated"})


# ═══════════════════════════════════════════════
#  LEAVE / ABSENCE TRACKER
# ═══════════════════════════════════════════════

@router.get("/leave", response_class=HTMLResponse)
async def leave_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    # My requests
    my_requests = (await db.execute(
        select(LeaveRequest)
        .where(LeaveRequest.user_id == current_user.id)
        .order_by(LeaveRequest.created_at.desc())
    )).scalars().all()

    # Pending requests (managers/admins see all)
    pending = []
    if current_user.role in ("super_admin", "admin", "manager"):
        pending_rows = (await db.execute(
            select(LeaveRequest, User.full_name, User.department, User.avatar_color)
            .join(User, LeaveRequest.user_id == User.id)
            .where(LeaveRequest.status == "pending")
            .order_by(LeaveRequest.created_at.asc())
        )).all()
        pending = [{"req": r, "name": n, "dept": d, "color": c} for r, n, d, c in pending_rows]

    # Calendar: who's off this week
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    off_this_week = (await db.execute(
        select(LeaveRequest, User.full_name, User.avatar_color, User.department)
        .join(User, LeaveRequest.user_id == User.id)
        .where(
            LeaveRequest.status == "approved",
            LeaveRequest.start_date <= datetime.combine(week_end, datetime.max.time()),
            LeaveRequest.end_date >= datetime.combine(week_start, datetime.min.time()),
        )
        .order_by(LeaveRequest.start_date)
    )).all()

    return templates.TemplateResponse(request=request, name="business/leave.html", context={
        "user": current_user, "my_requests": my_requests,
        "pending": pending, "off_this_week": off_this_week,
        "week_start": week_start, "week_end": week_end, "today": today,
        "page": "leave",
    })


@router.post("/leave/submit")
async def submit_leave(
    leave_type: str = Form(...), start_date: str = Form(...),
    end_date: str = Form(...), reason: str = Form(""),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    days = max(1, (end.date() - start.date()).days + 1)
    req = LeaveRequest(
        user_id=current_user.id, leave_type=leave_type,
        start_date=start, end_date=end, days_count=days, reason=reason,
    )
    db.add(req)
    await db.commit()
    return JSONResponse({"status": "submitted", "days": days})


@router.post("/leave/{req_id}/review")
async def review_leave(
    req_id: int, status: str = Form(...), note: str = Form(""),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    if current_user.role not in ("super_admin", "admin", "manager"):
        raise HTTPException(status_code=403)
    req = (await db.execute(select(LeaveRequest).where(LeaveRequest.id == req_id))).scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404)
    req.status = status
    req.reviewed_by = current_user.id
    req.review_note = note
    req.reviewed_at = datetime.utcnow()
    await db.commit()
    return JSONResponse({"status": status})


@router.delete("/leave/{req_id}")
async def cancel_leave(
    req_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    req = (await db.execute(select(LeaveRequest).where(LeaveRequest.id == req_id))).scalar_one_or_none()
    if not req or req.user_id != current_user.id:
        raise HTTPException(status_code=403)
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="Can only cancel pending requests")
    await db.delete(req)
    await db.commit()
    return JSONResponse({"status": "cancelled"})