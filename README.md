# ⚡ EV Route Agent – WebApp

Vollständige WebApp mit **FastAPI Backend** + **HTML/JS Frontend**.  
Die 3 CrewAI-Agenten streamen ihren Fortschritt live ans Frontend via **Server-Sent Events (SSE)**.

## 🏗 Architektur

Used Api´s
Claude: https://platform.claude.com/claude-code

Google Maps: https://console.cloud.google.com/google/maps-apis/home?project=project-d6df3b93-6216-4f42-b39&hl=en

Opencharge: https://openchargemap.org/loginprovider/beginlogin

GoinElectric: https://www.goingelectric.de/stromtankstellen/api/ucp/

Deepseek: https://platform.deepseek.com/usage

```
Browser (index.html)
  │  SSE Stream (live agent logs)
  ▼
FastAPI Server (server.py)
  │
  ├── Agent 1: Route Planner    [DeepSeek]  → Google Maps Directions API
  ├── Agent 2: Charging Specialist [Claude] → OpenChargeMap API
  └── Agent 3: Route Builder   [DeepSeek]  → Google Maps URL
```

## 🛠 Setup

### 1. Abhängigkeiten
```bash
cd ev_route_webapp
uv sync
```

### 2. API Keys
```bash
cp .env.example .env
# Fülle DEEPSEEK_API_KEY, ANTHROPIC_API_KEY, GOOGLE_MAPS_API_KEY, OPENCHARGERMAP_API_KEY aus
```

### 3. Server starten
```bash
uv run ev-route-web
# → http://localhost:8000
```

## 📁 Struktur

```
ev_route_webapp/
├── pyproject.toml
├── .env.example
├── static/
│   └── index.html              ← Frontend (dark electric UI)
└── src/ev_route_agent/
    ├── server.py               ← FastAPI + SSE Streaming
    ├── crew.py                 ← CrewAI Crew
    ├── agents.py               ← DeepSeek + Claude Agenten
    ├── tasks.py                ← Task Definitionen
    ├── config/providers.py     ← Ladeanbieter
    └── tools/
        ├── geocode_tool.py
        ├── route_analysis_tool.py
        ├── charging_station_tool.py
        └── maps_link_builder.py
```

## 🌐 API Endpoints

| Endpoint | Methode | Beschreibung |
|---|---|---|
| `/` | GET | Frontend HTML |
| `/health` | GET | API Key Status prüfen |
| `/providers` | GET | Alle Ladeanbieter abrufen |
| `/plan-route` | POST | Route planen (SSE Stream) |
