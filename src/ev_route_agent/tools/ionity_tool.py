"""
Direct IONITY station lookup from IONITY's own mapdata.json.
Always returns accurate, up-to-date IONITY stations.
"""
import math
import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

IONITY_DATA_URL = "https://wf-assets.com/ionity/mapdata.json"

# Module-level cache to avoid re-fetching on every tool call
_cached_stations: list[dict] | None = None


def _fetch_ionity_stations() -> list[dict]:
    """Fetch and cache all IONITY stations."""
    global _cached_stations
    if _cached_stations is not None:
        return _cached_stations
    try:
        resp = requests.get(IONITY_DATA_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # Stations are under the "LocationDetails" key
        locations = data.get("LocationDetails", data) if isinstance(data, dict) else data
        # Only keep active stations
        _cached_stations = [s for s in locations if isinstance(s, dict) and s.get("state") == "active"]
        return _cached_stations
    except requests.RequestException:
        return []


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class IonitySearchInput(BaseModel):
    latitude: float = Field(description="Latitude of the search location")
    longitude: float = Field(description="Longitude of the search location")
    radius_km: float = Field(default=30.0, description="Search radius in kilometers")
    max_results: int = Field(default=5, description="Maximum number of stations to return")


class IonityTool(BaseTool):
    name: str = "find_ionity_stations"
    description: str = (
        "Finds IONITY charging stations near a GPS coordinate using IONITY's "
        "official station data. Returns ONLY IONITY stations with name, coordinates, "
        "connector count, and max power. Use this tool when the user wants IONITY stations."
    )
    args_schema: type[BaseModel] = IonitySearchInput

    def _run(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 30.0,
        max_results: int = 5,
    ) -> str:
        stations = _fetch_ionity_stations()
        if not stations:
            return "ERROR: Could not fetch IONITY station data."

        # Find stations within radius
        nearby = []
        for s in stations:
            try:
                s_lat = float(s["latitude"])
                s_lng = float(s["longitude"])
            except (ValueError, KeyError):
                continue
            dist = _haversine_km(latitude, longitude, s_lat, s_lng)
            if dist <= radius_km:
                nearby.append((dist, s, s_lat, s_lng))

        nearby.sort(key=lambda x: x[0])

        if not nearby:
            return (
                f"Keine IONITY-Stationen in {radius_km} km Umkreis von "
                f"{latitude:.4f},{longitude:.4f} gefunden. "
                f"Versuche einen groesseren Radius (z.B. {int(radius_km * 2)} km)."
            )

        lines = [
            f"=== IONITY STATIONEN (Radius {radius_km}km) ===",
            f"Suche bei: {latitude:.5f},{longitude:.5f}",
            f"Quelle: IONITY offiziell (ionity.eu)",
            "",
        ]

        for i, (dist, s, s_lat, s_lng) in enumerate(nearby[:max_results]):
            name = s.get("name", "IONITY")
            country = s.get("country", "").title()
            total = s.get("connectorsTotal", 0)

            # Determine max power
            max_power = 0
            for kw in [600, 500, 400, 350, 200, 50]:
                count = s.get(f"connectors{kw}kw", 0)
                if count and count > 0:
                    max_power = kw
                    break
            ac_count = s.get("connectorsAC", 0)

            # Build power breakdown
            power_parts = []
            for kw in [600, 500, 400, 350, 200, 50]:
                count = s.get(f"connectors{kw}kw", 0)
                if count and count > 0:
                    power_parts.append(f"{count}x {kw}kW")
            if ac_count:
                power_parts.append(f"{ac_count}x AC")
            power_str = ", ".join(power_parts) if power_parts else "unbekannt"

            lines += [
                f"--- Station {i + 1} ---",
                f"Name:        {name}",
                f"Anbieter:    IONITY",
                f"Land:        {country}",
                f"Koordinaten: {s_lat},{s_lng}",
                f"Entfernung:  {dist:.1f} km",
                f"Max. Leistung: {max_power} kW",
                f"Ladepunkte:  {total} ({power_str})",
                "",
            ]

        return "\n".join(lines)
