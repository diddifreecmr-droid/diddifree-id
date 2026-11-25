from scripts.provision_diddimap_clients import DIDDIMAP_CLIENTS


def test_diddimap_client_policies_match_the_cross_module_contract():
    policies = {spec.service_name: spec.scopes for spec in DIDDIMAP_CLIENTS}

    assert policies == {
        "diddigo": (
            "diddimap:routing:read",
            "diddimap:geocoding:read",
            "diddimap:traces:write",
        ),
        "diddisend": (
            "diddimap:routing:read",
            "diddimap:geocoding:read",
        ),
        "backoffice": (
            "diddimap:reports:read",
            "diddimap:reports:decide",
            "diddimap:insights:read",
            "diddimap:insights:decide",
        ),
        "pilotage": ("diddimap:pilotage:read",),
    }


def test_diddimap_client_ids_are_environment_specific():
    assert DIDDIMAP_CLIENTS[0].client_id("staging") == "diddigo-staging-diddimap"
    assert DIDDIMAP_CLIENTS[0].client_id("production") == "diddigo-production-diddimap"
