"""
core/registry.py
================
Discovers all GCPNode subclasses under the `nodes` package and exposes them
as a dict[str, type].

Import NODE_REGISTRY wherever you need to look up a node class by name.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil

import nodes
from nodes.base_node import GCPNode

logger = logging.getLogger(__name__)


def _discover() -> dict[str, type]:
    registry: dict[str, type] = {}
    for _loader, module_name, _is_pkg in pkgutil.walk_packages(
        nodes.__path__, nodes.__name__ + "."
    ):
        module = importlib.import_module(module_name)
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, GCPNode) and obj is not GCPNode:
                registry[name] = obj
                logger.debug("Registered node: %s (from %s)", name, module_name)
    return registry


NODE_REGISTRY: dict[str, type] = _discover()
logger.info("Node registry loaded: %d types → %s", len(NODE_REGISTRY), list(NODE_REGISTRY.keys()))
