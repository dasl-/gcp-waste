"""Permission checking with remediation hints."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rich.console import Console

logger = logging.getLogger(__name__)


@dataclass
class PermissionHint:
    """Information about a required permission."""

    permission: str
    resource_types: list[str]
    message: str
    fix: str


# Permission requirements and remediation hints
PERMISSION_HINTS: list[PermissionHint] = [
    PermissionHint(
        permission="monitoring.viewer",
        resource_types=["compute", "bigtable", "storage"],
        message="Cannot query resource metrics",
        fix=(
            "gcloud projects add-iam-policy-binding {project} "
            "--member=user:$(gcloud config get-value account) "
            "--role=roles/monitoring.viewer"
        ),
    ),
    PermissionHint(
        permission="compute.viewer",
        resource_types=["compute"],
        message="Skipping Compute VM scan",
        fix=(
            "gcloud projects add-iam-policy-binding {project} "
            "--member=user:$(gcloud config get-value account) "
            "--role=roles/compute.viewer"
        ),
    ),
    PermissionHint(
        permission="bigtable.viewer",
        resource_types=["bigtable"],
        message="Skipping Bigtable cluster scan",
        fix=(
            "gcloud projects add-iam-policy-binding {project} "
            "--member=user:$(gcloud config get-value account) "
            "--role=roles/bigtable.viewer"
        ),
    ),
    PermissionHint(
        permission="storage.viewer",
        resource_types=["storage"],
        message="Skipping Cloud Storage bucket scan",
        fix=(
            "gcloud projects add-iam-policy-binding {project} "
            "--member=user:$(gcloud config get-value account) "
            "--role=roles/storage.objectViewer"
        ),
    ),
    PermissionHint(
        permission="billing.viewer",
        resource_types=["compute", "bigtable", "storage"],
        message="Cost estimates will use cached prices (may be outdated)",
        fix=(
            "gcloud billing accounts add-iam-policy-binding BILLING_ACCOUNT_ID "
            "--member=user:$(gcloud config get-value account) "
            "--role=roles/billing.viewer"
        ),
    ),
]


class PermissionChecker:
    """Check and report missing permissions with remediation hints."""

    def __init__(self, project: str):
        self.project = project

    def check_and_warn_all(
        self, resource_type: str, console: Console | None = None
    ) -> None:
        """Print warnings for permissions that may be needed.

        This doesn't actually test permissions (that happens when the API call
        is made). It provides upfront guidance about what permissions are needed.
        """
        if console is None:
            console = Console()

        types_to_check = (
            ["compute", "bigtable", "storage"]
            if resource_type == "all"
            else [resource_type]
        )

        relevant_hints = [
            hint
            for hint in PERMISSION_HINTS
            if any(t in hint.resource_types for t in types_to_check)
        ]

        if relevant_hints:
            logger.debug(
                "Required permissions for scanning %s: %s",
                ", ".join(types_to_check),
                ", ".join(h.permission for h in relevant_hints),
            )

    def format_permission_error(self, permission: str) -> str:
        """Format a permission error with remediation hint."""
        for hint in PERMISSION_HINTS:
            if hint.permission == permission:
                fix = hint.fix.format(project=self.project)
                return (
                    f"Missing permission: {permission}\n"
                    f"  -> {hint.message}\n"
                    f"  -> To enable: {fix}"
                )
        return f"Missing permission: {permission}"
