"""Checker registry for resource type extensibility."""

from __future__ import annotations

from typing import TYPE_CHECKING

from waste.checkers.bigtable import BigtableChecker
from waste.checkers.compute import ComputeChecker
from waste.checkers.storage import StorageChecker

if TYPE_CHECKING:
    from waste.checkers.base import BaseChecker

CHECKER_REGISTRY: dict[str, type[BaseChecker]] = {
    "compute": ComputeChecker,
    "bigtable": BigtableChecker,
    "storage": StorageChecker,
}
