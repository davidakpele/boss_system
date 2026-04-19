#!/bin/bash
# BOSS System — Startup Script
set -e

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   BOSS — Business Operating System       ║"
echo "║   MindSync AI Consults                   ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Check .env
if [ ! -f .env ]; then
  echo "⚙️  Creating .env from .env.example..."
  cp .env.example .env
  echo ".env created. Edit it with your DB credentials before running."
  echo ""
fi

# Check Python
if ! command -v python3 &> /dev/null; then
  echo "Python 3 not found. Install Python 3.11+."
  exit 1
fi

# Check virtual environment
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

echo "Installing dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt

# Check Ollama
echo ""
if command -v ollama &> /dev/null; then
  echo "Ollama found. Checking model..."
  if ollama list 2>/dev/null | grep -q "codellama:7b-instruct-q4_K_M"; then
    echo "Model codellama:7b-instruct-q4_K_M is ready."
  else
    echo "⬇Pulling model codellama:7b-instruct-q4_K_M (this may take a while)..."
    ollama pull codellama:7b-instruct-q4_K_M
  fi
else
  echo "Ollama not found. AI features will be unavailable."
  echo "   Install from: https://ollama.ai"
fi

echo ""
echo "Starting BOSS System..."
echo "   → http://localhost:8144"
echo ""

uvicorn main:app --host 0.0.0.0 --port 8144 --reload
