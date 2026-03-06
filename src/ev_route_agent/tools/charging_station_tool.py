import math
import os
import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from ev_route_agent.config.providers import get_operator_ids, get_ge_networks, get_bna_patterns

# ── IONITY direct data (cached) ────────────────────────────────────────────
IONITY_DATA_URL = "https://wf-assets.com/ionity/mapdata.json"
_ionity_cache: list[dict] | None = None


def _fetch_ionity_stations() -> list[dict]:
    global _ionity_cache
    if _ionity_cache is not None:
        return _ionity_cache
    try:
        resp = requests.get(IONITY_DATA_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        locations = data.get("LocationDetails", data) if isinstance(data, dict) else data
        _ionity_cache = [s for s in locations if isinstance(s, dict) and s.get("state") == "active"]
        return _ionity_cache
    except requests.RequestException:
        return []


# ── Tesla Supercharger direct data (cached via supercharge.info) ──────────
TESLA_DATA_URL = "https://supercharge.info/service/supercharge/allSites"
_tesla_cache: list[dict] | None = None


def _fetch_tesla_stations() -> list[dict]:
    global _tesla_cache
    if _tesla_cache is not None:
        return _tesla_cache
    try:
        resp = requests.get(TESLA_DATA_URL, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        _tesla_cache = [
            s for s in data
            if isinstance(s, dict)
        ]
        return _tesla_cache
    except requests.RequestException:
        return []


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Tool ────────────────────────────────────────────────────────────────────

class ChargingStationInput(BaseModel):
    latitude: float = Field(description="Latitude of the search location")
    longitude: float = Field(description="Longitude of the search location")
    radius_km: float = Field(default=30.0, description="Search radius in kilometers")
    min_power_kw: float = Field(default=50.0, description="Minimum charging power in kW")
    max_results: int = Field(default=5, description="Maximum number of stations to return")


class ChargingStationTool(BaseTool):
    name: str = "find_charging_stations"
    description: str = (
        "Finds EV charging stations near a GPS coordinate. "
        "Automatically filters by the user's preferred providers. "
        "Returns station name, address, GPS coordinates, power, and connector types."
    )
    args_schema: type[BaseModel] = ChargingStationInput

    # This is set at construction time and CANNOT be overridden by the agent.
    # The agent only needs to pass latitude/longitude.
    _forced_providers: list[str] = []

    def __init__(self, forced_providers: list[str] | None = None, **kwargs):
        super().__init__(**kwargs)
        if forced_providers:
            self._forced_providers = forced_providers

    def _run(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 30.0,
        min_power_kw: float = 50.0,
        max_results: int = 5,
    ) -> str:
        provider_list = self._forced_providers

        # Direct data sources (100% accurate, no API key needed)
        direct_results = []
        remaining_providers = list(provider_list)

        # IONITY: direct data from ionity.eu
        if "IONITY" in remaining_providers:
            ionity_result = self._search_ionity_direct(
                latitude, longitude, radius_km, max_results,
            )
            if ionity_result:
                direct_results.append(ionity_result)
            remaining_providers = [p for p in remaining_providers if p != "IONITY"]

        # Tesla Supercharger: direct data from supercharge.info
        if "Tesla Supercharger" in remaining_providers:
            tesla_result = self._search_tesla_direct(
                latitude, longitude, radius_km, max_results,
            )
            if tesla_result:
                direct_results.append(tesla_result)
            remaining_providers = [p for p in remaining_providers if p != "Tesla Supercharger"]

        # If all requested providers had direct sources, return combined result
        if provider_list and not remaining_providers:
            if direct_results:
                return "\n\n".join(direct_results)
            return (
                f"Keine Ladestationen der Anbieter {', '.join(provider_list)} "
                f"in {radius_km} km Umkreis von {latitude:.4f},{longitude:.4f} gefunden."
            )

        # Remaining providers: try BNA first (no API key needed), then GE/OCM
        if remaining_providers:
            # BNA: covers all German stations
            bna_result = self._search_bna(
                latitude, longitude, radius_km,
                remaining_providers, min_power_kw, max_results,
            )
            if bna_result:
                direct_results.append(bna_result)
            else:
                # Fallback to GoingElectric/OCM
                api_result = self._search_other_providers(
                    latitude, longitude, radius_km,
                    remaining_providers, min_power_kw, max_results,
                )
                if api_result:
                    direct_results.append(api_result)

        # Return combined results from all sources
        if direct_results:
            return "\n\n".join(direct_results)

        if provider_list:
            # Provider filter active but nothing found — do NOT fall back to all providers
            return (
                f"Keine Ladestationen der Anbieter {', '.join(provider_list)} "
                f"in {radius_km} km Umkreis von {latitude:.4f},{longitude:.4f} gefunden. "
                f"Diese Anbieter haben moeglicherweise keine Abdeckung in dieser Region."
            )

        # No provider filter — search all via BNA first, then GE/OCM
        result = self._search_bna(
            latitude, longitude, radius_km,
            [], min_power_kw, max_results,
        )
        if result:
            return result

        result = self._search_other_providers(
            latitude, longitude, radius_km,
            [], min_power_kw, max_results,
        )
        if result:
            return result

        return (
            f"Keine Ladestationen gefunden in {radius_km} km Umkreis von "
            f"{latitude:.4f},{longitude:.4f}."
        )

    # ── IONITY Direct ───────────────────────────────────────────────────

    def _search_ionity_direct(
        self, latitude: float, longitude: float,
        radius_km: float, max_results: int,
    ) -> str | None:
        stations = _fetch_ionity_stations()
        if not stations:
            return None

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
            return None

        lines = [
            f"=== IONITY STATIONEN (Radius {radius_km}km) ===",
            f"Suche bei: {latitude:.5f},{longitude:.5f}",
            f"Quelle: IONITY offiziell",
            "",
        ]

        for i, (dist, s, s_lat, s_lng) in enumerate(nearby[:max_results]):
            name = s.get("name", "IONITY")
            country = s.get("country", "").title()
            total = s.get("connectorsTotal", 0)

            max_power = 0
            for kw in [600, 500, 400, 350, 200, 50]:
                count = s.get(f"connectors{kw}kw", 0)
                if count and count > 0:
                    max_power = kw
                    break

            power_parts = []
            for kw in [600, 500, 400, 350, 200, 50]:
                count = s.get(f"connectors{kw}kw", 0)
                if count and count > 0:
                    power_parts.append(f"{count}x {kw}kW")
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

    # ── Tesla Supercharger Direct ────────────────────────────────────────

    def _search_tesla_direct(
        self, latitude: float, longitude: float,
        radius_km: float, max_results: int,
    ) -> str | None:
        stations = _fetch_tesla_stations()
        if not stations:
            return None

        nearby = []
        for s in stations:
            gps = s.get("gps", {})
            try:
                s_lat = float(gps.get("latitude", 0))
                s_lng = float(gps.get("longitude", 0))
            except (ValueError, TypeError):
                continue
            if s_lat == 0 and s_lng == 0:
                continue
            dist = _haversine_km(latitude, longitude, s_lat, s_lng)
            if dist <= radius_km:
                nearby.append((dist, s, s_lat, s_lng))

        nearby.sort(key=lambda x: x[0])
        if not nearby:
            return None

        lines = [
            f"=== TESLA SUPERCHARGER (Radius {radius_km}km) ===",
            f"Suche bei: {latitude:.5f},{longitude:.5f}",
            f"Quelle: supercharge.info",
            "",
        ]

        for i, (dist, s, s_lat, s_lng) in enumerate(nearby[:max_results]):
            name = s.get("name", "Tesla Supercharger")
            addr = s.get("address", {})
            street = addr.get("street", "")
            city = addr.get("city", "")
            country = addr.get("country", "")
            stall_count = s.get("stallCount", 0)
            power_kw = s.get("powerKilowatt", 0)
            status = s.get("status", "UNKNOWN")
            status_str = status if status == "OPEN" else f"⚠ {status}"

            lines += [
                f"--- Station {i + 1} ---",
                f"Name:        Tesla Supercharger {name}",
                f"Anbieter:    Tesla Supercharger",
                f"Status:      {status_str}",
                f"Adresse:     {street}, {city} {country}",
                f"Koordinaten: {s_lat},{s_lng}",
                f"Entfernung:  {dist:.1f} km",
                f"Max. Leistung: {power_kw} kW",
                f"Ladepunkte:  {stall_count}",
                "",
            ]

        return "\n".join(lines)

    # ── Bundesnetzagentur (all German stations, no API key) ─────────────

    def _search_bna(
        self, latitude: float, longitude: float,
        radius_km: float, provider_list: list[str],
        min_power_kw: float, max_results: int,
    ) -> str | None:
        # Build bounding box from radius
        dlat = radius_km / 111.0
        dlng = radius_km / (111.0 * math.cos(math.radians(latitude)))
        bbox = f"{longitude - dlng},{latitude - dlat},{longitude + dlng},{latitude + dlat}"

        # Build WHERE clause
        where_parts = [f"Nennleistung_Ladeeinrichtung__k >= {int(min_power_kw)}"]
        if provider_list:
            patterns = get_bna_patterns(provider_list)
            if patterns:
                like_clauses = [f"Betreiber LIKE '%{p}%'" for p in patterns]
                where_parts.append(f"({' OR '.join(like_clauses)})")

        params = {
            "where": " AND ".join(where_parts),
            "outFields": "Betreiber,Anzeigename__Karte_,Ort,Straße,Hausnummer,Breitengrad,Längengrad,"
                         "Nennleistung_Ladeeinrichtung__k,Anzahl_Ladepunkte,Steckertypen1,"
                         "Nennleistung_Stecker1,Steckertypen2,Nennleistung_Stecker2",
            "geometry": bbox,
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "orderByFields": "Nennleistung_Ladeeinrichtung__k DESC",
            "resultRecordCount": max(max_results * 3, 15),
            "f": "json",
        }

        try:
            resp = requests.get(
                "https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/"
                "Ladesaeulen_in_Deutschland/FeatureServer/0/query",
                params=params, timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            return None

        features = data.get("features", [])
        if not features:
            return None

        lines = [
            f"=== BUNDESNETZAGENTUR LADESTATIONEN (Radius ~{radius_km}km, min {min_power_kw}kW) ===",
            f"Suche bei: {latitude:.5f},{longitude:.5f}",
            f"Quelle: Bundesnetzagentur Ladesaeulenregister (Open Data)",
            "",
        ]

        count = 0
        for feat in features:
            if count >= max_results:
                break
            a = feat.get("attributes", {})
            s_lat = a.get("Breitengrad")
            s_lng = a.get("Längengrad")
            if not s_lat or not s_lng:
                continue

            dist = _haversine_km(latitude, longitude, s_lat, s_lng)
            if dist > radius_km:
                continue

            operator = a.get("Betreiber") or "Unbekannt"
            display_name = a.get("Anzeigename__Karte_") or operator
            city = a.get("Ort", "")
            street = a.get("Straße", "")
            house_nr = a.get("Hausnummer", "")
            power = a.get("Nennleistung_Ladeeinrichtung__k", 0)
            num_points = a.get("Anzahl_Ladepunkte", 0)

            connectors = []
            for i in range(1, 3):
                ct = a.get(f"Steckertypen{i}")
                if ct:
                    cp = a.get(f"Nennleistung_Stecker{i}", "")
                    connectors.append(f"{ct} ({cp}kW)" if cp else ct)
            connectors_str = ", ".join(connectors) if connectors else "unbekannt"

            addr = f"{street} {house_nr}".strip()
            if city:
                addr = f"{addr}, {city}" if addr else city

            lines += [
                f"--- Station {count + 1} ---",
                f"Name:        {display_name}",
                f"Anbieter:    {operator}",
                f"Adresse:     {addr}",
                f"Koordinaten: {s_lat},{s_lng}",
                f"Entfernung:  {dist:.1f} km",
                f"Max. Leistung: {power} kW",
                f"Ladepunkte:  {num_points}",
                f"Stecker:     {connectors_str}",
                "",
            ]
            count += 1

        return "\n".join(lines) if count > 0 else None

    # ── Other providers (GoingElectric + OCM fallback) ──────────────────

    def _search_other_providers(
        self, latitude: float, longitude: float, radius_km: float,
        provider_list: list[str], min_power_kw: float, max_results: int,
    ) -> str | None:
        # Try GoingElectric first
        ge_key = os.getenv("GOINGELECTRIC_API_KEY")
        if ge_key:
            result = self._search_goingelectric(
                ge_key, latitude, longitude, radius_km,
                provider_list, min_power_kw, max_results,
            )
            if result:
                return result

        # Fallback to OpenChargeMap
        ocm_key = os.getenv("OPENCHARGERMAP_API_KEY")
        if ocm_key:
            result = self._search_openchargemap(
                ocm_key, latitude, longitude, radius_km,
                provider_list, min_power_kw, max_results,
            )
            if result:
                return result

        return None

    # ── GoingElectric ───────────────────────────────────────────────────

    def _search_goingelectric(
        self, api_key: str, latitude: float, longitude: float,
        radius_km: float, provider_list: list[str],
        min_power_kw: float, max_results: int,
    ) -> str | None:
        params: dict = {
            "key": api_key,
            "lat": latitude,
            "lng": longitude,
            "radius": int(radius_km),
            "min_power": int(min_power_kw),
            "orderby": "distance",
        }

        if provider_list:
            ge_networks = get_ge_networks(provider_list)
            if ge_networks:
                params["networks"] = ",".join(ge_networks)

        try:
            resp = requests.get(
                "https://api.goingelectric.de/chargepoints/",
                params=params, timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            return None

        if data.get("status") != "ok":
            return None

        locations = data.get("chargelocations", [])
        if not locations:
            return None

        # Post-filter by network name
        if provider_list:
            ge_networks_lower = {n.lower() for n in get_ge_networks(provider_list)}
            locations = [
                loc for loc in locations
                if (loc.get("network") or "").lower() in ge_networks_lower
            ]

        if not locations:
            return None

        lines = [
            f"=== LADESTATIONEN (Radius {radius_km}km, min {min_power_kw}kW) ===",
            f"Suche bei: {latitude:.5f},{longitude:.5f}",
            "",
        ]

        count = 0
        for loc in locations:
            if count >= max_results:
                break
            if "ge_id" not in loc:
                continue

            name = loc.get("name", "Unbekannt")
            addr = loc.get("address", {})
            street = addr.get("street", "")
            city = addr.get("city", "")
            country = addr.get("country", "")
            coords = loc.get("coordinates", {})
            lat = coords.get("lat")
            lng = coords.get("lng")
            network = loc.get("network", "Unbekannt")

            chargepoints = loc.get("chargepoints", [])
            max_power = 0
            connector_types = set()
            total_points = 0
            for cp in chargepoints:
                power = cp.get("power", 0) or 0
                if power > max_power:
                    max_power = power
                total_points += cp.get("count", 1)
                cp_type = cp.get("type", "")
                if cp_type:
                    connector_types.add(cp_type)

            connectors_str = ", ".join(sorted(connector_types)) if connector_types else "unbekannt"

            lines += [
                f"--- Station {count + 1} ---",
                f"Name:        {name}",
                f"Anbieter:    {network}",
                f"Adresse:     {street}, {city} {country}",
                f"Koordinaten: {lat},{lng}",
                f"Max. Leistung: {max_power} kW",
                f"Ladepunkte:  {total_points}",
                f"Stecker:     {connectors_str}",
                "",
            ]
            count += 1

        return "\n".join(lines) if count > 0 else None

    # ── OpenChargeMap (Fallback) ────────────────────────────────────────

    def _search_openchargemap(
        self, api_key: str, latitude: float, longitude: float,
        radius_km: float, provider_list: list[str],
        min_power_kw: float, max_results: int,
    ) -> str | None:
        params: dict = {
            "output": "json",
            "latitude": latitude,
            "longitude": longitude,
            "distance": radius_km,
            "distanceunit": "KM",
            "maxresults": max(max_results * 5, 50),
            "minpowerkw": min_power_kw,
            "compact": "true",
            "verbose": "false",
            "key": api_key,
        }

        if provider_list:
            operator_ids = get_operator_ids(provider_list)
            if operator_ids:
                params["operatorid"] = ",".join(str(i) for i in operator_ids)

        try:
            resp = requests.get(
                "https://api.openchargemap.io/v3/poi/",
                params=params, timeout=15,
            )
            resp.raise_for_status()
            stations = resp.json()
        except requests.RequestException:
            return None

        if not stations:
            return None

        # Post-filter by operator ID
        if provider_list:
            allowed_ids = set(get_operator_ids(provider_list))
            if allowed_ids:
                stations = [
                    s for s in stations
                    if (s.get("OperatorID") in allowed_ids
                        or (s.get("OperatorInfo") or {}).get("ID") in allowed_ids)
                ]

        if not stations:
            return None

        lines = [
            f"=== LADESTATIONEN (Radius {radius_km}km, min {min_power_kw}kW) ===",
            f"Suche bei: {latitude:.5f},{longitude:.5f}",
            "",
        ]

        count = 0
        for s in stations:
            if count >= max_results:
                break

            addr_info = s.get("AddressInfo", {})
            name = addr_info.get("Title", "Unbekannt")
            address = addr_info.get("AddressLine1", "")
            city = addr_info.get("Town", "")
            country = addr_info.get("Country", {}).get("ISOCode", "")
            lat = addr_info.get("Latitude")
            lng = addr_info.get("Longitude")

            op = s.get("OperatorInfo") or {}
            operator_name = op.get("Title", "Unbekannt")

            connections = s.get("Connections", [])
            power_vals = [c.get("PowerKW") for c in connections if c.get("PowerKW")]
            max_power = max(power_vals) if power_vals else "?"
            num_points = len(connections)

            conn_types = set()
            for c in connections:
                ct = (c.get("ConnectionType") or {}).get("Title", "")
                if ct:
                    conn_types.add(ct)
            connectors_str = ", ".join(sorted(conn_types)) if conn_types else "unbekannt"

            lines += [
                f"--- Station {count + 1} ---",
                f"Name:        {name}",
                f"Anbieter:    {operator_name}",
                f"Adresse:     {address}, {city} {country}",
                f"Koordinaten: {lat},{lng}",
                f"Max. Leistung: {max_power} kW",
                f"Ladepunkte:  {num_points}",
                f"Stecker:     {connectors_str}",
                "",
            ]
            count += 1

        return "\n".join(lines) if count > 0 else None
