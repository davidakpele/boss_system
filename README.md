# 🚀 BOSS — AI Business Operating System

**Run your entire company from one platform.**

Chat. AI. HR. Accounting. Inventory. Compliance.
All powered by **real-time systems + local AI (offline)**.

---

## ⚡ Why BOSS?

Most companies use **10+ disconnected tools**.

The software replaces them with **one intelligent system**:

* 💬 Messaging (Slack-style)
* 🧠 AI Assistant (RAG-powered)
* 📄 Knowledge Base
* 👥 HR & Recruitment
* 💰 Accounting
* 📦 Inventory
* ⚖️ Compliance & Risk
* 📊 Analytics
* 📱 WhatsApp Automation

> **Think:** Slack + Notion + SAP + ChatGPT — in one system.

---

## 🧠 The Story Behind BOSS

Goodness gracious… building a full business operating system is no joke.

When I started building **BOSS System**, it was just an idea — a way to unify messaging, AI, HR, accounting, inventory, and operations into one intelligent platform.

But as the system grew, so did the complexity.

Today, BOSS is evolving into a full AI-powered corporate operating system — with real-time communication, knowledge intelligence (RAG), compliance tracking, AI recruitment, WhatsApp automation, and much more.

There are bugs to fix. Features to refine. Big ideas to bring to life.

Like many open source projects, the biggest challenge isn’t ideas — it’s time and consistency.

---

## 🔥 Why Developers Are Starring This

* 🧠 Chat with your company knowledge (RAG)
* 🤖 AI auto-detects compliance & risks
* 💰 Record expenses via natural language
* 📱 WhatsApp becomes a business assistant
* 👔 AI screens job applicants automatically
* ⚡ Fully offline AI (Ollama)

---

## 🧠 Core Architecture

* **Backend:** FastAPI (async)
* **Database:** PostgreSQL
* **Realtime:** WebSockets + SSE
* **AI Engine:** Ollama (local LLM)
* **Embeddings:** sentence-transformers
* **Frontend:** Vanilla JS + PWA

---

## 📸 Screenshots

![Login](public/assets/images/login.png)

### Dashboard

![Dashboard](public/assets/images/1.png)

### Messaging

![Messages](public/assets/images/message.png)

### Ask BOSS (AI)

![AI](public/assets/images/ask.png)

### Onboarding

![Onboarding](public/assets/images/onboarding.png)

### WhatsApp Integration

![WhatsApp](public/assets/images/whatsapp.png)

---

## 🧩 Core Modules

### 💬 Messaging

* Real-time chat (WebSockets)
* Channels + DMs
* File sharing + voice notes
* Reactions, threads, mentions
* Read receipts

---

### 🧠 Ask BOSS (AI)

* RAG over company knowledge
* Streaming responses (SSE)
* Citation-based answers
* Role-based access
* Meeting summaries

---

### 📄 Knowledge Base

* Auto-built from docs + chats
* Semantic search (vector)
* AI summaries per chunk

---

### 👥 HR & AI Recruitment

* CV parsing + scoring
* AI recommendations
* Hiring pipeline
* Auto email generation

---

### 💰 Accounting

* Natural language input

  > “I paid 15000 for transport”
* Auto classification
* Full history + export

---

### 📦 Inventory

* Stock tracking
* Movement logs
* Low stock alerts
* SKU auto-generation

---

### ⚖️ Compliance & Risk

* AI detection from documents
* Risk scoring system
* Compliance tracking dashboard

---

### 📊 Analytics

* Activity tracking
* Knowledge growth
* User engagement
* PDF reports (AI-generated)

---

### 📱 WhatsApp Integration

* AI auto-replies
* Transaction recording
* Knowledge queries
* CRM + contact tracking

---

## 🏗️ System Design

```
Frontend (PWA)
    ↓
FastAPI Backend
    ↓
AI Layer (RAG + Ollama)
    ↓
PostgreSQL (35+ tables)
```

---

## ⚙️ Quick Setup (Manual)

### 1. Create DB

```sql
CREATE DATABASE boss_system;
```

---

### 2. Configure `.env`

```env
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/boss_system
SECRET_KEY=your_secret_key

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=codellama:7b-instruct-q4_K_M
```

---

### 3. Install

```bash
python -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

---

### 4. Run

```bash
uvicorn main:app --reload
```

---

## 🧠 AI Stack

* Ollama (local LLM)
* RAG pipeline
* Sentence embeddings (384-dim)
* Semantic retrieval
* Context-aware generation

---

## 🔐 Security

* JWT Authentication
* OAuth (Google + Microsoft)
* IP Allowlist
* 2FA (TOTP)
* Audit logs
* Field-level encryption

---

## 📦 Features Overview

| Area      | Features                        |
| --------- | ------------------------------- |
| Messaging | Chat, threads, reactions, voice |
| AI        | RAG, summaries, automation      |
| HR        | Recruitment pipeline            |
| Finance   | Accounting + reports            |
| Ops       | Tasks, meetings                 |
| Data      | Knowledge base                  |
| Security  | SSO, IP control                 |
| Mobile    | PWA + Push                      |

---

## 🧪 Use Cases

* Startups replacing SaaS stack
* Internal company OS
* AI-powered operations
* Knowledge-driven teams
* Customer support via WhatsApp

---

## 🤝 Contributing

We welcome contributions.

### Good First Issues:

* UI improvements
* AI prompt tuning
* Performance optimization
* New integrations

---

## ⭐ Support

If this project helps you:

* ⭐ Star the repo
* 🍴 Fork it
* 💬 Share it

---

## 💰 Sponsor

👉 https://github.com/sponsors/davidakpele

---

## 🧭 Roadmap

* Mobile app (React Native)
* Multi-tenant SaaS mode
* Plugin system
* API marketplace
* Advanced AI agents

---

## 👨‍💻 Author

**David Akpele**

---

## 📄 Full Documentation

👉 [View DETAILS](./FULLDETAILS.md)

---

> Built with ❤️ by **David Akpele** · BOSS System v2.0
