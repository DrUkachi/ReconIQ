from app.services.web_auth import (
    display_name,
    mask_email,
    normalize_email,
    web_user_key,
    web_workspace_key,
    workspace_name,
)


def test_normalize_email_lowercases_and_trims():
    assert normalize_email("  Finance.Team@Example.com ") == "finance.team@example.com"


def test_mask_email_retains_only_a_small_prefix():
    assert mask_email("analyst@example.com") == "an*****@example.com"


def test_web_identity_keys_fit_existing_database_columns():
    assert len(web_workspace_key("analyst@example.com")) == 32
    assert len(web_user_key("analyst@example.com")) == 32


def test_display_name_and_workspace_name_fall_back_cleanly():
    assert display_name(None, "north.wind@example.com") == "North Wind"
    assert workspace_name(None, "north.wind@example.com") == "Example Workspace"
