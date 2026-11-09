import copy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from linkdown.gate import Gate  # noqa: E402
from linkdown.scenario import apply_variation, load_variations, load_yaml  # noqa: E402
from linkdown.sim import Topology  # noqa: E402
from linkdown.state import ExerciseState  # noqa: E402


@pytest.fixture
def base_scenario():
    return load_yaml(ROOT / "scenarios/base.yaml")


@pytest.fixture
def variations():
    return load_variations(ROOT / "scenarios/variations.yaml")


@pytest.fixture
def topo():
    return Topology.load(ROOT / "config/topology.yaml")


@pytest.fixture
def rules():
    return yaml.safe_load((ROOT / "config/rules.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def gate(rules):
    return Gate(rules)


FIXTURE_SHA = "ab" * 32      # TEST FIXTURE hash, not a real document


def verified_bundle(rules):
    """(rules, ledger, manifest) as if two people had checked every NCSP clause in the
    primary PDF. TEST FIXTURE ONLY: the names and the hash are not real verifications."""
    r = copy.deepcopy(rules)
    entries = []
    for rule in r["legal"]:
        if rule["source"] == "uae-ncsp-v2-2025":
            rule["verification"] = "primary_verified"
            rule["ledger"] = f"FX-{rule['id']}"
            entries.append({"id": rule["ledger"], "source_id": "uae-ncsp-v2-2025", "section": "FIXTURE",
                            "page": 1, "quote": "FIXTURE QUOTE", "verified_by": ["FIXTURE-A", "FIXTURE-B"],
                            "verified_on": "2026-10-23", "source_sha256": FIXTURE_SHA})
    return r, {"entries": entries}, {"uae-ncsp-v2-2025": {"sha256": FIXTURE_SHA}}


@pytest.fixture
def verified_gate(rules):
    return Gate(*verified_bundle(rules))


def make_state(base, variation=None):
    sc = apply_variation(base, variation)
    return ExerciseState.from_scenario(Topology.load(ROOT / "config/topology.yaml"), sc), sc
