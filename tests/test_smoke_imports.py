"""Import smoke test for every agent submodule."""

import importlib
import pkgutil

import pytest

import agent

# Discovered dynamically: modules come and go, a hardcoded list rots.
AGENT_MODULES = sorted(m.name for m in pkgutil.walk_packages(agent.__path__, "agent."))


@pytest.mark.parametrize("module_name", AGENT_MODULES)
def test_agent_submodule_imports(module_name):
    importlib.import_module(module_name)
