from scripts.provision_diddiadmin_diddisupport_client import (
    SCOPES,
    SERVICE_NAME,
    TARGET_AUDIENCE,
    client_id_for,
)


def test_diddiadmin_diddisupport_client_policy_is_minimal():
    assert SERVICE_NAME == "diddiadmin"
    assert TARGET_AUDIENCE == "diddi-support"
    assert SCOPES == (
        "diddi-support:read",
        "diddi-support:write",
    )


def test_diddiadmin_diddisupport_client_is_environment_scoped():
    assert client_id_for("staging") == "backoffice-staging-diddisupport"
    assert client_id_for("production") == "backoffice-production-diddisupport"
