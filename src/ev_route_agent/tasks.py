from crewai import Task, Agent


def create_route_analysis_task(agent: Agent, route_input: dict) -> Task:
    """
    Task 1: Geocode all addresses and determine charging stop locations.
    """
    user_waypoints = route_input.get("waypoints", "").strip()
    waypoint_steps = ""
    waypoint_output = ""
    if user_waypoints:
        wp_list = [w.strip() for w in user_waypoints.split(",") if w.strip()]
        geocode_steps = []
        for idx, wp in enumerate(wp_list):
            step_num = 3 + idx
            geocode_steps.append(
                f"Step {step_num}: Call geocode_address with address=\"{wp}\" (user waypoint)"
            )
        waypoint_steps = "\n".join(geocode_steps) + "\n"
        waypoint_output = (
            f"  USER_WAYPOINTS: {len(wp_list)}\n"
            f"  WAYPOINT 1: [lat],[lng] ([name])\n"
        )
        route_step = 3 + len(wp_list)
    else:
        route_step = 3

    return Task(
        description=(
            f"You MUST call tools before giving a Final Answer. "
            f"Do NOT give a Final Answer until you have tool results.\n\n"
            f"Step 1: Call geocode_address with address=\"{route_input['origin']}\"\n"
            f"Step 2: Call geocode_address with address=\"{route_input['destination']}\"\n"
            f"{waypoint_steps}"
            f"Step {route_step}: Call analyze_route_and_find_charging_locations with:\n"
            f"  - origin_coords: the lat,lng from step 1\n"
            f"  - destination_coords: the lat,lng from step 2\n"
            f"  - range_km: {route_input['range_km']}\n"
            f"  - safety_buffer_pct: 0.15\n\n"
            f"Step {route_step + 1}: Format the output EXACTLY like this:\n"
            f"  TOTAL_DISTANCE: [X] km\n"
            f"  START: [lat],[lng]\n"
            f"  DESTINATION: [lat],[lng]\n"
            f"{waypoint_output}"
            f"  CHARGING_STOPS: [N]\n"
            f"  STOP 1: [lat],[lng] (after approx [X] km)\n"
            f"  STOP 2: [lat],[lng] (after approx [X] km)\n"
        ),
        expected_output=(
            "Structured output with TOTAL_DISTANCE, START coordinates, "
            "DESTINATION coordinates, and STOP coordinates as lat,lng."
        ),
        agent=agent,
    )


def create_charging_station_task(agent: Agent, context_tasks: list, route_input: dict) -> Task:
    """
    Task 2: Find the best charging stations at each required stop location.
    The tool already has the provider filter hardcoded - agent just needs lat/lng.
    """
    return Task(
        description=(
            f"You MUST call tools before giving a Final Answer. "
            f"Do NOT give a Final Answer until you have tool results.\n\n"
            f"Read the STOP coordinates from the previous task context.\n\n"
            f"For EACH stop coordinate, call find_charging_stations with:\n"
            f"  - latitude: the stop's latitude\n"
            f"  - longitude: the stop's longitude\n"
            f"  - radius_km: 50\n\n"
            f"The tool automatically filters by the correct providers.\n\n"
            f"Then pick the best station per stop and output:\n"
            f"  STATION 1: [name]\n"
            f"  PROVIDER: [name]\n"
            f"  COORDS: [lat],[lng]\n"
            f"  POWER: [X] kW"
        ),
        expected_output=(
            "List of charging stations with name, provider, "
            "GPS coordinates (lat,lng), and power in kW per stop."
        ),
        agent=agent,
        context=context_tasks,
    )


def create_provider_qa_task(agent: Agent, context_tasks: list, route_input: dict) -> Task:
    """
    Task 3: Validate that all stations match the user's preferred providers.
    """
    providers_str = route_input.get("preferred_providers", "")
    if not providers_str:
        return Task(
            description=(
                "No provider filter was set by the user. "
                "Simply pass through all stations from the previous task unchanged."
            ),
            expected_output=(
                "The same list of stations from the previous task, unchanged."
            ),
            agent=agent,
            context=context_tasks,
        )

    provider_list = [p.strip() for p in providers_str.split(",") if p.strip()]

    return Task(
        description=(
            f"The user ONLY wants stations from these providers: {provider_list}\n\n"
            f"Review each station from the previous task context.\n"
            f"For each station, check if its PROVIDER/operator name matches one of: {provider_list}\n\n"
            f"Rules:\n"
            f"- If a station's provider IS in the list -> keep it, output it unchanged.\n"
            f"- If a station's provider is NOT in the list -> REJECT it and call "
            f"find_charging_stations with the stop's latitude and longitude (radius_km=50). "
            f"The tool automatically filters by the correct providers.\n"
            f"  Then pick a matching station from the results.\n\n"
            f"- If no matching station is found, note it as 'NO MATCHING STATION' for that stop.\n\n"
            f"Output the final validated list in the same format:\n"
            f"  STATION [N]: [name]\n"
            f"  PROVIDER: [name]\n"
            f"  COORDS: [lat],[lng]\n"
            f"  POWER: [X] kW"
        ),
        expected_output=(
            "Validated list of charging stations where every station's provider "
            "matches the user's preferences."
        ),
        agent=agent,
        context=context_tasks,
    )


def create_route_building_task(agent: Agent, context_tasks: list, route_input: dict) -> Task:
    """
    Task 4: Build the final Google Maps URL with all stops in order.
    """
    user_waypoints = route_input.get("waypoints", "").strip()
    if user_waypoints:
        waypoint_instruction = (
            f"IMPORTANT: The user has specified these intermediate stops: {user_waypoints}\n"
            f"You MUST include them as waypoints IN ADDITION to charging station coordinates.\n"
            f"Use the geocoded coordinates from the route analysis context for these stops.\n"
            f"Order all waypoints geographically along the route (user stops + charging stops).\n\n"
        )
    else:
        waypoint_instruction = ""

    return Task(
        description=(
            f"You MUST call tools before giving a Final Answer. "
            f"Do NOT give a Final Answer until you have tool results.\n\n"
            f"Read the COORDS of each charging station from the previous task context.\n\n"
            f"{waypoint_instruction}"
            f"Call build_google_maps_link with:\n"
            f"  - origin: \"{route_input['origin']}\"\n"
            f"  - destination: \"{route_input['destination']}\"\n"
            f"  - waypoints: all waypoints (user stops + charging stations) joined with | "
            f"(e.g. \"48.1,11.5|49.2,12.3\")\n\n"
            f"Then output the Google Maps link from the tool result."
        ),
        expected_output=(
            "A Google Maps link with all user stops and charging stops as waypoints."
        ),
        agent=agent,
        context=context_tasks,
    )
