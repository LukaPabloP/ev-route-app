from crewai import Crew, Process

from ev_route_agent.agents import (
    create_route_planner_agent,
    create_charging_specialist_agent,
    create_provider_qa_agent,
    create_route_builder_agent,
)
from ev_route_agent.tasks import (
    create_route_analysis_task,
    create_charging_station_task,
    create_provider_qa_task,
    create_route_building_task,
)


def create_ev_route_crew(route_input: dict) -> Crew:
    """
    Creates and returns the EV Route Planning Crew.

    route_input dict keys:
        origin              (str)  – Start address
        destination         (str)  – Destination address
        range_km            (float) – Current EV range in km
        waypoints           (str, optional) – Comma-separated user waypoints
        preferred_providers (str, optional) – Comma-separated provider names
        min_power_kw        (float, optional) – Minimum charging power, default 50
    """
    # Parse provider list ONCE and inject into tools deterministically
    providers_str = route_input.get("preferred_providers", "")
    forced_providers = (
        [p.strip() for p in providers_str.split(",") if p.strip()]
        if providers_str
        else []
    )

    # ── Agents ────────────────────────────────────────────────────────────
    route_planner       = create_route_planner_agent()
    charging_specialist = create_charging_specialist_agent(forced_providers=forced_providers)
    provider_qa         = create_provider_qa_agent(forced_providers=forced_providers)
    route_builder       = create_route_builder_agent()

    # ── Tasks (sequential – each depends on the previous) ─────────────────
    task_analyze  = create_route_analysis_task(route_planner, route_input)
    task_stations = create_charging_station_task(charging_specialist, [task_analyze], route_input)
    task_qa       = create_provider_qa_task(provider_qa, [task_analyze, task_stations], route_input)
    task_build    = create_route_building_task(route_builder, [task_analyze, task_qa], route_input)

    # ── Crew ──────────────────────────────────────────────────────────────
    return Crew(
        agents=[route_planner, charging_specialist, provider_qa, route_builder],
        tasks=[task_analyze, task_stations, task_qa, task_build],
        process=Process.sequential,
        verbose=True,
    )
