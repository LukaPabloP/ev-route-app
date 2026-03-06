import re
import urllib.parse
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def _sanitize_coord(value: str) -> str:
    """
    Clean up a coordinate string that an LLM might produce.
    Handles formats like:
      - "48.137,11.575"  (correct)
      - "48.137, 11.575" (extra space)
      - "48.137;11.575"  (semicolon)
      - "(48.137, 11.575)" (parentheses)
      - "lat: 48.137, lng: 11.575" (labels)
    Returns cleaned "lat,lng" or original string if not coordinates.
    """
    value = value.strip().strip("()[]")
    # Remove common labels
    value = re.sub(r'(?:lat(?:itude)?|lng|lon(?:gitude)?)\s*[:=]\s*', '', value, flags=re.IGNORECASE)
    # Try to extract two decimal numbers
    nums = re.findall(r'-?\d+\.?\d*', value)
    if len(nums) >= 2:
        try:
            lat, lng = float(nums[0]), float(nums[1])
            # Basic sanity check for valid GPS coordinates
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return f"{lat},{lng}"
        except ValueError:
            pass
    return value


class MapsLinkInput(BaseModel):
    origin: str = Field(description="Start address or 'lat,lng' coordinates")
    destination: str = Field(description="Destination address or 'lat,lng' coordinates")
    waypoints: str = Field(
        default="",
        description=(
            "Pipe-separated list of waypoints (max 9), each as 'lat,lng'. "
            "Example: '48.137,11.575|48.775,9.182'"
        ),
    )
    travel_mode: str = Field(default="driving", description="Travel mode: driving, walking, bicycling, transit")


class MapsLinkBuilderTool(BaseTool):
    name: str = "build_google_maps_link"
    description: str = (
        "Builds a Google Maps directions URL with origin, destination and waypoints. "
        "Waypoints should include the optimal charging station coordinates as 'lat,lng'. "
        "Returns a clickable Google Maps link the user can open directly."
    )
    args_schema: type[BaseModel] = MapsLinkInput

    def _run(
        self,
        origin: str,
        destination: str,
        waypoints: str = "",
        travel_mode: str = "driving",
    ) -> str:
        base = "https://www.google.com/maps/dir/?api=1"

        # Sanitize origin and destination
        origin_clean = _sanitize_coord(origin)
        dest_clean = _sanitize_coord(destination)

        params = {
            "origin": origin_clean,
            "destination": dest_clean,
            "travelmode": travel_mode,
        }

        extra_note = ""
        if waypoints.strip():
            # Split on pipe or semicolon, sanitize each waypoint
            raw_wps = re.split(r'[|;]', waypoints)
            wp_list = [_sanitize_coord(w) for w in raw_wps if w.strip()]
            if len(wp_list) > 9:
                wp_list = wp_list[:9]
                extra_note = "\nWarnung: Mehr als 9 Zwischenstopps - nur die ersten 9 wurden uebernommen."
            params["waypoints"] = "|".join(wp_list)

        query_string = "&".join(
            f"{k}={urllib.parse.quote(str(v), safe=',|')}" for k, v in params.items()
        )
        url = f"{base}&{query_string}"

        # Build summary
        wp_list_display = params.get("waypoints", "").split("|") if "waypoints" in params else []
        stop_summary = ""
        if wp_list_display:
            stop_summary = "\n\nZwischenstopps:\n" + "\n".join(
                f"  {i+1}. {wp}" for i, wp in enumerate(wp_list_display)
            )

        return (
            f"=== GOOGLE MAPS ROUTE ===\n"
            f"Von:  {origin_clean}\n"
            f"Nach: {dest_clean}{stop_summary}\n\n"
            f"Google Maps Link:\n{url}"
            f"{extra_note}"
        )
