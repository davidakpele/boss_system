# BOSS System — Business Operating System

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

![Dashboard Preview](public/assets/images/1.png)

### 2. Messages (Real-Time Communication)
A full-featured internal communication system modelled after WhatsApp:

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
![Message Preview](public/assets/images/2.png)

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
![Ask Boss Preview](public/assets/images/3.png)
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

### 12. Analytics & Reporting

A dedicated intelligence layer that turns system data into actionable insights — no external BI tools required.

#### Analytics Dashboard (`/analytics`)

Five KPI cards give an at-a-glance snapshot: total documents, users, knowledge chunks, messages, and current compliance score. A **period selector** (7 / 30 / 90 days) refreshes all time-series charts live without a page reload.

**Charts included:**
- **Document uploads over time** — line chart with daily bars for the selected period
- **Messages over time** — same period and style
- **Compliance score trend** — always spans 12 months, showing score progression over time
- **Knowledge base growth** — cumulative chunk count overlaid with daily additions
- **Knowledge by department** — doughnut/pie breakdown of which teams are contributing most
- **Login activity heatmap** — 12-week GitHub-style grid; colour intensity maps to login count per day
- **Most active users** — horizontal bar chart of the top 10 users by message count (30-day window)

All charts are powered by **Chart.js** loaded from CDN — no npm build step required.

#### User Activity Report (`/analytics/user-activity`)

A full tabular breakdown of every active user showing: messages sent, documents uploaded, AI queries made, login count, composite activity score, and last-seen date.

- **Sortable columns** — click any header to toggle ascending/descending order
- **Live search** — filter instantly by name, email, or department
- **Summary cards** — aggregate totals across all users shown at the top
- **Period selector** — 7 / 30 / 90 / 365 days
- **CSV export** — downloads the complete dataset as a spreadsheet
- **Online indicator** — green dot marks currently active users

#### Reports (`/analytics/reports`)

On-demand PDF reports generated server-side using ReportLab with an AI summary step powered by Ollama:

| Report | What it contains |
|---|---|
| **Department Knowledge PDF** | Pick department + period (1 week → 1 quarter). AI summarises knowledge added, then PDF includes: stats table, AI bullet points, new documents list, compliance records, knowledge chunk previews |
| **User Activity** | Links through to the interactive `/analytics/user-activity` table with CSV export |
| **Compliance Summary PDF** | Same PDF engine scoped to compliance records for the selected period |

Reports are streamed directly to the browser as a download. Generation takes 15–30 seconds due to the AI summary step — a progress message is displayed during the wait.

---

### 13. Business Command Centre (BCC)

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

Here's the updated WhatsApp section for your README.md. Add this under the **"🔥 NEW: Messaging, AI & Security Enhancements (v2.1)"** section or as its own subsection:

---

### 14. WhatsApp Business Integration (v2.2)

BOSS now connects directly to **WhatsApp Business API** — turning your business phone number into an AI-powered customer and employee engagement channel.

#### Key Features

**🤖 AI-Powered WhatsApp Assistant**
- Customers and employees can message your WhatsApp number and get intelligent responses powered by Ollama LLM
- Automatic intent detection: `accounting` · `inventory` · `hr` · `greeting` · `query`
- RAG-powered answers using your company knowledge base (documents, policies, FAQs)
- Maintains conversation history per contact (last 10 turns)

**💰 Natural Language Accounting**
- Users can record transactions by simply messaging: *"I paid $15,000 for transportation today"*
- AI automatically parses: type (income/expense), amount, currency, category, description
- Returns a friendly confirmation: *"Got it! Recorded your expense of $15,000."*
- Transaction auto-saved to Accounting module

**📦 Context-Aware Responses**
- Intent routing ensures accounting messages go to finance AI, inventory queries check stock levels
- Knowledge base retrieval surfaces relevant company information
- WhatsApp-optimised responses: short, emoji-warm, with *bold markdown* for emphasis

**🔐 Contact Management Dashboard**
- Full CRM for WhatsApp contacts at `/whatsapp`
- View all contacts, message history, block/unblock, add CRM notes
- Real-time stats: total contacts, messages, AI-handled rate, today's volume
- Token health check — verify your WhatsApp API token is valid
- Live token updates from UI without server restart

**📊 Automatic Record Keeping**
- Every inbound/outbound message saved to database
- Message direction: `inbound` / `outbound`
- Status tracking: `received` · `sent` · `failed` · `read`
- AI handling flag and detected intent stored per message

#### How It Works

```
  WhatsApp User
       │
       ▼  (sends message)
  Meta WhatsApp API
       │
       ▼  (POST to /whatsapp/webhook)
  ┌────────────────────────────────────────────────────────┐
  │              BOSS Webhook Handler                       │
  │  • Verifies signature and token                         │
  │  • Extracts wa_id, message content                      │
  │  • Saves inbound message                                │
  │  • Marks as read (blue ticks)                           │
  └────────────────────┬───────────────────────────────────┘
                       ▼
  ┌────────────────────────────────────────────────────────┐
  │              Intent Detection                           │
  │  greeting → accounting → inventory → hr → query         │
  └────────────────────┬───────────────────────────────────┘
                       ▼
  ┌────────────────────────────────────────────────────────┐
  │           AI Response Engine (Ollama)                   │
  │  • Retrieves relevant knowledge chunks (RAG)            │
  │  • Parses transactions if accounting intent             │
  │  • Generates WhatsApp-optimised reply                   │
  └────────────────────┬───────────────────────────────────┘
                       ▼
  ┌────────────────────────────────────────────────────────┐
  │           Response Actions                              │
  │  • Auto-save accounting record (if transaction)         │
  │  • Update conversation history                          │
  │  • Send reply via WhatsApp API                          │
  │  • Save outbound message                                │
  └────────────────────────────────────────────────────────┘
```

#### Configuration

Add to your `.env`:

```env
# WhatsApp Business API
WHATSAPP_ENABLED=true
WHATSAPP_API_VERSION=v18.0
WHATSAPP_PHONE_NUMBER_ID=23490xxxxxxxx
WHATSAPP_ACCESS_TOKEN=EAA... (long-lived token)
WHATSAPP_VERIFY_TOKEN=your_webhook_verify_token_here
```

#### Setup Instructions

1. **Create Meta App** at [developers.facebook.com](https://developers.facebook.com)
2. **Add WhatsApp product** to your app
3. **Get your Phone Number ID** from the WhatsApp API dashboard
4. **Generate access token** (business integration → long-lived token)
5. **Configure webhook** in Meta dashboard:
   - Callback URL: `https://yourdomain.com/whatsapp/webhook`
   - Verify token: (the value you set in `WHATSAPP_VERIFY_TOKEN`)
   - Subscribe to: `messages`, `message_deliveries`, `message_reads`
6. **Add your business number** (can be a test number from Meta)

#### API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/whatsapp/webhook` | GET | Meta webhook verification |
| `/whatsapp/webhook` | POST | Receive inbound messages |
| `/whatsapp/send` | POST | Manual send from dashboard |
| `/whatsapp` | GET | Dashboard page (HTML) |
| `/whatsapp/contacts` | GET | All contacts JSON |
| `/whatsapp/contacts/{id}/history` | GET | Contact + message history |
| `/whatsapp/contacts/{id}/block` | POST | Block/unblock contact |
| `/whatsapp/contacts/{id}/note` | POST | Add CRM note |
| `/whatsapp/stats` | GET | JSON stats for dashboard |
| `/whatsapp/token-status` | GET | Check token validity |
| `/whatsapp/update-token` | POST | Update token at runtime |

#### Example API Response

When sending a message via `/whatsapp/send`:

```json
{
    "messaging_product": "whatsapp",
    "contacts": [
        {
            "input": "23490xxxxxxxx",
            "wa_id": "23490xxxxxxxx"
        }
    ],
    "messages": [
        {
            "id": "wamid.HBgNMjM0OTAxOTM4NDQ5NhUCABEYEjI2RTcxQTkyMEJFMkFFMDIxMQA="
        }
    ]
}
```

#### Security & Best Practices

- **Block contacts** — prevent spam or unwanted messages
- **Rate limiting** — handles Meta's retry policies (always returns 200 immediately)
- **Async processing** — webhook doesn't block on AI generation
- **Token rotation** — update tokens from UI without restarting
- **Message context** — reply threading supported via `context.message_id`

#### Database Tables Added

```
whatsapp_contacts     — wa_id, phone, name, total_messages, is_blocked, notes
whatsapp_messages     — direction, content, status, intent, ai_handled, ai_response
whatsapp_sessions     — per-contact conversation history (JSON)
```

---

> *This feature transforms WhatsApp from a simple messaging app into a business operations channel — enabling transaction recording, customer support, and employee self-service directly from your business phone number.*

### 15. Security

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

### 15. Progressive Web App (PWA)
- `manifest.json` with full icon set, shortcuts, and theme colors
- Service worker with network-first for pages, cache-first for static assets
- Offline fallback page when network unavailable
- Install prompt via `beforeinstallprompt` — **Install App** button in Settings
- Runs in standalone mode (no browser chrome) once installed on phone/desktop

---

### 16. Push Notifications
- Web Push API with VAPID keys — no third-party service required
- Notifications delivered even when the tab is closed
- Per-device subscription — one user can have multiple devices subscribed
- Notification includes title, body, icon, click-through URL, and vibrate pattern
- **Enable Notifications** button in Settings; test via **Send Test**
- Used internally by the messages router for new message notifications

---

### 17. Internal Notifications (In-App)
- Bell icon in topbar with real-time unread badge
- Dropdown panel with click-to-navigate, mark-as-read per item
- Mark all read button
- Polls every 30 seconds; also triggered immediately by server events
- Types: `info` · `success` · `warning` · `error` · `message` · `hr`
- Fires web push simultaneously when a notification is created

## 18. Communication

| # | Feature | Status |
|---|---------|--------|
| 1 | **Email Integration (SMTP)** | ✅ Built |
| 2 | **Message Reactions** | ✅ Built |
| 3 | **Message Search** | ✅ Built |
| 4 | **Voice Notes** | ✅ Built |
| 5 | **Read Receipts** | ✅ Built |
| 6 | **Message Threads** | ✅ Built |
| 7 | **@Mentions** | ✅ Built |
| 8 | **Scheduled Messages** | ✅ Built |
| 9 | **Message Pinning** | ✅ Built |
| 10 | **Message Edit** | ✅ Built |
| 11 | **Group Video/Audio Calls** | ✅ Built |
| 12 | **Screen Sharing** | ✅ Built |

### Feature Details

**1. Email Integration (SMTP)**
Full SMTP email service at `app/services/email_service.py`. Branded HTML email shell with BOSS header injected on every outbound email. Ready-made senders for: HR emails (interview invites, offer letters, rejection), @mention notifications, daily digest for managers, and system alerts with severity levels (info / warning / critical). Works with Gmail, Office 365, Mailgun, Sendinblue. Configured via `.env`:
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM_NAME=BOSS System
```

**2. Message Reactions**
Emoji picker opens anchored to the reaction `+` button or via the ⋯ message menu. Single global picker instance repositioned per message — no DOM clutter. Reactions aggregate by emoji with a count badge. Clicking your own reaction toggles it off. All changes broadcast via WebSocket so every participant sees updates in real time without a page refresh. Stored in `message_reactions` table.

**3. Message Search**
Search bar in the chat header (magnifying glass icon). Debounced 350ms — queries `GET /messages/search?channel_id=&q=` as you type. Results appear in a panel above the input with sender name, timestamp, and highlighted match text. Clicking a result scrolls the message list to that exact message and highlights it for 2 seconds. Supports ILIKE partial matching.

**4. Voice Notes**
Click the microphone button → browser requests mic permission → records via `MediaRecorder` API. Animated recording bar shows elapsed time (max 2 minutes). Send or cancel. Audio stored as `.webm` / `.ogg` / `.mp4` depending on browser support, served from `/static/uploads/voice/`. Rendered inline with a waveform visualisation (SVG bars), play/pause button, and a live time counter. Stored in `messages` table with `message_type="voice"` and `voice_duration`.

**5. Read Receipts**
Every message sent triggers a `read` WebSocket frame from recipients when they scroll to or view the message. Each receipt stored in `message_read_receipts`. The sender sees small avatar thumbnails beneath their sent messages showing who has read it. Handled entirely via WebSocket — no HTTP polling.

**6. Message Threads**
Click ⋯ → Thread on any message. A slide-in side panel shows the parent message and all replies in a separate thread stream. Thread reply count badge updates in real time as new replies arrive. Thread replies are stored with `is_thread_reply=True` and `thread_id` referencing the parent message. Thread and main channel streams are fully independent.

**7. @Mentions**
Type `@` in the message input to trigger an autocomplete dropdown showing matching users. Select with keyboard (↑↓ Enter) or click. Mention stored in `mentions` table. Mentioned user receives: an instant WebSocket push notification, a badge count on the `@` button in the left panel, and a dedicated Mentions panel listing all recent mentions with jump-to links. Batch mark-all-read on panel open.

**8. Scheduled Messages**
Clock icon in the chat header → type message → pick date/time → Schedule. Stored in `scheduled_messages` table. A background asyncio worker in `main.py` polls every 30 seconds, delivers due messages as real WebSocket broadcasts (indistinguishable from live messages), marks them sent, and stores the delivery time. Future-date validation prevents scheduling in the past.

**9. Message Pinning**
Click ⋯ → Pin on any message. Stored in `pinned_messages` table. The 📌 button in the chat header shows a count badge of pinned messages. Clicking opens a panel listing all pins with sender avatar, content preview, and a "View" button that scrolls to the original message. Pin/unpin events broadcast via WebSocket so all participants see the change instantly.

**10. Message Edit**
Click ⋯ → Edit on your own messages (admins cannot edit others'). The current message text fills the input area and an "Editing" indicator bar appears. Submitting sends `POST /messages/{id}/edit`. The edit is broadcast via WebSocket — all participants see the updated text with an "(edited)" label appended. Full edit history stored in `message_edits` table with old content, new content, editor, and timestamp. Accessible via `GET /messages/{id}/edit-history`.

**11. Group Video/Audio Calls**
📞 / 📹 buttons in the chat header. Uses WebRTC peer-to-peer — audio/video travels directly between browsers, only call signaling (offer/answer/ICE) goes through the BOSS WebSocket. Caller sees a "Calling…" modal. All other channel members get an incoming call banner (bottom-right slide-up) with the caller's name and Accept/Decline buttons. WebSocket signaling handles: `call_start`, `call_offer`, `call_answer`, `ice_candidate`, `call_reject`, `call_end`. STUN servers: `stun.l.google.com:19302` (free, no account needed).

**12. Screen Sharing**
Available during an active call via the 🖥️ button. Uses `getDisplayMedia()` — user picks a window, tab, or entire screen. Replaces the video track in all active peer connections so remote participants see the screen immediately. The local preview updates to show the shared screen. One click restores the camera. Button turns red while sharing. The `onended` event (user clicks "Stop sharing" in the browser bar) also triggers cleanup automatically.

---

## 19. Platform & Infrastructure

| # | Feature | Status |
|---|---------|--------|
| 76 | **Multi-Tenant Architecture** | ✅ Built |
| 77 | **White Labelling** | ✅ Built |
| 78 | **Automated Database Backups** | ✅ Built |
| 79 | **Health Check Dashboard** | ✅ Built |
| 80 | **Email Digest** | ✅ Built |
| 81 | **Changelog & Version Notes** | ✅ Built |
| 82 | **Dark / Light Mode Toggle** | ✅ Built |
| 83 | **Keyboard Shortcuts** | ✅ Built |
| 84 | **Global Search** | ✅ Built |
| 85 | **Drag-and-Drop File Uploads** | ✅ Built |
| 86 | **Audit Trail Export** | ✅ Built |
| 87 | **Rate Limiting** | ✅ Built |

### Feature Details

**76. Multi-Tenant Architecture**
`Tenant` model with slug-based organisation identifiers, plan tiers (starter / pro / enterprise), user limits, and active/inactive toggle. Each tenant has isolated settings via `TenantSetting` key-value table. Super-admin dashboard at `/tenants` for creating, editing, and managing all organisations. Full CRUD: create with name + slug + plan + max users, toggle active status, edit all branding fields.

**77. White Labelling**
Per-tenant brand fields: `brand_name`, `brand_logo_url`, `brand_favicon`, `primary_color` (accent), `sidebar_color`, and `custom_css` injected on every page. Edit via Tenants dashboard → Edit Brand modal. Colour pickers for accent and sidebar. Custom CSS field allows arbitrary overrides. Changes take effect on next page load without server restart.

**78. Automated Database Backups**
`pg_dump | gzip` runs daily at 2am UTC via an asyncio background task started in the `lifespan` context. Manual trigger from the Health dashboard. Downloads available as `.sql.gz` via `GET /platform/backup/{id}/download`. All runs logged in `backup_logs` table with status, file size, duration, and error message. Auto-prunes files older than 30 days. Triggered-by field distinguishes `scheduler` vs `manual`.

**79. Health Check Dashboard**
Live dashboard at `/platform` refreshing every 10 seconds via `GET /platform/health`. Six metric cards: Database (connected + latency in ms), AI Engine (Ollama online/offline + model name), Disk (used / total GB with progress bar), Memory (used / total GB with progress bar), WebSockets (active connections), Uploads directory (total MB). Table row counts for every major model. Overall system status dot (green / red). Backup log panel alongside.

**80. Email Digest**
Daily digest sender at `email_service.send_daily_digest()`. Accepts a `stats` dict with labelled metric rows. Rendered as a clean HTML table with BOSS branding. Designed to be called from a scheduler (e.g., daily at 8am) passing counts for messages, tasks completed, new hires, accounting records, etc. Configurable per-manager delivery.

**81. Changelog & Version Notes**
In-app changelog at `/platform/changelog`. Super-admins publish versioned entries with type badge: 🟢 Feature / 🔵 Bug Fix / 🟡 Improvement / 🔴 Security. Each entry has version string, title, and markdown-style body (bullet lists, headings supported). Users see a `NEW` badge on unread entries. Read status tracked per-user in `changelog_reads`. Unread count available via `GET /platform/changelog/unread-count` for topbar badge.

**82. Dark / Light Mode Toggle**
Moon/sun toggle button in the topbar. Switches all CSS custom properties (`--bg`, `--text`, `--border`, etc.) instantly via JavaScript. Preference saved to `localStorage` and restored on every page load — no flash of wrong theme. Light mode uses white/zinc palette; dark mode uses a deep navy/slate palette. Both modes fully supported across all pages.

**83. Keyboard Shortcuts**
`G` + letter navigation (1.2 second window): `D` Dashboard, `M` Messages, `A` Ask BOSS, `T` Tasks, `B` Command Centre, `R` Analytics, `S` Settings, `P` System Health. `Ctrl+K` / `Cmd+K` opens Global Search overlay. `Esc` closes search or modals. `?` opens the shortcuts reference modal. All shortcuts disabled when typing in inputs/textareas. Implemented via `keydown` event listener on `document`.

**84. Global Search**
`Ctrl+K` / `Cmd+K` opens a full-screen overlay with a search input. Searches five collections simultaneously: Messages (content + sender), Documents (title + content), Users (name + email), Tasks (title + description), Knowledge chunks (content + summary). Results show type icon, title, subtitle, and colour-coded type label. Arrow keys navigate, Enter opens the result's page. Match text highlighted in yellow. Quick-nav shortcuts shown on first open. Debounced 250ms. Backend: `GET /search?q=`.

**85. Drag-and-Drop File Uploads**
Page-wide drop zone — drag any file anywhere on the browser window. A full-screen overlay with a cloud upload icon appears while dragging. On drop, files are routed by current page: Messages page → `handleFileSelect()` attaches to message input; Documents page → triggers the file input's change event. Works with multiple files. Visual feedback via the overlay disappearing on drop. Implemented as a document-level `dragenter` / `dragleave` / `drop` listener.

**86. Audit Trail Export**
`GET /platform/audit/export?format=csv&days=90` or `?format=pdf`. CSV exports all columns (timestamp, user, email, action, resource type, resource ID, IP address, details) for up to 10,000 rows — suitable for spreadsheet analysis and compliance submissions. PDF export uses ReportLab with a styled two-tone table, BOSS header, generation timestamp, and record count. PDF limited to 500 rows with a note to use CSV for full data. Both available from the Audit Logs page action buttons.

**87. Rate Limiting**
In-memory sliding window middleware at `app/middleware/rate_limiter.py`. No Redis dependency. Per-path limits: login (10/min), registration (5/min), WhatsApp send (30/min), AI endpoints (20/min), search (60/min). Violators blocked for 5 minutes. Every response includes `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Window` headers. Static files and health endpoints are exempt. Block duration and per-path limits configurable in `RATE_RULES` dict.
---

### 🧠 AI-Powered Intelligence (Expanded)

BOSS is no longer just AI-assisted — it's AI-driven across the entire system:

* **AI Writing Assistant**
  Improve, expand, rewrite, or translate messages inline before sending.

* **Document Q&A with Citations**
  Ask questions and receive answers with exact source references from your knowledge base.

* **Auto-Tagging Engine**
  AI automatically classifies and organizes documents and knowledge entries.

* **Sentiment Analysis**
  Detect team mood trends across conversations to identify risks early.

* **Meeting Intelligence**
  Automatically extract:

  * Action items
  * Decisions made
  * Key discussion points
    From meeting transcripts and channel history.

---

### 🔐 Security & Access Control (Enterprise Upgrade)

Advanced protection and compliance-ready infrastructure:

* **Two-Factor Authentication (2FA — TOTP)**
  Secure accounts with authenticator apps.

* **Session Management**
  View and revoke active sessions across devices.

* **Password Policy Enforcement**
  Enforce strong password rules (length, complexity, expiry).

* **Login Attempt Lockout**
  Automatically block brute-force attempts after repeated failures.

* **API Key Management**
  Generate, rotate, and revoke API keys securely.

* **Field-Level Encryption**
  Sensitive data is encrypted at rest (e.g., tokens, secrets).

* **Data Retention Policies**
  Define automatic cleanup rules for compliance and storage optimization.

---

## 🚀 Impact Summary

* ⚡ Faster communication (search, threads, voice)
* 🧠 Smarter workflows (AI everywhere)
* 🔐 Stronger security (enterprise compliance ready)
* 📈 Better team insights (sentiment + meeting intelligence)

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
| **PDF Generation** | ReportLab |
| **Templates** | Jinja2 |
| **Frontend** | Vanilla JS · CSS variables · SSE · HTML5 DnD |
| **Charts** | Chart.js (CDN) |
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
| Analytics chart period default | Period selector default value in `analytics.html` |

---

*Built with ❤️ by **David Akpele** · BOSS System v2.0*
