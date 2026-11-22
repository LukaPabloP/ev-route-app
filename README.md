# EV Route Agent

Plan a long trip in an electric car and get the charging stops picked for you.
Four AI agents work through the route one after another and stream their progress live to the browser.

**Live demo:** https://ev-route-app-911796949663.europe-west1.run.app/

## Why I built this

My family bought an electric car, and my dad said he wished there was an app that plans a trip and chooses the charging stops for him, filtered by the charging providers he actually uses. I built it for fun, and it turned into my first multi-agent project.

## How it works

```
Browser (HTML/CSS/JS)
  │  Server-Sent Events (live agent log)
  ▼
FastAPI server (server.py)
  │
  ├── Agent 1: Route Planner        → geocoding and charging stop calculation
  ├── Agent 2: Charging Specialist  → finds stations near each stop
  ├── Agent 3: Provider QA          → checks the stations against the selected providers
  └── Agent 4: Route Builder        → builds a Google Maps link with all waypoints
```

The agents are built with [CrewAI](https://www.crewai.com/) and run on Claude through the Anthropic API. They run sequentially, and each one has its own tools.

### Data sources

| Source | Coverage | API key |
|---|---|---|
| IONITY | Official station data | not needed |
| Tesla Supercharger | via supercharge.info | not needed |
| Bundesnetzagentur | about 195,000 charging points in Germany (open data) | not needed |
| GoingElectric | Europe | optional |
| OpenChargeMap | Worldwide fallback | needed |

## Features

- Filter by charging provider (IONITY, Tesla, EnBW, Allego and more), with search
- Optional intermediate stops, geocoded and added to the final route
- Adjustable vehicle range and minimum charging power
- Live view of the agent pipeline while it works
- Result with station cards showing provider and power
- Google Maps link with every charging stop as a waypoint
- Works on mobile

## Tech stack

Python, FastAPI, CrewAI, Anthropic API, Google Maps Directions and Geocoding API, Server-Sent Events, plain HTML/CSS/JavaScript, Docker, Google Cloud Run.

## Run it locally

```bash
pip install -e .
```

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=...
GOOGLE_MAPS_API_KEY=...
OPENCHARGERMAP_API_KEY=...
GOINGELECTRIC_API_KEY=...   # optional, OpenChargeMap is used without it
```

Start the server:

```bash
python -m ev_route_agent.server
# http://localhost:8000
```

Or with Docker:

```bash
docker build -t ev-route-app .
docker run -p 8080:8080 --env-file .env ev-route-app
```

## Project structure

```
├── Dockerfile
├── pyproject.toml
├── static/                     frontend (HTML, CSS, JS with SSE handling)
└── src/ev_route_agent/
    ├── server.py               FastAPI app and SSE streaming
    ├── crew.py                 CrewAI crew (4 agents, sequential)
    ├── agents.py               agent definitions
    ├── tasks.py                task definitions
    ├── config/providers.py     charging providers and data source mappings
    └── tools/                  geocoding, route analysis, station search, Maps link builder
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Frontend |
| `/health` | GET | Shows which API keys are configured |
| `/providers` | GET | All charging providers |
| `/plan-route` | POST | Starts a route planning job |
| `/stream/{job_id}` | GET | Live event stream for a job |

## License

MIT
