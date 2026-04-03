# BOSS System — Business Operating System
### Developed by MindSync AI Consults

> **The intelligent backbone of your organization.** BOSS is a full-stack, AI-powered corporate operating platform that unifies communication, knowledge management, compliance, risk, and onboarding — all in one dark-themed, real-time web application.

---

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          BOSS SYSTEM OVERVIEW                               │
└─────────────────────────────────────────────────────────────────────────────┘

  Browser (Users)
  ┌─────────────────────────────────────────────────────────────────────┐
  │  Dashboard │ Messages │ Ask BOSS │ Docs │ Knowledge │ Compliance... │
  └────────────────────────┬────────────────────────────────────────────┘
                           │  HTTP / WebSocket
                           ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                     FastAPI Application                             │
  │                                                                     │
  │  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
  │  │  Auth    │  │ Messages │  │ Ask BOSS  │  │    Documents     │  │
  │  │ (JWT +   │  │ Router   │  │  Router   │  │    Router        │  │
  │  │  Cookie) │  │ + WS     │  │  SSE Stream│  │  (Upload+Approve)│  │
  │  └──────────┘  └────┬─────┘  └─────┬─────┘  └────────┬─────────┘  │
  │                     │              │                  │            │
  │  ┌──────────┐  ┌────▼─────┐  ┌─────▼─────┐  ┌────────▼─────────┐  │
  │  │ Dashboard│  │ WebSocket│  │   Ollama  │  │  File Parser     │  │
  │  │  Router  │  │ Manager  │  │  Service  │  │ PDF/DOCX/CSV/TXT │  │
  │  └──────────┘  └────┬─────┘  └─────┬─────┘  └────────┬─────────┘  │
  │                     │              │                  │            │
  │             ┌───────▼──────────────▼──────────────────▼──────────┐ │
  │             │               AI Service Layer                     │ │
  │             │  • RAG Retrieval (keyword search on knowledge base) │ │
  │             │  • Knowledge extraction from chat messages          │ │
  │             │  • Compliance detection from documents              │ │
  │             │  • Document summarization                           │ │
  │             └───────────────────────┬──────────────────────────┬─┘ │
  └─────────────────────────────────────┼──────────────────────────┼───┘
                                        │                          │
                  ┌─────────────────────▼──────┐    ┌─────────────▼───────┐
                  │      PostgreSQL Database    │    │    Ollama LLM       │
                  │                            │    │  (Local, Offline)   │
                  │  users, channels, messages │    │                     │
                  │  documents, knowledge_chunks│    │ codellama:7b-instruct│
                  │  compliance_records        │    │  -q4_K_M            │
                  │  risk_items, audit_logs    │    │                     │
                  │  ai_conversations, ...     │    │  Runs on your       │
                  └────────────────────────────┘    │  own machine        │
                                                    └─────────────────────┘
```

---

## Knowledge Flow Diagram

```
  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
  │   Upload     │    │   Chat       │    │   Manual     │
  │   Document   │    │   Messages   │    │   Entry      │
  │ PDF/DOCX/CSV │    │ (Messages tab│    │  (Documents  │
  └──────┬───────┘    └──────┬───────┘    │   form)      │
         │                  │            └──────┬───────┘
         ▼                  ▼                   ▼
  ┌──────────────────────────────────────────────────────┐
  │                  AI Processing Layer                 │
  │                                                      │
  │  • Text extraction (PDF → text, DOCX → paragraphs)   │
  │  • Chunking (500-word overlapping segments)          │
  │  • Summarization (Ollama generates summaries)        │
  │  • Compliance detection (regulatory requirements)    │
  │  • Knowledge scoring from chat messages              │
  └──────────────────────────┬───────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────┐
  │               knowledge_chunks table                 │
  │                                                      │
  │  source_type: "document" | "message" | "manual"      │
  │  content: raw text chunk                             │
  │  summary: AI-generated summary                       │
  │  department: HR | Sales | Technology | ...           │
  └──────────────────────────┬───────────────────────────┘
                             │
                             ▼ (on Ask BOSS query)
  ┌──────────────────────────────────────────────────────┐
  │                  RAG Retrieval                       │
  │                                                      │
  │  1. User asks question                               │
  │  2. Keywords extracted from question                 │
  │  3. Matching chunks retrieved from DB                │
  │  4. Top 5 chunks sent as context to Ollama           │
  │  5. Ollama generates answer grounded in company data │
  │  6. Response streamed back to user (SSE)             │
  └──────────────────────────────────────────────────────┘
```

---

## WebSocket Communication Diagram

```
  User A (Browser)          BOSS Server           User B (Browser)
        │                        │                       │
        │── WS Connect (/ws/42) ─▶│                       │
        │                        │◀─ WS Connect (/ws/42) ─│
        │                        │                       │
        │── {type:"message",     │                       │
        │    content:"Hello"} ──▶│── {type:"message",   ─▶│
        │                        │    sender:"User A",   │
        │◀─ {type:"message",...} ─│    content:"Hello"}   │
        │  (own echo back for    │                       │
        │   confirmation)        │── [AI extraction runs │
        │                        │   in background]      │
        │                        │                       │
        │── {type:"typing"} ────▶│── {type:"typing",    ─▶│
        │                        │    user:"User A"}     │
        │                        │                       │
        │── {type:"ping"} ──────▶│──▶{type:"pong"}       │
        │   (every 25s)          │                       │
        │                        │                       │
        │── DELETE /message/5 ──▶│── {type:"msg_deleted"─▶│
        │                        │    id: 5}             │
```

---

## Module Deep-Dive

### 1. Dashboard
The command center showing a real-time overview of the entire organization:

- **Document count** — total files in the knowledge base
- **User count** — all registered staff
- **Active users** — currently online (tracked via `is_online` flag updated on login/logout)
- **Pending approvals** — documents submitted but not yet reviewed by admin
- **Compliance score** — percentage of compliance records marked as compliant, rendered as an animated SVG ring
- **Recent activity feed** — live audit log showing last 8 actions (logins, uploads, approvals)
- **Quick action buttons** — shortcuts to upload, chat, add users
- **Recent documents list** — last 5 uploads with status badges

---

### 2. Messages (Real-Time Internal Communication)
A full-featured internal communication system modelled after WhatsApp/Slack:

**Direct Messages (DM)**
- Every employee appears in the People list with their department, role, and online indicator
- Clicking any user opens a private 1-on-1 conversation
- A dedicated DM channel (`dm_{userA_id}_{userB_id}`) is silently created per pair
- Messages are private — only the two participants can read them

**Channels (Group Chat)**
- Channels tab shows channels you belong to and channels you can browse and join
- When creating a channel, select one or more departments — all users in those departments are auto-added
- Channel creator and admins can edit the channel name, description, and departments at any time
- Changing departments automatically updates membership

**Message Features**
- **File sharing** — share PDF, DOCX, XLSX, CSV, TXT, PNG, JPG, GIF, WebP, MP4, ZIP
- Images render as inline thumbnails with click-to-enlarge lightbox
- Non-image files show as download cards with filetype icons
- **Reply to message** — hover any message and click reply; a quote preview is embedded in your response
- **Delete message** — hover and delete your own messages (admins can delete any)
- **Typing indicators** — animated dots appear when someone is typing
- **Auto-reconnect** — if the WebSocket drops, it reconnects automatically after 3 seconds with keep-alive pings every 25 seconds
- **WS status indicator** — Connected / Connecting / Disconnected badge in the chat header

**AI Knowledge Extraction**
- Every message sent in any channel is silently analysed by the AI
- If the message contains valuable business knowledge (sales experiences, customer insights, processes), it is extracted and stored in the knowledge base
- This happens asynchronously — users never notice any delay

---

### 3. Ask BOSS (AI Chat Assistant)
A Retrieval-Augmented Generation (RAG) chat interface connected to your entire company knowledge base:

- **RAG pipeline** — before answering, the AI retrieves the most relevant knowledge chunks from the database and uses them as context
- **Streaming responses** — answers are streamed token-by-token using Server-Sent Events (SSE) for a real-time typing effect
- **Persistent history** — all conversations are saved; previous sessions are listed in the sidebar and can be resumed at any time
- **Role-aware access** — super admins see all knowledge; staff only see `all_staff` level content; confidential documents are only surfaced for executives
- **Offline capable** — the AI runs entirely on your machine via Ollama (no internet required)
- **Suggestion chips** — quick-start prompts help new users explore common questions
- **AI status indicator** — shows Online/Offline based on Ollama availability

---

### 4. Knowledge Base
The organisation's accumulated intelligence, automatically built over time:

- **Auto-populated** — chunks are created whenever a document is approved or the AI extracts knowledge from a chat message
- **Three source types:** `document`, `message`, `manual`
- **Searchable** — full-text search across all knowledge chunks
- **Department filter** — filter knowledge by department
- **AI summaries** — each chunk shows an AI-generated 1-2 sentence summary
- **Statistics panel** — total chunks, from documents, from messages, active departments

---

### 5. Documents
The company document repository with a structured approval workflow:

**Upload flow:**
1. Staff member fills in title, description, department, access level and optionally attaches a file
2. Document enters `pending` status
3. Admin/super_admin approves or rejects
4. On approval, text is extracted, chunked and added to the knowledge base
5. Compliance requirements are auto-detected and added to the compliance register

**File type support:** PDF, DOCX, DOC, CSV, TXT

**Access levels:**
- `all_staff` — visible to all employees
- `restricted` — visible to staff level and above
- `confidential` — visible to admins and executives only

**Document statuses:** Draft → Pending → Approved / Rejected

---

### 6. Users
Team member management for administrators:

- Add new users with name, email, department, role, and temporary password
- View all users with their role, department, onboarding status, and online presence
- Activate / deactivate accounts
- First registered user is automatically assigned Super Admin role
- New employees are automatically enrolled in the onboarding flow on creation

**Role hierarchy:**

| Role | Key Permissions |
|---|---|
| `super_admin` | Full system access, all documents, all users, all settings |
| `admin` | Approve/reject documents, manage users, view all content |
| `manager` | View restricted docs, oversee team onboarding progress |
| `staff` | Chat, ask BOSS, view all_staff documents, upload docs |
| `new_employee` | Onboarding steps only, limited system access |

---

### 7. Onboarding Setup
Structured guided onboarding for new employees:

- **Admin creates steps** — title, description, order, required/optional flag
- **Progress tracking** — admins see each new employee's progress as a percentage bar
- **Self-service completion** — employees mark steps complete themselves as they go
- **Auto-graduation** — once all required steps are completed, `onboarding_complete` is set to `true` and the user's role access expands
- Steps can be linked to specific documents (e.g. "Read the company policy" links directly to the policy document)

---

### 8. Compliance
Automated regulatory monitoring powered by AI:

- **Auto-extraction** — whenever a document is approved, the AI scans it for regulatory and compliance requirements
- **Compliance register** — each extracted requirement is logged with regulation type, risk level (low/medium/high/critical), and current status
- **Status tracking** — each record can be marked as: `identified`, `compliant`, `non_compliant`, or `pending`
- **Compliance score** — the overall score (shown on dashboard) is the percentage of records marked compliant
- **Risk distribution chart** — breakdown of critical/high/medium/low items
- **Manual updates** — managers and admins can update status and add notes to any compliance record

---

### 9. Risk Management
A structured risk register for identifying and tracking business risks:

- **Risk matrix scoring** — each risk is scored by `likelihood (1–5) × impact (1–5)` giving a score of 1–25
- **Automatic risk classification:**
  - Score ≥ 15 → Critical (red)
  - Score 8–14 → High (yellow)
  - Score 4–7 → Medium (blue)
  - Score < 4 → Low (green)
- **Risk fields:** title, description, category, likelihood, impact, mitigation plan, owner, status
- **Status tracking:** open → mitigated → closed
- **Visual likelihood/impact dots** — 5-dot indicators for quick visual scanning

---

### 10. Audit Logs
A tamper-visible system-wide activity trail:

- Every significant action is logged: logins, document creation, approvals, rejections, user creation, setting changes
- Each log entry records: timestamp, user, action, resource type, resource ID, details, and IP address
- Visible only to super_admin and admin roles
- Last 100 events displayed in reverse-chronological order
- Color-coded action badges (green for logins, blue for creates, purple for approvals, red for deletes)

---

### 11. Settings
Profile and system preferences per user:

- **Profile update** — change name and department
- **Password change** — current password required; new password updated with bcrypt
- **System info panel** — version, AI model, backend stack, developer info

---

## Full Tech Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3.11+ |
| **Web Framework** | FastAPI |
| **ORM** | SQLAlchemy 2.0 (async) |
| **Database** | PostgreSQL (via asyncpg) |
| **Real-time** | WebSockets (native FastAPI) |
| **AI Engine** | Ollama (local LLM, no internet required) |
| **AI Model** | codellama:7b-instruct-q4_K_M |
| **File Parsing** | PyPDF2 · python-docx · pandas |
| **Templates** | Jinja2 |
| **Frontend** | Vanilla JS · CSS variables · SSE |
| **Auth** | JWT (python-jose) · bcrypt · httpOnly cookies |
| **Fonts** | Syne · DM Sans · JetBrains Mono |

---

## Database Schema (15 Tables)

```
users                    channels              messages
──────────────────       ─────────────────     ─────────────────────
id                       id                    id
full_name                name                  channel_id → channels
email (unique)           description           sender_id → users
hashed_password          channel_type          content
department               department            message_type
role (enum)              created_by → users    file_url
is_active                created_at            reply_to_id → messages
is_online                                      is_ai_extracted
avatar_color             channel_members       created_at
onboarding_complete      ───────────────
created_at               id
                         channel_id → channels
documents                user_id → users
──────────────────────
id                       knowledge_chunks
title                    ────────────────────
content                  id
description              document_id → documents
department               source_type
access_level (enum)      content
status (enum)            summary
author_id → users        keywords (JSON)
approved_by → users      department
file_path                created_at
file_type
is_compliance            ai_conversations      ai_messages
compliance_score         ────────────────      ───────────────
tags (JSON)              id                    id
created_at               user_id → users       conversation_id
                         session_id            role
compliance_records       created_at            content
──────────────────────                         sources (JSON)
id                       onboarding_steps      created_at
document_id → documents  ─────────────────
regulation_type          id                    onboarding_progress
requirement              title                 ────────────────────
status                   description           id
risk_level               document_id           user_id → users
notes                    step_order            step_id → onboarding_steps
created_at               is_required           completed
                         created_at            completed_at
risk_items
──────────────────────   audit_logs            app_settings
id                       ──────────────────    ──────────────────
title                    id                    id
description              user_id → users       key (unique)
category                 action                value
likelihood               resource_type         description
impact                   resource_id           updated_at
risk_score               details (JSON)
status                   ip_address
owner_id → users         created_at
mitigation_plan
created_at
```

---

## Quick Setup

### Prerequisites

```bash
# Python 3.11+
python --version

# PostgreSQL
# Windows: download from https://postgresql.org/download/windows
# Ubuntu:  sudo apt install postgresql
# macOS:   brew install postgresql

# Ollama (local AI — runs offline)
# Windows/macOS: https://ollama.ai/download
# Linux: curl -fsSL https://ollama.ai/install.sh | sh
```

### 1. Database Setup

Open pgAdmin or psql and run:

```sql
CREATE DATABASE boss_system;
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:
```env
DATABASE_URL=
SECRET_KEY=your-minimum-32-character-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=codellama:7b-instruct-q4_K_M
UPLOAD_DIR=uploads
MAX_FILE_SIZE_MB=50
```

### 3. Install Python Dependencies

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 4. Pull AI Model

```bash
ollama pull codellama:7b-instruct-q4_K_M
```

> ~4GB download. Lighter alternatives:
> - `ollama pull llama3.2:3b` (~2GB, faster)
> - `ollama pull mistral:7b-instruct-q4_K_M` (~4GB, excellent quality)

### 5. Start the Server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000** in your browser.

### 6. First Login

1. Go to **http://localhost:8000/auth/register**
2. Register your first account — it automatically becomes **Super Admin**
3. Log in and start configuring your organisation

---

## File Upload Limits & Supported Types

| Category | Formats | Feature |
|---|---|---|
| Documents | PDF, DOCX, DOC, CSV, TXT | Knowledge base extraction, compliance detection |
| Images | PNG, JPG, JPEG, GIF, WebP | Inline preview + lightbox in messages |
| Office | XLSX | Shareable in messages (download card) |
| Video | MP4 | Shareable in messages (download card) |
| Archives | ZIP | Shareable in messages (download card) |

Max file size: configurable via `MAX_FILE_SIZE_MB` in `.env` (default: 50MB)

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

**Nginx reverse proxy (required for WebSockets):**

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /uploads/ {
        alias /path/to/boss_system/uploads/;
    }
}
```

**Production checklist:**
- [ ] Change `SECRET_KEY` to a cryptographically random string
- [ ] Change PostgreSQL password
- [ ] Enable HTTPS (Let's Encrypt / Certbot)
- [ ] Set `httponly=True` and `secure=True` on cookies in `auth.py`
- [ ] Configure firewall — expose only ports 80 and 443
- [ ] Set up PostgreSQL backups (daily minimum)
- [ ] Use environment variables, not `.env` file in production

---

## Project Structure

```
boss_system/
├── main.py                         # FastAPI app — routes, lifespan, static files
├── requirements.txt                # Python dependencies (no version pins)
├── .env.example                    # Environment variable template
├── setup_db.sql                    # PostgreSQL database creation script
├── start.sh                        # One-click startup script
├── README.md                       # This file
├── uploads/                        # Auto-created — stores all uploaded files
│   ├── documents/                  # Document uploads (PDF, DOCX, CSV)
│   └── messages/                   # File attachments shared in chat
└── app/
    ├── __init__.py
    ├── config.py                   # Pydantic settings loaded from .env
    ├── database.py                 # Async SQLAlchemy engine + session factory
    ├── models.py                   # All 15 SQLAlchemy ORM models
    ├── auth.py                     # bcrypt hashing, JWT creation, dependencies
    ├── routers/
    │   ├── __init__.py
    │   ├── auth.py                 # /auth/* — login, register, logout, ws-token
    │   ├── business_ops.py         # /Tasks/ -Meetings schedules
    │   ├── dashboard.py            # /dashboard — stats, activity feed
    │   ├── messages.py             # /messages/* — chat, WebSocket, file upload, delete
    │   ├── ask_boss.py             # /ask-boss/* — AI chat, SSE streaming, sessions
    │   ├── documents.py            # /documents/* — CRUD, upload, approve/reject
    │   └── admin.py                # /users, /onboarding, /compliance, /risk, /settings
    ├── services/
    │   ├── __init__.py
    │   ├── ai_service.py           # Ollama client, RAG, knowledge/compliance extraction
    │   ├── document_service.py     # PDF/DOCX/CSV text extraction + text chunking
    │   └── websocket_manager.py    # Multi-channel WebSocket connection manager
    ├── templates/
    │   ├── base.html               # Master layout — sidebar, topbar, toast, modals
    │   ├── auth/
    │   │   ├── login.html
    │   │   └── register.html
    │   ├── dashboard/index.html
    │   ├── messages/index.html     # Full-featured chat UI
    │   ├── ask_boss/index.html     # Streaming AI chat
    │   ├── knowledge/index.html
    │   ├── documents/
    │   │   ├── index.html
    │   │   └── new.html
    │   ├── users/index.html
    │   ├── onboarding/index.html
    │   ├── compliance/index.html
    │   ├── risk/index.html
    │   ├── audit/index.html
    │   ├── settings/index.html
    │   └── errors/
    │       ├── 403.html
    │       └── 404.html
    └── static/
        ├── css/custom.css
        └── js/app.js
```

---

## Customization

| What | Where |
|---|---|
| Change AI model | `OLLAMA_MODEL` in `.env` |
| Add departments | Department lists in `messages.py` and templates |
| Brand name / colors | CSS variables in `base.html` (`:root` block) |
| Max upload size | `MAX_FILE_SIZE_MB` in `.env` |
| Session duration | `ACCESS_TOKEN_EXPIRE_MINUTES` in `.env` |
| Add knowledge manually | Knowledge Base page → or directly via the Documents upload |
| Allowed file types in chat | `ALLOWED_EXTENSIONS` set in `messages.py` |

---

*Built with ❤️ by **MindSync AI Consults** · BOSS System v1.0*