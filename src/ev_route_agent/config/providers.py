# ─────────────────────────────────────────────────────────────────
# Charging Provider Configuration
# Maps display names to API-specific identifiers
# ─────────────────────────────────────────────────────────────────

# OpenChargeMap Operator IDs
# Source: https://api.openchargemap.io/v3/referencedata/
OCM_OPERATOR_IDS: dict[str, list[int]] = {
    "IONITY":              [3299],
    "Tesla Supercharger":  [23, 3534],
    "EnBW mobility+":      [86],
    "Allego":              [103],
    "Fastned":             [74],
    "Maingau Energie":     [],
    "Lidl":                [38],
    "ARAL Pulse":          [3455],
    "Shell Recharge":      [156, 47, 157],
    "Aldi Sued":           [3464],
    "E.ON Drive":          [3403, 46],
    "EWE Go":              [127],
    "Recharge (Vattenfall)": [198, 108],
    "Total Energies":      [3447, 25],
    "Smatrics":            [3253],
    "Wien Energie":        [142],
}

# GoingElectric network names – verified via networklist endpoint
GE_NETWORK_NAMES: dict[str, list[str]] = {
    "IONITY":              ["IONITY"],
    "Tesla Supercharger":  ["Tesla Supercharger"],
    "EnBW mobility+":      ["EnBW", "EnBW ODR"],
    "Allego":              ["allego"],
    "Fastned":             ["Fastned"],
    "Maingau Energie":     ["Maingau Energie"],
    "Lidl":                ["Lidl"],
    "ARAL Pulse":          ["Aral pulse"],
    "Shell Recharge":      ["Shell Recharge", "Shell Recharge FR"],
    "Aldi Sued":           ["ALDI S\u00fcd", "ALDI Nord"],
    "E.ON Drive":          ["E.ON"],
    "EWE Go":              ["EWE Go", "EWE Go Hochtief"],
    "Recharge (Vattenfall)": ["Recharge", "Vattenfall"],
    "Total Energies":      ["Total EV Charge"],
    "Smatrics":            ["Smatrics"],
    "Wien Energie":        ["TANKE WienEnergie"],
}

# Backward-compatible alias
CHARGING_PROVIDERS = OCM_OPERATOR_IDS

# Bundesnetzagentur operator name patterns (for SQL LIKE queries)
BNA_OPERATOR_PATTERNS: dict[str, list[str]] = {
    "IONITY":              ["IONITY"],
    "Tesla Supercharger":  ["Tesla"],
    "EnBW mobility+":      ["EnBW"],
    "Allego":              ["Allego"],
    "Fastned":             ["Fastned"],
    "Maingau Energie":     ["Maingau"],
    "Lidl":                ["Lidl"],
    "ARAL Pulse":          ["Aral"],
    "Shell Recharge":      ["Shell"],
    "Aldi Sued":           ["ALDI"],
    "E.ON Drive":          ["E.ON"],
    "EWE Go":              ["EWE"],
    "Recharge (Vattenfall)": ["Vattenfall", "Recharge"],
    "Total Energies":      ["Total"],
    "Smatrics":            ["SMATRICS"],
    "Wien Energie":        ["Wien Energie"],
}

# Providers that support HPC (High Power Charging, >= 150 kW)
HPC_PROVIDERS = {"IONITY", "Tesla Supercharger", "Fastned", "ARAL Pulse", "Allego"}


def get_operator_ids(provider_names: list[str]) -> list[int]:
    """Returns OCM operator IDs for a list of provider names."""
    ids = []
    for name in provider_names:
        if name in OCM_OPERATOR_IDS:
            ids.extend(OCM_OPERATOR_IDS[name])
            continue
        for key, val in OCM_OPERATOR_IDS.items():
            if name.lower() in key.lower():
                ids.extend(val)
                break
    return ids


def get_ge_networks(provider_names: list[str]) -> list[str]:
    """Returns GoingElectric network names for a list of provider names."""
    networks = []
    for name in provider_names:
        if name in GE_NETWORK_NAMES:
            networks.extend(GE_NETWORK_NAMES[name])
            continue
        for key, val in GE_NETWORK_NAMES.items():
            if name.lower() in key.lower():
                networks.extend(val)
                break
    return networks


def get_bna_patterns(provider_names: list[str]) -> list[str]:
    """Returns BNA operator LIKE patterns for a list of provider names."""
    patterns = []
    for name in provider_names:
        if name in BNA_OPERATOR_PATTERNS:
            patterns.extend(BNA_OPERATOR_PATTERNS[name])
            continue
        for key, val in BNA_OPERATOR_PATTERNS.items():
            if name.lower() in key.lower():
                patterns.extend(val)
                break
    return patterns


def list_all_providers() -> str:
    """Returns a formatted list of all available providers."""
    lines = ["Verfuegbare Ladeanbieter:\n"]
    for i, name in enumerate(OCM_OPERATOR_IDS, 1):
        hpc = "HPC" if name in HPC_PROVIDERS else ""
        lines.append(f"  {i:2}. {name} {hpc}")
    return "\n".join(lines)
