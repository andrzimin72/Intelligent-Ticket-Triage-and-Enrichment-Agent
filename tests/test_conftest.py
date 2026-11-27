import pytest
import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture(scope="session")
def test_data():
    """Load general test data."""
    with open(FIXTURES_DIR / "test_data.json") as f:
        return json.load(f)

@pytest.fixture(scope="session")
def teams_activities():
    """Load sample Teams activities."""
    with open(FIXTURES_DIR / "sample_teams_activity.json") as f:
        data = json.load(f)
        # Remove metadata key
        return {k: v for k, v in data.items() if not k.startswith("_")}

@pytest.fixture(scope="session")
def agent_responses():
    """Load sample agent responses."""
    with open(FIXTURES_DIR / "sample_agent_response.json") as f:
        data = json.load(f)
        return {k: v for k, v in data.items() if not k.startswith("_")}

@pytest.fixture(scope="session")
def ticket_dataset():
    """Load ticket classification dataset."""
    with open(FIXTURES_DIR / "ticket_dataset.json") as f:
        return json.load(f)

@pytest.fixture
def sample_tenant(test_data):
    """Get a sample active tenant."""
    return test_data["test_tenants"][0]

@pytest.fixture
def sample_user(test_data):
    """Get a sample user."""
    return test_data["test_users"][0]