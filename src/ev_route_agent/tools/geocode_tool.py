import os
import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class GeocodeInput(BaseModel):
    address: str = Field(description="The address or place name to geocode")


class GeocodeTool(BaseTool):
    name: str = "geocode_address"
    description: str = (
        "Converts a human-readable address or place name into GPS coordinates (latitude/longitude). "
        "Use this for start, destination, and any waypoints before route planning."
    )
    args_schema: type[BaseModel] = GeocodeInput

    def _run(self, address: str) -> str:
        api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            return "ERROR: GOOGLE_MAPS_API_KEY not set in environment."

        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {"address": address, "key": api_key}

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if data["status"] != "OK":
                return f"Geocoding failed for '{address}': {data.get('status')}"

            result = data["results"][0]
            loc = result["geometry"]["location"]
            formatted = result["formatted_address"]

            return (
                f"Address: {formatted}\n"
                f"Latitude: {loc['lat']}\n"
                f"Longitude: {loc['lng']}\n"
                f"Coords: {loc['lat']},{loc['lng']}"
            )
        except requests.RequestException as e:
            return f"HTTP error during geocoding: {e}"
