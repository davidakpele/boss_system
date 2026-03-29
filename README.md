# BOSS System — Business Operating System
**Developed by MindSync AI Consults**

A full-stack AI-powered corporate knowledge management and communication platform.

---

## Features

| Module | Description |
|---|---|
| **Dashboard** | Live stats — documents, users, active sessions, compliance score |
| **Messages** | Real-time WebSocket internal chat with AI knowledge extraction |
| **Ask BOSS** | Streaming RAG-powered AI assistant with persistent chat history |
| **Knowledge Base** | Auto-populated from documents & message conversations |
| **Documents** | Upload PDF, DOCX, CSV with approval workflow & access levels |
| **Users** | User management with roles and department assignment |
| **Onboarding** | Step-by-step new employee onboarding with progress tracking |
| **Compliance** | Auto-extracted regulatory requirements from documents |
| **Risk Management** | Risk register with likelihood × impact scoring |
| **Audit Logs** | Full system activity trail |
| **Settings** | Profile, password, system info |

---

## Tech Stack

- **Backend:** Python 3.11+ · FastAPI · SQLAlchemy (async) · WebSockets
- **Database:** MySQL 8+ (via aiomysql)
- **AI Engine:** Ollama local LLM (`codellama:7b-instruct-q4_K_M`)
- **File Support:** PDF (PyPDF2) · DOCX (python-docx) · CSV (pandas)
- **Frontend:** Jinja2 templates · Vanilla JS · WebSockets SSE
- **Auth:** JWT cookies · bcrypt · Role-based access

---

## Quick Setup

### 1. Prerequisites

```bash
# MySQL 8+
sudo apt install mysql-server   # Ubuntu
brew install mysql              # macOS

# Python 3.11+
python3 --version

# Ollama (local AI)
curl -fsSL https://ollama.ai/install.sh | sh
```

### 2. Database

```bash
mysql -u root -p < setup_db.sql
```

Or manually:
```sql
CREATE DATABASE boss_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'boss_user'@'localhost' IDENTIFIED BY 'boss_pass';
GRANT ALL PRIVILEGES ON boss_db.* TO 'boss_user'@'localhost';
FLUSH PRIVILEGES;
```

### 3. Environment

```bash
cp .env.example .env
# Edit .env with your settings
nano .env
```

Key settings in `.env`:
```
DATABASE_URL=mysql+aiomysql://boss_user:boss_pass@localhost:3306/boss_db
SECRET_KEY=your-very-secret-key-min-32-characters
OLLAMA_MODEL=codellama:7b-instruct-q4_K_M
```

### 4. Python Environment

```bash
python3 -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 5. Pull AI Model

```bash
ollama pull codellama:7b-instruct-q4_K_M
```

> This is ~4GB. Alternative lighter models:
> - `ollama pull mistral:7b-instruct-q4_K_M`
> - `ollama pull llama3.2:3b`

### 6. Start

```bash
# Easy start:
bash start.sh

# Manual:
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open: **http://localhost:8000**

---

## First Run

1. Go to **http://localhost:8000/auth/register**
2. Register — the **first account automatically becomes Super Admin**
3. Log in and explore the dashboard
4. Create channels in Messages, upload documents, ask BOSS AI

---

## Project Structure

```
boss_system/
├── main.py                    # FastAPI app entry point
├── requirements.txt
├── start.sh                   # One-click startup
├── setup_db.sql               # MySQL setup
├── .env.example               # Config template
├── uploads/                   # Uploaded files (auto-created)
└── app/
    ├── config.py              # Settings from .env
    ├── database.py            # Async SQLAlchemy + MySQL
    ├── models.py              # All 15 DB models
    ├── auth.py                # JWT + cookie auth
    ├── routers/
    │   ├── auth.py            # Login / register / logout
    │   ├── dashboard.py       # Dashboard stats
    │   ├── messages.py        # Chat + WebSocket
    │   ├── ask_boss.py        # AI chat (streaming SSE)
    │   ├── documents.py       # Document CRUD + approval
    │   └── admin.py           # Users, onboarding, compliance, risk, settings
    ├── services/
    │   ├── ai_service.py      # Ollama RAG + knowledge extraction
    │   ├── document_service.py # PDF/DOCX/CSV text extraction
    │   └── websocket_manager.py # Multi-channel WS manager
    ├── templates/             # Jinja2 HTML templates
    └── static/                # CSS / JS assets
```

---

## User Roles

| Role | Permissions |
|---|---|
| `super_admin` | Full access — all features, all documents |
| `admin` | Manage users, approve documents, view all |
| `manager` | View restricted docs, manage team onboarding |
| `staff` | Chat, ask BOSS, view all_staff documents |
| `new_employee` | Onboarding flow, limited access |

---

## How Knowledge Extraction Works

1. **Documents:** Uploaded files (PDF/DOCX/CSV) are text-extracted and chunked
2. **Messages:** Every chat message is analyzed by AI; valuable business knowledge is stored
3. **Ask BOSS:** Uses RAG — retrieves relevant chunks and sends them as context to the LLM
4. **Result:** New employees can ask questions and get answers based on accumulated company knowledge

---

## Production Deployment

```bash
# Use gunicorn for production
pip install gunicorn
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

# With nginx reverse proxy:
# proxy_pass http://127.0.0.1:8000;
# proxy_http_version 1.1;
# proxy_set_header Upgrade $http_upgrade;  # For WebSockets
# proxy_set_header Connection "upgrade";
```

**Important for production:**
- Change `SECRET_KEY` to a secure random string
- Change MySQL password
- Use HTTPS (required for secure cookies)
- Set `cookie.secure=True` in auth.py

---

## Customization

- **Change AI model:** Update `OLLAMA_MODEL` in `.env`
- **Add departments:** Edit department lists in templates
- **Branding:** Update logo/colors in `base.html` CSS variables
- **Max file size:** Update `MAX_FILE_SIZE_MB` in `.env`

---

*Built with ❤️ by MindSync AI Consults*
