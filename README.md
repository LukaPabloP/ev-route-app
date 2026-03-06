# EV Route Agent

Multi-Agent Web App zur Planung von Elektrofahrzeug-Routen mit optimalen Ladestopps.
Nutzt **CrewAI** mit 4 spezialisierten Agenten, die live ihren Fortschritt via **Server-Sent Events** ans Frontend streamen.

## Architektur

```
Browser (HTML/CSS/JS)
  │  SSE Stream (live Agent-Logs)
  ▼
FastAPI Server (server.py)
  │
  ├── Agent 1: Route Planner         [Claude]  → Geocodierung + Ladestopp-Berechnung
  ├── Agent 2: Charging Specialist    [Claude]  → IONITY/Tesla/BNA direkt + GE/OCM Fallback
  ├── Agent 3: Provider QA            [Claude]  → Validiert Anbieter-Filter
  └── Agent 4: Route Builder          [Claude]  → Google Maps Link mit allen Waypoints
```

### Datenquellen

- **IONITY** – Offizielle Stationsdaten via wf-assets.com (kein API Key)
- **Tesla Supercharger** – Via supercharge.info (kein API Key)
- **Bundesnetzagentur** – Alle ~195.000 Ladepunkte in DE via Open Data ArcGIS (kein API Key)
- **GoingElectric** – Europaweite Stationsdaten (API Key)
- **OpenChargeMap** – Globaler Fallback (API Key)

## Setup

### 1. Abhaengigkeiten

```bash
cd ev_route_webapp
pip install -e .
```

### 2. API Keys

Erstelle eine `.env` Datei im Projektroot:

```
ANTHROPIC_API_KEY=sk-...
GOOGLE_MAPS_API_KEY=...
OPENCHARGERMAP_API_KEY=...
GOINGELECTRIC_API_KEY=...
DEEPSEEK_API_KEY=...
```

### 3. Server starten

```bash
python -m ev_route_agent.server
# → http://localhost:8000
```

## Projektstruktur

```
ev_route_webapp/
├── pyproject.toml
├── static/
│   ├── index.html          ← Frontend HTML
│   ├── style.css           ← Dark Electric UI
│   └── app.js              ← Client-Logik + SSE Handling
└── src/ev_route_agent/
    ├── server.py            ← FastAPI + SSE Streaming
    ├── crew.py              ← CrewAI Crew (4 Agents, sequential)
    ├── agents.py            ← Agent-Definitionen
    ├── tasks.py             ← Task-Definitionen mit Waypoint-Support
    ├── config/providers.py  ← Ladeanbieter + OCM/GE/BNA Mappings
    └── tools/
        ├── geocode_tool.py           ← Google Maps Geocoding
        ├── route_analysis_tool.py    ← Routenberechnung + Ladestopp-Positionen
        ├── charging_station_tool.py  ← IONITY/Tesla/BNA direkt + API-Fallback
        └── maps_link_builder.py      ← Google Maps URL Builder
```

## API Endpoints

| Endpoint | Methode | Beschreibung |
|---|---|---|
| `/` | GET | Frontend |
| `/health` | GET | API Key Status |
| `/providers` | GET | Alle Ladeanbieter |
| `/plan-route` | POST | Route planen (startet Job) |
| `/stream/{job_id}` | GET | SSE Stream fuer Job |

## Features

- Anbieter-Filter (IONITY, Tesla, EnBW, Allego, etc.)
- Suchfunktion fuer Ladeanbieter
- Zwischenstopps (werden geocodiert und in Google Maps Link eingebaut)
- Einstellbare EV-Reichweite und Mindest-Ladeleistung
- Live Agent-Pipeline mit Fortschrittsanzeige
- Ergebnis mit Stationskarten, Anbieter, Leistung
- Google Maps Link mit allen Ladestopps als Waypoints
- Mobile Responsive
