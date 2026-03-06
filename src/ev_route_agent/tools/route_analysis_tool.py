import os
import math
import requests
import polyline as polyline_lib
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class RouteAnalysisInput(BaseModel):
    origin_coords: str = Field(description="Start coordinates as 'lat,lng'")
    destination_coords: str = Field(description="Destination coordinates as 'lat,lng'")
    range_km: float = Field(description="Current EV range in kilometers")
    safety_buffer_pct: float = Field(
        default=0.15,
        description="Safety buffer as fraction (0.15 = arrive at charger with 15% remaining)"
    )
    waypoints_coords: str = Field(
        default="",
        description="Optional user waypoints as 'lat1,lng1|lat2,lng2'"
    )


class RouteAnalysisTool(BaseTool):
    name: str = "analyze_route_and_find_charging_locations"
    description: str = (
        "Uses Google Maps Directions API to analyze a driving route. "
        "Given EV range and safety buffer, it calculates where along the route "
        "charging stops are needed, and returns the GPS coordinates for those locations. "
        "Also returns total distance and estimated duration."
    )
    args_schema: type[BaseModel] = RouteAnalysisInput

    def _run(
        self,
        origin_coords: str,
        destination_coords: str,
        range_km: float,
        safety_buffer_pct: float = 0.15,
        waypoints_coords: str = "",
    ) -> str:
        api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            return "ERROR: GOOGLE_MAPS_API_KEY not set."

        # ── 1. Fetch route from Google Directions ──────────────────────────
        url = "https://maps.googleapis.com/maps/api/directions/json"
        params = {
            "origin": origin_coords,
            "destination": destination_coords,
            "mode": "driving",
            "key": api_key,
        }
        if waypoints_coords:
            params["waypoints"] = f"via:{waypoints_coords.replace('|', '|via:')}"

        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            return f"HTTP error: {e}"

        if data["status"] != "OK":
            return f"Directions API error: {data.get('status')} – {data.get('error_message', '')}"

        route = data["routes"][0]
        legs = route["legs"]

        # ── 2. Extract all steps with cumulative distance ──────────────────
        total_distance_m = sum(leg["distance"]["value"] for leg in legs)
        total_duration_s = sum(leg["duration"]["value"] for leg in legs)
        total_km = total_distance_m / 1000

        # Flatten all steps across all legs
        steps = []
        cum_dist = 0.0
        for leg in legs:
            for step in leg["steps"]:
                cum_dist += step["distance"]["value"] / 1000
                steps.append({
                    "cum_km": cum_dist,
                    "end_lat": step["end_location"]["lat"],
                    "end_lng": step["end_location"]["lng"],
                })

        # ── 3. Calculate charging stop positions ──────────────────────────
        effective_range = range_km * (1.0 - safety_buffer_pct)
        charging_stops = []
        current_charge_km = 0.0  # km since last charge / start

        for step in steps:
            driven_since_last = step["cum_km"] - (
                charging_stops[-1]["cum_km"] if charging_stops else 0.0
            )
            if driven_since_last >= effective_range:
                # Find the step just before we run out
                charging_stops.append({
                    "cum_km": step["cum_km"],
                    "lat": step["end_lat"],
                    "lng": step["end_lng"],
                })

        # ── 4. Build result ────────────────────────────────────────────────
        duration_h = total_duration_s // 3600
        duration_m = (total_duration_s % 3600) // 60

        lines = [
            f"=== ROUTE ANALYSIS ===",
            f"Gesamtstrecke:    {total_km:.1f} km",
            f"Fahrzeit:         {duration_h}h {duration_m}min (ohne Ladestopps)",
            f"EV Reichweite:    {range_km} km",
            f"Effektive Range:  {effective_range:.0f} km (mit {safety_buffer_pct*100:.0f}% Puffer)",
            f"Benötigte Ladestopps: {len(charging_stops)}",
            "",
            "=== LADESTOP-KOORDINATEN ===",
        ]

        if not charging_stops:
            lines.append("✅ Keine Ladestopps nötig – Ziel ist in Reichweite!")
        else:
            for i, stop in enumerate(charging_stops, 1):
                lines.append(
                    f"Stop {i}: lat={stop['lat']:.6f}, lng={stop['lng']:.6f} "
                    f"(nach ca. {stop['cum_km']:.0f} km)"
                )

        return "\n".join(lines)


# ── Haversine helper (not used above but useful for agents) ───────────────────
def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
