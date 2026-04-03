# BOSS System — Business Operating System
### Developed by MindSync AI Consults

> **The intelligent backbone of your organization.** BOSS is a full-stack, AI-powered corporate operating platform that unifies communication, knowledge management, compliance, risk, HR, accounting, inventory, and business operations — all in one dark-themed, real-time progressive web application.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              BOSS SYSTEM OVERVIEW                                │
└──────────────────────────────────────────────────────────────────────────────────┘

  Browser / Mobile (PWA)
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │  Dashboard │ Messages │ Ask BOSS │ Docs │ BCC │ HR │ Accounting │ Inventory  │
  └──────────────────────────────┬───────────────────────────────────────────────┘
                                 │  HTTPS / WSS / SSE
                                 ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │                        FastAPI Application                                   │
  │                                                                              │
  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │
  │  │  Auth +  │ │ Messages │ │ Ask BOSS │ │   BCC    │ │   Business Ops   │  │
  │  │  SSO     │ │  + WS    │ │ SSE/RAG  │ │ Router   │ │ Tasks/Meetings   │  │
  │  └──────────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────────────────┘  │
  │  ┌──────────┐ ┌────▼─────┐ ┌────▼─────┐ ┌────▼─────┐ ┌──────────────────┐  │
  │  │  Push    │ │ WebSocket│ │  Ollama  │ │Accounting│ │   IP Allowlist   │  │
  │  │  Notifs  │ │ Manager  │ │ Service  │ │Inventory │ │   Middleware     │  │
  │  └──────────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────────────────┘  │
  │                    │            │             │                              │
  │            ┌───────▼────────────▼─────────────▼──────────────────────────┐  │
  │            │                   AI Service Layer                          │  │
  │            │  • Vector RAG (sentence-transformers embeddings)            │  │
  │            │  • Knowledge extraction from chat messages                  │  │
  │            │  • Compliance detection · Risk detection                    │  │
  │            │  • CV screening · AI priority scoring                       │  │
  │            │  • Meeting summary · Onboarding assistant                   │  │
  │            │  • Natural language transaction parsing                     │  │
  │            └──────────────────────┬──────────────────────────────────┬──┘  │
  └─────────────────────────────────  │  ─────────────────────────────── │ ────┘
                                      │                                  │
               ┌──────────────────────▼──────────┐     ┌────────────────▼──────┐
               │        PostgreSQL Database       │     │     Ollama LLM        │
               │  35+ tables across all modules   │     │   (Local, Offline)    │
               │  users · channels · messages     │     │  codellama:7b /       │
               │  documents · knowledge_chunks    │     │  mistral:7b /         │
               │  accounting · inventory          │     │  llama3.2:3b          │
               │  job_postings · applications     │     │  Runs on your machine │
               │  tasks · meetings · leave        │     └───────────────────────┘
               │  push_subscriptions · ip_allow  │
               └──────────────────────────────────┘
```

---

## Knowledge Flow

```
  ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────────┐
  │  Upload    │   │   Chat     │   │  Approved  │   │  Manual Entry  │
  │  CV/Doc    │   │  Messages  │   │  Document  │   │  (Direct text) │
  └─────┬──────┘   └─────┬──────┘   └─────┬──────┘   └───────┬────────┘
        └──────────────── ▼ ───────────────┘                  │
                   ┌──────▼──────────────────────────────────▼──┐
                   │              AI Processing Layer            │
                   │  PDF/DOCX/CSV extraction · Chunking         │
                   │  Summarization · Compliance detection        │
                   │  Risk detection · Embedding (384-dim)        │
                   └──────────────────────┬──────────────────────┘
                                          ▼
                   ┌──────────────────────────────────────────────┐
                   │             knowledge_chunks table            │
                   │  content · summary · embedding (vector)      │
                   │  source_type · department · document_id      │
                   └──────────────────────┬──────────────────────┘
                                          ▼  (Ask BOSS query)
                   ┌──────────────────────────────────────────────┐
                   │              Vector RAG Pipeline             │
                   │  1. Embed query (all-MiniLM-L6-v2)           │
                   │  2. Cosine similarity search                 │
                   │  3. Top 5 chunks → context window            │
                   │  4. Ollama generates cited answer            │
                   │  5. Stream via SSE + citation chips          │
                   └──────────────────────────────────────────────┘
```

---

## Module Deep-Dive

### 1. Dashboard
The command center with a real-time overview of the entire organization:

- Document count, user count, active users (online indicator), pending approvals
- Compliance score rendered as an animated SVG ring (green/amber/red by threshold)
- Recent activity feed — last 8 audit log events with color-coded action badges
- Quick action buttons — upload document, open AI chat, manage users
- Recent documents list with status badges
- Unread announcement badge and notification bell in topbar

---

### 2. Messages (Real-Time Communication)
A full-featured internal communication system modelled after WhatsApp/Slack:

**Direct Messages** — private 1-on-1 conversations with online presence indicators.

**Department Channels** — select departments on creation; all members auto-added. Edit membership at any time.

**Message Features:**
- File sharing: PDF, DOCX, XLSX, CSV, TXT, PNG, JPG, GIF, WebP, MP4, ZIP
- Image inline preview with lightbox; file cards for non-images
- Reply-to with quoted preview; delete own messages (admins delete any)
- Typing indicators, auto-reconnect (3 s), keep-alive ping (25 s)
- WS status badge: Connected / Connecting / Disconnected
- Speech bubble tails, 68% max-width bubbles, date separators, avatar grouping
- Hover-reveal action buttons (reply, delete)

**AI Knowledge Extraction** — every message silently analysed; business knowledge auto-stored in the knowledge base asynchronously.

---

### 3. Ask BOSS (AI Assistant)
RAG-powered AI chat connected to your entire company knowledge base:

- **Vector semantic search** — `all-MiniLM-L6-v2` embeddings, cosine similarity, keyword fallback
- **Streaming SSE responses** — token-by-token typing effect
- **Citation chips** — every response shows which document/chunk it used, with relevance score
- **Persistent sessions** — full history saved, resumable from sidebar
- **Role-aware access** — confidential docs only surfaced for admins/executives
- **Onboarding Assistant** — warm dedicated AI chat for new employees at `/ask-boss/onboarding-assistant` with quick-start chips and department-aware context
- **Meeting Summary** — `POST /ask-boss/meeting-summary/{channel_id}` generates structured summaries (topics, decisions, action items, next steps) from channel history
- **Fully offline** — runs on your machine via Ollama

---

### 4. Knowledge Base
The organisation's accumulated intelligence:

- Auto-populated from approved documents, chat messages, and manual entries
- Three source types: `document`, `message`, `manual`
- Full-text search + department filter
- AI-generated 1–2 sentence summary per chunk
- Embedding stored per chunk for vector retrieval

---

### 5. Documents
Structured document repository with approval workflow:

- Upload PDF, DOCX, DOC, CSV, TXT
- Status pipeline: Draft → Pending → Approved / Rejected
- Access levels: `all_staff` · `restricted` · `confidential`
- On approval: text extracted → chunked → embedded → knowledge base
- Background AI tasks: compliance extraction + risk detection

---

### 6. Users & Roles

| Role | Key Permissions |
|---|---|
| `super_admin` | Full system access, all features, IP allowlist, SSO settings |
| `admin` | Approve documents, manage users, view all content |
| `manager` | View restricted docs, approve leave, oversee onboarding |
| `staff` | Chat, ask BOSS, upload docs, view all_staff content |
| `new_employee` | Onboarding steps only, limited access |

First registered account automatically becomes Super Admin.

---

### 7. Onboarding
Guided step-by-step onboarding for new employees:

- Admin creates steps (title, description, order, required/optional, linked document)
- Progress bar per employee visible to managers/admins
- Employees self-mark steps complete; auto-graduation when all required steps done
- Onboarding AI Assistant available at any time for questions

---

### 8. Compliance
Automated regulatory monitoring:

- AI scans every approved document for compliance requirements
- Register with regulation type, risk level, and status tracking
- Status flow: `identified` → `compliant` / `non_compliant` / `pending`
- Compliance score (%) on dashboard and compliance page
- Manual notes and status updates by managers/admins

---

### 9. Risk Management
Structured risk register:

- Likelihood × Impact scoring (1–5 each, score 1–25)
- Auto-classification: Critical (≥15) · High (8–14) · Medium (4–7) · Low (<4)
- **AI auto-detection** — risks auto-created from approved documents via background task
- `auto_detected` flag distinguishes AI risks from manually entered ones
- Status lifecycle: open → mitigated → closed

---

### 10. Audit Logs
System-wide tamper-visible activity trail:

- Every action logged: logins (including SSO), document events, approvals, user changes
- Records: timestamp, user, action, resource type, resource ID, details JSON, IP address
- Visible to super_admin and admin only
- Color-coded action badges

---

### 11. Business Operations

**Task Board** (Kanban)
- Three columns: To Do / In Progress / Done
- Drag-and-drop between columns (drag-and-drop via native HTML5 DnD)
- Priority levels: low · medium · high · urgent with color-coded dots
- Due date badges: green (>2 days) · amber (≤2 days) · red (overdue)
- **AI Priority Suggestion** — click robot icon to get AI-suggested priority with reason
- Assign to any team member; filter by department

**Meeting Scheduler**
- Book meetings with start/end time, location, description
- Invite multiple attendees; RSVP (Accept / Decline) per attendee
- **AI Agenda Generation** — pulls last 30 messages from linked channel, generates structured time-boxed agenda
- Meeting summaries stored per channel per day

**Announcement Board**
- Admins post company-wide notices with priority: Normal · Important · Urgent
- Color-coded cards with unread badge on topbar
- Read confirmation per user; read count visible to admins
- Optional expiry date; archive to remove

**Employee Directory**
- Searchable by name, email, department
- Grouped by department with headcount
- Online/offline indicator per employee
- Reporting lines — super_admin can assign manager to any employee
- Displayed on each employee card

**Leave / Absence Tracker**
- Employees submit requests: Annual · Sick · Maternity · Paternity · Unpaid · Other
- Managers/admins approve or reject with optional note
- Weekly absence calendar sidebar showing who's off
- Cancel pending requests

---

### 12. Business Command Centre (BCC)

**BCC Dashboard** — unified KPI view: total income, total expenses, net P&L, low-stock alerts, open jobs, pending HR applications, recent transactions.

#### Accounting
- Record income and expenses manually or via **natural language AI entry**
- Type _"I paid $15,000 for transportation today"_ → AI parses type, amount, category, description → confirm and save
- Full transaction history with filters (type, month)
- Export all records to CSV
- Color-coded income (green) / expense (red) rows

#### Inventory Management
- Card-based stock board with progress bar per item showing stock health
- Color-coded alerts: red (out of stock) · amber (at or below reorder level) · green (healthy)
- Stock movements: Stock In · Stock Out · Return In · Adjustment
- Full movement history per item
- Auto-generates SKU if not provided
- Total portfolio value calculation
- Supplier and storage location tracking

#### AI Recruitment (HR)
Full 7-stage hiring pipeline — the system does the heavy lifting:

**Stage flow:** Received → Screening → Shortlisted → Interview → Offer → Hired → Rejected

**What the AI does automatically:**
1. **CV Screening** — upload PDF/DOCX; AI extracts text, scores candidate 0–100 against job requirements, identifies strengths and gaps, gives recommendation: `shortlist` / `consider` / `reject`
2. **Bulk screening** — queue all unscreened CVs for a job at once
3. **Email generation** — one-click AI writes professional emails for every pipeline stage:
   - Screening acknowledgement
   - Interview invitation (includes scheduled date)
   - Job offer letter
   - Rejection email (warm, encouraging)
4. **Status management** — drag each candidate through the pipeline; all changes logged

**What you control:**
- You always see AI recommendations before acting
- You approve every status change
- You decide who gets the offer

---

### 13. Security

**SSO (Single Sign-On)**
- Google Workspace OAuth2 — `/auth/sso/google`
- Microsoft 365 OAuth2 — `/auth/sso/microsoft`
- Auto-creates user account on first SSO login; links to existing account by email
- Buttons appear on login page only when credentials are configured in `.env`

**IP Allowlist**
- Middleware enforces IP-based access control when `IP_ALLOWLIST_ENABLED=true`
- Super admin manages rules at `/settings/ip-allowlist`
- Supports single IPs and CIDR ranges (e.g. `192.168.1.0/24`)
- Always exempts SSO callbacks, static files, and health endpoints
- 60-second DB cache to avoid per-request overhead
- "Detect my IP" button auto-fills your current IP

---

### 14. Progressive Web App (PWA)
- `manifest.json` with full icon set, shortcuts, and theme colors
- Service worker with network-first for pages, cache-first for static assets
- Offline fallback page when network unavailable
- Install prompt via `beforeinstallprompt` — **Install App** button in Settings
- Runs in standalone mode (no browser chrome) once installed on phone/desktop

---

### 15. Push Notifications
- Web Push API with VAPID keys — no third-party service required
- Notifications delivered even when the tab is closed
- Per-device subscription — one user can have multiple devices subscribed
- Notification includes title, body, icon, click-through URL, and vibrate pattern
- **Enable Notifications** button in Settings; test via **Send Test**
- Used internally by the messages router for new message notifications

---

### 16. Internal Notifications (In-App)
- Bell icon in topbar with real-time unread badge
- Dropdown panel with click-to-navigate, mark-as-read per item
- Mark all read button
- Polls every 30 seconds; also triggered immediately by server events
- Types: `info` · `success` · `warning` · `error` · `message` · `hr`
- Fires web push simultaneously when a notification is created

---

## Full Tech Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3.11+ |
| **Web Framework** | FastAPI |
| **ORM** | SQLAlchemy 2.0 (async) |
| **Database** | PostgreSQL (via asyncpg) |
| **Real-time** | WebSockets (native FastAPI) + SSE |
| **Session Middleware** | Starlette SessionMiddleware (for SSO state) |
| **AI Engine** | Ollama (local LLM, fully offline) |
| **AI Model** | codellama:7b-instruct-q4_K_M (default) |
| **Embeddings** | sentence-transformers `all-MiniLM-L6-v2` (384-dim) |
| **File Parsing** | PyPDF2 · python-docx · pandas |
| **Templates** | Jinja2 |
| **Frontend** | Vanilla JS · CSS variables · SSE · HTML5 DnD |
| **Auth** | JWT (python-jose) · bcrypt · httpOnly cookies |
| **SSO** | Google OAuth2 · Microsoft OAuth2 (via httpx) |
| **Push Notifications** | Web Push API · pywebpush · VAPID keys |
| **PWA** | Service Worker · Web App Manifest |
| **Fonts** | Syne · DM Sans · JetBrains Mono |

---

## Database Schema (35+ Tables)

```
CORE
────────────────────────────────────────────────────────────────────
users                   channels              messages
oauth_accounts          channel_members       knowledge_chunks
push_subscriptions      ip_allowlist          audit_logs
app_settings            internal_notifications

DOCUMENTS & AI
────────────────────────────────────────────────────────────────────
documents               ai_conversations      ai_messages
compliance_records      risk_items            meeting_summaries
onboarding_conversations

ONBOARDING
────────────────────────────────────────────────────────────────────
onboarding_steps        onboarding_progress

BUSINESS OPERATIONS
────────────────────────────────────────────────────────────────────
tasks                   meeting_rooms         meeting_attendees
announcements           announcement_reads    leave_requests
reporting_lines

BUSINESS COMMAND CENTRE
────────────────────────────────────────────────────────────────────
accounting_records      accounting_categories
inventory_items         inventory_movements
job_postings            job_applications      hr_notifications
```

---

## Quick Setup

### Prerequisites

```bash
# Python 3.11+
python --version

# PostgreSQL
# Windows: https://postgresql.org/download/windows
# Ubuntu:  sudo apt install postgresql
# macOS:   brew install postgresql

# Ollama (local AI — runs fully offline)
# Windows/macOS: https://ollama.ai/download
# Linux: curl -fsSL https://ollama.ai/install.sh | sh
```

### 1. Database

```sql
CREATE DATABASE boss_system;
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Key settings in `.env`:

```env
# Core
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5432/boss_system
SECRET_KEY=your-minimum-32-character-random-string
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# AI
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=codellama:7b-instruct-q4_K_M

# Files
UPLOAD_DIR=uploads
MAX_FILE_SIZE_MB=50

# SSO (leave blank to hide buttons)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/sso/google/callback
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_TENANT_ID=common
MICROSOFT_REDIRECT_URI=http://localhost:8000/auth/sso/microsoft/callback

# Security
IP_ALLOWLIST_ENABLED=false

# Push Notifications (generate keys — see below)
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_CLAIMS_EMAIL=admin@yourcompany.com
```

### 3. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 4. Pull AI Model

```bash
ollama pull codellama:7b-instruct-q4_K_M
```

Lighter alternatives:
- `ollama pull llama3.2:3b` (~2 GB, fastest)
- `ollama pull mistral:7b-instruct-q4_K_M` (~4 GB, excellent quality)

### 5. Generate VAPID Keys (Push Notifications)

```bash
python -c "
from py_vapid import Vapid
v = Vapid()
v.generate_keys()
print('VAPID_PUBLIC_KEY=' + v.public_key_urlsafe)
print('VAPID_PRIVATE_KEY=' + v.private_key_urlsafe)
"
```

Paste both values into `.env`.

### 6. Start

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000**

### 7. First Login

1. Go to **http://localhost:8000/auth/register**
2. Register — the **first account automatically becomes Super Admin**
3. Log in and begin configuring your organization

---

## File Upload Limits & Supported Types

| Category | Formats | Where Used |
|---|---|---|
| Documents | PDF, DOCX, DOC, CSV, TXT | Knowledge base, compliance, BCC HR CVs |
| Images | PNG, JPG, JPEG, GIF, WebP | Messages inline preview + lightbox |
| Office | XLSX | Messages download card |
| Video | MP4 | Messages download card |
| Archives | ZIP | Messages download card |
| CVs | PDF, DOCX | HR recruitment pipeline |

Max file size: `MAX_FILE_SIZE_MB` in `.env` (default: 50 MB)

---

## Project Structure

```
boss_system/
├── main.py                              # FastAPI app, middleware, all routers
├── requirements.txt
├── .env.example
├── uploads/
│   ├── documents/
│   ├── messages/
│   └── cvs/                             # HR applicant CVs
└── app/
    ├── config.py                        # Pydantic settings from .env
    ├── database.py                      # Async SQLAlchemy engine + session
    ├── models.py                        # All 35+ ORM models
    ├── auth.py                          # JWT + bcrypt + cookie dependencies
    ├── middleware/
    │   └── ip_allowlist.py              # IP range enforcement middleware
    ├── routers/
    │   ├── auth.py                      # /auth/* — login, register, logout, ws-token
    │   ├── sso.py                       # /auth/sso/* — Google + Microsoft OAuth2
    │   ├── push.py                      # /push/* — VAPID Web Push notifications
    │   ├── bcc.py                       # /bcc/* — Accounting, Inventory, HR, Notifications
    │   ├── dashboard.py                 # /dashboard
    │   ├── messages.py                  # /messages/* — WebSocket chat
    │   ├── ask_boss.py                  # /ask-boss/* — RAG AI, SSE, onboarding, meeting summary
    │   ├── documents.py                 # /documents/* + /knowledge-base
    │   ├── admin.py                     # /users, /onboarding, /compliance, /risk, /settings, /ip-allowlist
    │   └── business_ops.py             # /tasks, /meetings, /announcements, /directory, /leave
    ├── services/
    │   ├── ai_service.py               # Ollama · Vector RAG · CV screening · NL accounting · Risk detection
    │   ├── document_service.py         # PDF/DOCX/CSV extraction + chunking
    │   └── websocket_manager.py        # Multi-channel WS manager
    ├── templates/
    │   ├── base.html                   # Sidebar layout · topbar · notifications bell · PWA JS
    │   ├── auth/
    │   │   ├── login.html              # Email/password + Google + Microsoft SSO buttons
    │   │   └── register.html
    │   ├── dashboard/index.html
    │   ├── messages/index.html
    │   ├── ask_boss/
    │   │   ├── index.html              # RAG chat with citation chips
    │   │   └── onboarding_assistant.html
    │   ├── bcc/
    │   │   ├── dashboard.html          # BCC command centre overview
    │   │   ├── accounting.html         # AI natural-language transaction entry
    │   │   ├── inventory.html          # Stock cards, movements, alerts
    │   │   ├── hr_jobs.html            # Job postings, pipeline stats
    │   │   └── hr_applications.html    # CV upload, AI screening, email generation
    │   ├── business/
    │   │   ├── tasks.html              # Kanban board
    │   │   ├── meetings.html           # Meeting scheduler + AI agenda
    │   │   ├── announcements.html      # Company notices
    │   │   ├── directory.html          # Org chart + reporting lines
    │   │   └── leave.html              # Leave requests + absence calendar
    │   ├── knowledge/index.html
    │   ├── documents/{index,new}.html
    │   ├── users/index.html
    │   ├── onboarding/index.html
    │   ├── compliance/index.html
    │   ├── risk/index.html
    │   ├── audit/index.html
    │   ├── settings/
    │   │   ├── index.html              # Profile, password, notifications, PWA install
    │   │   └── ip_allowlist.html       # IP range management (super_admin)
    │   └── errors/{403,404}.html
    └── static/
        ├── manifest.json               # PWA manifest
        ├── sw.js                       # Service worker
        ├── img/                        # PWA icons (72–512 px)
        ├── css/custom.css
        └── js/app.js
```

---

## Production Deployment

```bash
pip install gunicorn

gunicorn main:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120
```

**Nginx (required for WebSockets + PWA):**

```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /uploads/ {
        alias /path/to/boss_system/uploads/;
        add_header X-Content-Type-Options nosniff;
    }

    location /sw.js {
        proxy_pass http://127.0.0.1:8000/sw.js;
        add_header Service-Worker-Allowed /;
        add_header Cache-Control "no-cache";
    }
}
```

**Production checklist:**
- [ ] Set `SECRET_KEY` to a 64-character random string
- [ ] Change PostgreSQL password
- [ ] Enable HTTPS — required for PWA install + push notifications
- [ ] Set `cookie.secure=True` and `httponly=True` in `auth.py`
- [ ] Configure firewall — expose only 80 and 443
- [ ] Set up daily PostgreSQL backups (`pg_dump`)
- [ ] Use environment variables directly, not `.env` file
- [ ] Configure `IP_ALLOWLIST_ENABLED=true` and add office IP ranges
- [ ] Set VAPID keys for push notifications
- [ ] Configure Google/Microsoft SSO credentials if using SSO

---

## Optional SSO Setup

**Google Workspace:**
1. [console.cloud.google.com](https://console.cloud.google.com) → APIs & Services → Credentials → Create OAuth 2.0 Client
2. Authorized redirect URI: `https://yourdomain.com/auth/sso/google/callback`
3. Add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` to `.env`

**Microsoft 365:**
1. [portal.azure.com](https://portal.azure.com) → App registrations → New registration
2. Redirect URI: `https://yourdomain.com/auth/sso/microsoft/callback`
3. Create client secret under "Certificates & secrets"
4. Add `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_TENANT_ID` to `.env`

---

## Customization

| What to change | Where |
|---|---|
| AI model | `OLLAMA_MODEL` in `.env` |
| Brand name / accent color | `:root` CSS variables in `base.html` |
| Departments list | Department arrays in router files and templates |
| Max file upload size | `MAX_FILE_SIZE_MB` in `.env` |
| Session duration | `ACCESS_TOKEN_EXPIRE_MINUTES` in `.env` |
| Push notification icon | `app/static/img/icon-192.png` |
| Allowed chat file types | `ALLOWED_EXTENSIONS` in `messages.py` |
| Accounting currency | `currency` default in `AccountingRecord` model |
| Notification poll interval | `setInterval(loadNotifications, 30000)` in `base.html` |

---

*Built with ❤️ by **David Akpele** · BOSS System v2.0*