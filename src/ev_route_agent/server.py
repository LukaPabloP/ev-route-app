"""
EV Route WebApp – FastAPI Server
Streams CrewAI agent progress via Server-Sent Events (SSE)
"""
import os
import sys
import json
import asyncio
import threading
import queue
import uuid
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel

# ── Load env ──────────────────────────────────────────────────────────────────
ENV_FILE = Path(__file__).parent.parent.parent / ".env"
load_dotenv(ENV_FILE)

# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(title="EV Route Agent", version="1.0.0")

# Serve static files (frontend)
STATIC_DIR = Path(__file__).parent.parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Request Model ─────────────────────────────────────────────────────────────
class RouteRequest(BaseModel):
    origin: str
    destination: str
    range_km: float
    waypoints: str = ""
    preferred_providers: str = ""
    min_power_kw: float = 50.0


# ── SSE Progress Streaming ────────────────────────────────────────────────────
class ProgressCapture:
    """Captures CrewAI stdout and converts to SSE events."""

    def __init__(self, event_queue: queue.Queue):
        self.queue = event_queue
        self._original_stdout = sys.stdout
        self.full_log = []  # Collect all output for station parsing

    def write(self, text: str):
        self._original_stdout.write(text)
        if text.strip():
            self.full_log.append(text.rstrip())
            self.queue.put({"type": "log", "message": text.rstrip()})

    def flush(self):
        self._original_stdout.flush()


def run_crew_sync(route_input: dict, event_queue: queue.Queue):
    """Runs the CrewAI crew in a thread, pushing events to the queue."""
    try:
        # Import here to avoid circular issues
        from ev_route_agent.crew import create_ev_route_crew

        # Emit agent start events
        event_queue.put({"type": "agent_start", "agent": "Route Planner", "model": "Claude",
                          "message": "Analysiere Route und berechne Ladestopp-Positionen..."})

        # Monkey-patch to capture progress
        capture = ProgressCapture(event_queue)
        sys.stdout = capture

        crew = create_ev_route_crew(route_input)

        # Hook into task callbacks if available
        original_kickoff = crew.kickoff

        sys.stdout = capture
        result = original_kickoff()
        sys.stdout = capture._original_stdout

        # Parse result for structured data
        result_str = str(result)
        full_log_str = "\n".join(capture.full_log)

        # Extract Google Maps URL from result or full log
        maps_url = None
        import re as _re
        for text_to_search in [result_str, full_log_str]:
            url_match = _re.search(r'(https?://www\.google\.com/maps/dir/[^\s\n\)]*)', text_to_search)
            if url_match:
                maps_url = url_match.group(1).rstrip('*).>,;"\' ')
                break

        # Extract stations from the full log (intermediate task outputs contain station details)
        stations = _extract_stations_from_log(full_log_str)

        event_queue.put({
            "type": "complete",
            "result": result_str,
            "full_log": full_log_str,
            "maps_url": maps_url,
            "stations": stations,
        })

    except Exception as e:
        sys.stdout = sys.__stdout__
        event_queue.put({"type": "error", "message": str(e)})
    finally:
        sys.stdout = sys.__stdout__


def _extract_stations_from_log(log_text: str) -> list[dict]:
    """
    Extract the SELECTED charging stations from the CrewAI log.

    The log contains tool call results (with many stations per search) AND
    agent task outputs (with the selected best station per stop).
    We want the agent's final selections, not all raw search results.

    Strategy: Find the waypoints in the Google Maps URL - those are the actual
    selected stations. Then match them to station names from the log.
    """
    import re

    # Build a lookup of all station data by approximate coordinates
    all_stations = {}
    block_pattern = re.compile(
        r'---\s*Station\s*(\d+)\s*---(.+?)(?=---\s*Station\s*\d+\s*---|===|$)',
        re.DOTALL | re.IGNORECASE
    )
    for m in block_pattern.finditer(log_text):
        block = m.group(2)
        station = {}
        name_m = re.search(r'Name:\s*(.+)', block)
        if name_m:
            station['name'] = name_m.group(1).strip()
        prov_m = re.search(r'(?:Anbieter|Provider|Operator|Betreiber):\s*(.+)', block, re.IGNORECASE)
        if prov_m:
            station['provider'] = prov_m.group(1).strip().split('(')[0].strip()
        coord_m = re.search(r'(?:Koordinaten|Coords|coordinates|GPS):\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)', block, re.IGNORECASE)
        if coord_m:
            station['coords'] = f"{coord_m.group(1)},{coord_m.group(2)}"
            # Index by rounded coords for matching
            key = f"{round(float(coord_m.group(1)), 2)},{round(float(coord_m.group(2)), 2)}"
            all_stations[key] = station
        power_m = re.search(r'(?:Max\.?\s*Leistung|Power|Leistung):\s*(\d+)\s*kW', block, re.IGNORECASE)
        if power_m:
            station['power'] = f"{power_m.group(1)} kW"
        addr_m = re.search(r'(?:Adresse|Address|Ort):\s*(.+)', block, re.IGNORECASE)
        if addr_m:
            station['address'] = addr_m.group(1).strip()
        status_m = re.search(r'Status:\s*(.+)', block, re.IGNORECASE)
        if status_m:
            station['status'] = status_m.group(1).strip()

    # Strategy 1: Extract waypoints from Google Maps URL and match to station data
    url_match = re.search(r'waypoints=([^&\s\n\)]+)', log_text)
    if url_match and all_stations:
        waypoints_str = url_match.group(1)
        # URL-decode
        import urllib.parse
        waypoints_str = urllib.parse.unquote(waypoints_str)
        waypoint_coords = [w.strip() for w in waypoints_str.split('|') if w.strip()]

        stations = []
        for wp in waypoint_coords:
            nums = re.findall(r'-?\d+\.?\d*', wp)
            if len(nums) >= 2:
                lat, lng = float(nums[0]), float(nums[1])
                key = f"{round(lat, 2)},{round(lng, 2)}"
                if key in all_stations:
                    stations.append(all_stations[key])
                else:
                    # Try to find closest match
                    best_match = None
                    best_dist = 999
                    for sk, sv in all_stations.items():
                        sk_nums = sk.split(',')
                        d = abs(float(sk_nums[0]) - lat) + abs(float(sk_nums[1]) - lng)
                        if d < best_dist:
                            best_dist = d
                            best_match = sv
                    if best_match and best_dist < 0.5:
                        stations.append(best_match)
                    else:
                        stations.append({'name': f'{lat},{lng}', 'coords': f'{lat},{lng}'})
        if stations:
            return stations

    # Strategy 2: Find "STATION N:" blocks in task outputs
    station_blocks = re.compile(
        r'STATION\s*\d+\s*:(.+?)(?=STATION\s*\d+\s*:|$)',
        re.DOTALL | re.IGNORECASE
    )
    stations = []
    for m in station_blocks.finditer(log_text):
        block = m.group(1)
        station = {}
        name_m = re.search(r'(?:^|\n)\s*(.+?)(?:\n|$)', block)
        if name_m:
            station['name'] = name_m.group(1).strip().lstrip(':- *')
        prov_m = re.search(r'(?:PROVIDER|Anbieter):\s*(.+)', block, re.IGNORECASE)
        if prov_m:
            station['provider'] = prov_m.group(1).strip()
        coord_m = re.search(r'(?:COORDS|Koordinaten):\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)', block, re.IGNORECASE)
        if coord_m:
            station['coords'] = f"{coord_m.group(1)},{coord_m.group(2)}"
        power_m = re.search(r'(?:POWER|Leistung):\s*(\d+)\s*kW', block, re.IGNORECASE)
        if power_m:
            station['power'] = f"{power_m.group(1)} kW"
        if station.get('name'):
            stations.append(station)
    if stations:
        return stations

    # Strategy 3: Return first station per search (the "--- Station 1 ---" from each tool call)
    first_per_search = []
    search_blocks = re.split(r'===\s*IONITY STATIONEN|===\s*TESLA SUPERCHARGER', log_text)
    for sb in search_blocks[1:]:
        first_match = re.search(r'---\s*Station\s*1\s*---(.+?)(?=---\s*Station\s*2\s*---|===|$)', sb, re.DOTALL)
        if first_match:
            block = first_match.group(1)
            station = {}
            name_m = re.search(r'Name:\s*(.+)', block)
            if name_m:
                station['name'] = name_m.group(1).strip()
            prov_m = re.search(r'(?:Anbieter|Provider):\s*(.+)', block, re.IGNORECASE)
            if prov_m:
                station['provider'] = prov_m.group(1).strip().split('(')[0].strip()
            power_m = re.search(r'(?:Max\.?\s*Leistung|Power):\s*(\d+)\s*kW', block, re.IGNORECASE)
            if power_m:
                station['power'] = f"{power_m.group(1)} kW"
            addr_m = re.search(r'(?:Adresse|Address):\s*(.+)', block, re.IGNORECASE)
            if addr_m:
                station['address'] = addr_m.group(1).strip()
            if station.get('name'):
                first_per_search.append(station)

    return first_per_search


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main frontend HTML."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Frontend not found. Run build or place index.html in /static</h1>")


@app.get("/health")
async def health():
    keys = {
        "deepseek": bool(os.getenv("DEEPSEEK_API_KEY")),
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "google_maps": bool(os.getenv("GOOGLE_MAPS_API_KEY")),
        "openchargermap": bool(os.getenv("OPENCHARGERMAP_API_KEY")),
        "goingelectric": bool(os.getenv("GOINGELECTRIC_API_KEY")),
    }
    return JSONResponse({"status": "ok", "api_keys": keys})


@app.get("/providers")
async def get_providers():
    """Returns all available charging providers."""
    from ev_route_agent.config.providers import CHARGING_PROVIDERS, HPC_PROVIDERS
    providers = [
        {"name": name, "hpc": name in HPC_PROVIDERS}
        for name in CHARGING_PROVIDERS
    ]
    return JSONResponse({"providers": providers})


JOB_QUEUES: dict[str, queue.Queue] = {}
JOB_THREADS: dict[str, threading.Thread] = {}


@app.post("/plan-route")
async def plan_route(request: RouteRequest):
    """Start a route-planning job and return its job_id."""
    job_id = str(uuid.uuid4())
    event_queue: queue.Queue = queue.Queue()
    JOB_QUEUES[job_id] = event_queue

    route_input = {
        "origin": request.origin,
        "destination": request.destination,
        "range_km": request.range_km,
        "waypoints": request.waypoints,
        "preferred_providers": request.preferred_providers,
        "min_power_kw": request.min_power_kw,
    }

    thread = threading.Thread(
        target=run_crew_sync,
        args=(route_input, event_queue),
        daemon=True,
    )
    thread.start()
    JOB_THREADS[job_id] = thread

    return JSONResponse({"job_id": job_id})


@app.get("/stream/{job_id}")
async def stream_job(job_id: str, req: Request):
    """SSE endpoint: streams agent progress for a given job."""
    event_queue = JOB_QUEUES.get(job_id)
    if event_queue is None:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    thread = JOB_THREADS.get(job_id)

    async def event_generator() -> AsyncGenerator[dict, None]:
        yield {"event": "connected", "data": json.dumps({"message": "Agent-Crew gestartet..."})}

        while True:
            if await req.is_disconnected():
                break

            try:
                event = event_queue.get(timeout=0.1)
                yield {"event": event["type"], "data": json.dumps(event)}

                if event["type"] in ("complete", "error"):
                    break
            except queue.Empty:
                if thread and not thread.is_alive() and event_queue.empty():
                    break
                await asyncio.sleep(0.05)

        # Cleanup
        JOB_QUEUES.pop(job_id, None)
        JOB_THREADS.pop(job_id, None)

    return EventSourceResponse(event_generator())


# ── Entry Point ───────────────────────────────────────────────────────────────
def main():
    port = int(os.getenv("PORT", 8000))
    print(f"\n⚡ EV Route WebApp starting on http://localhost:{port}\n")
    uvicorn.run("ev_route_agent.server:app", host="0.0.0.0", port=port, reload=True)


if __name__ == "__main__":
    main()
