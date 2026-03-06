import os
from crewai import Agent, LLM

from ev_route_agent.tools.geocode_tool import GeocodeTool
from ev_route_agent.tools.route_analysis_tool import RouteAnalysisTool
from ev_route_agent.tools.charging_station_tool import ChargingStationTool
from ev_route_agent.tools.maps_link_builder import MapsLinkBuilderTool


# ── LLM Definitions ──────────────────────────────────────────────────────────

def get_claude_llm() -> LLM:
    """Anthropic Claude Sonnet - fast, affordable, great at tool calling."""
    return LLM(
        model="anthropic/claude-sonnet-4-6",
        api_key=os.environ["ANTHROPIC_API_KEY"],
        temperature=0.2,
    )


# ── Agent Definitions ─────────────────────────────────────────────────────────

def create_route_planner_agent() -> Agent:
    return Agent(
        role="EV Route Planner",
        goal=(
            "Geocode all addresses using geocode_address, then call "
            "analyze_route_and_find_charging_locations to find charging stop positions. "
            "Output the structured result with GPS coordinates."
        ),
        backstory=(
            "You are an autonomous bot. You must ALWAYS use Action/Action Input to call tools. "
            "You must call geocode_address and analyze_route_and_find_charging_locations "
            "BEFORE giving any Final Answer. Never skip tool calls."
        ),
        tools=[GeocodeTool(), RouteAnalysisTool()],
        llm=get_claude_llm(),
        verbose=True,
        max_iter=8,
    )


def create_charging_specialist_agent(forced_providers: list[str] | None = None) -> Agent:
    """
    Agent 2: Finds the best charging stations at each required stop.
    The provider filter is HARDCODED in the tool — the agent cannot override it.
    """
    tool = ChargingStationTool(forced_providers=forced_providers)
    return Agent(
        role="Charging Station Specialist",
        goal=(
            "For each charging stop coordinate from the context, call find_charging_stations "
            "with latitude and longitude. The tool automatically filters by the correct providers. "
            "Pick the best station per stop and output the result."
        ),
        backstory=(
            "You are an autonomous bot. You must ALWAYS use Action/Action Input to call tools. "
            "You must call find_charging_stations for each stop coordinate "
            "BEFORE giving any Final Answer. Never skip tool calls."
        ),
        tools=[tool],
        llm=get_claude_llm(),
        verbose=True,
        max_iter=10,
    )


def create_provider_qa_agent(forced_providers: list[str] | None = None) -> Agent:
    """
    Agent 3: Validates that all selected stations match the user's provider filter.
    The tool has the same hardcoded filter for re-searching.
    """
    tool = ChargingStationTool(forced_providers=forced_providers)
    return Agent(
        role="Provider Quality Checker",
        goal=(
            "Verify that every charging station matches the user's preferred providers. "
            "For any station that does NOT match, call find_charging_stations again "
            "with the stop's coordinates to find a replacement. "
            "Output only stations that match the user's preferences."
        ),
        backstory=(
            "You are a strict quality assurance bot. You compare each station's provider "
            "against the user's allowed list. If a station's provider is not in the list, "
            "you MUST replace it by calling find_charging_stations with the stop's coordinates. "
            "The tool automatically filters by the correct providers. "
            "You never let a non-matching provider through."
        ),
        tools=[tool],
        llm=get_claude_llm(),
        verbose=True,
        max_iter=10,
    )


def create_route_builder_agent() -> Agent:
    return Agent(
        role="Route Builder",
        goal=(
            "Read the charging station coordinates from the context and immediately call "
            "build_google_maps_link to create the final route URL."
        ),
        backstory=(
            "You are an autonomous bot. You must ALWAYS use Action/Action Input to call tools. "
            "You must call build_google_maps_link BEFORE giving any Final Answer. "
            "Use GPS coordinates from context as pipe-separated waypoints. Never skip tool calls."
        ),
        tools=[MapsLinkBuilderTool()],
        llm=get_claude_llm(),
        verbose=True,
        max_iter=5,
    )
