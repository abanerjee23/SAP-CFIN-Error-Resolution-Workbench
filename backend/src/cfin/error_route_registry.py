"""Code-owned route policy lookup for Error Analysis.

The model may choose a category, but this module is the only place that turns a
category into ownership, approvals, route steps or escalation. Production uses
the versioned Supabase registry; the in-memory registry makes the same policy
testable without cloud credentials.
"""

from collections.abc import Mapping
from typing import Any, Protocol

from cfin.error_analysis_contracts import (
    ErrorCategoryId,
    RouteDefinition,
    RouteStep,
    TaxonomyCategory,
)
from cfin.gateway import ServiceGateway

TAXONOMY: tuple[TaxonomyCategory, ...] = (
    TaxonomyCategory(
        category_id="master_data",
        label="Master-data failure",
        definition=(
            "A required master-data record, value or maintained target context may be unavailable."
        ),
        pilot_active=True,
    ),
    TaxonomyCategory(
        category_id="mapping",
        label="Mapping failure",
        definition="A required source-to-target mapping may be missing or incorrect.",
        pilot_active=True,
    ),
    TaxonomyCategory(
        category_id="integration_mapping",
        label="Integration or organisational mapping discrepancy",
        definition="Interface or organisational mapping context does not align.",
        pilot_active=False,
    ),
    TaxonomyCategory(
        category_id="master_data_restriction",
        label="Master-data validity, restriction or block",
        definition="A master-data validity, restriction or block may prevent processing.",
        pilot_active=False,
    ),
    TaxonomyCategory(
        category_id="posting_period",
        label="Posting-period failure",
        definition="The reported posting period cannot be used for the attempted posting.",
        pilot_active=False,
    ),
    TaxonomyCategory(
        category_id="tax",
        label="Tax failure",
        definition="Tax determination or tax data causes the reported exception.",
        pilot_active=False,
    ),
    TaxonomyCategory(
        category_id="currency",
        label="Currency or exchange-rate failure",
        definition="Currency or exchange-rate information causes the reported exception.",
        pilot_active=False,
    ),
    TaxonomyCategory(
        category_id="document_splitting",
        label="Document-splitting failure",
        definition="Document splitting causes the reported exception.",
        pilot_active=False,
    ),
    TaxonomyCategory(
        category_id="account_assignment",
        label="Account-assignment failure",
        definition="Account assignment causes the reported exception.",
        pilot_active=False,
    ),
    TaxonomyCategory(
        category_id="technical_interface",
        label="Technical or interface failure",
        definition="A technical or interface condition causes the reported exception.",
        pilot_active=False,
    ),
)


class RouteRegistry(Protocol):
    async def get_error_route(
        self,
        workspace_id: str,
        category_id: ErrorCategoryId,
        context: Mapping[str, str] | None = None,
    ) -> RouteDefinition: ...


def taxonomy_payload() -> list[dict[str, Any]]:
    return [category.model_dump(mode="json") for category in TAXONOMY]


def _route(category_id: ErrorCategoryId) -> RouteDefinition:
    if category_id == "master_data":
        steps = (
            RouteStep(
                order=1,
                step_id="request_approval",
                kind="request_process_owner_approval",
                description=(
                    "MDG Process Owner tags the relevant Process Owner in the case-log "
                    "conversation to request approval."
                ),
                required_role="mdg_process_owner",
            ),
            RouteStep(
                order=2,
                step_id="process_owner_approval",
                kind="record_process_owner_decision",
                description=(
                    "The relevant Process Owner approves or rejects in the same case-log "
                    "conversation."
                ),
                required_role="process_owner",
                requires_approval=True,
            ),
            RouteStep(
                order=3,
                step_id="create_data",
                kind="create_master_data",
                description="After recorded approval, MDG Process Owner creates the required data.",
                required_role="mdg_process_owner",
                requires_approval=True,
            ),
            RouteStep(
                order=4,
                step_id="implementation_evidence",
                kind="upload_implementation_evidence",
                description=(
                    "MDG Process Owner uploads implementation evidence to the case history."
                ),
                required_role="mdg_process_owner",
                requires_evidence=True,
            ),
            RouteStep(
                order=5,
                step_id="reprocessing_go_ahead",
                kind="record_reprocessing_go_ahead",
                description="MDG Process Owner records the reprocessing go-ahead.",
                required_role="mdg_process_owner",
                requires_evidence=True,
            ),
            RouteStep(
                order=6,
                step_id="reprocess",
                kind="reprocess_document",
                description="Data Operations reprocesses the document.",
                required_role="data_operations",
            ),
            RouteStep(
                order=7,
                step_id="posting_outcome",
                kind="record_posting_outcome",
                description=(
                    "Data Operations records the CFIN posting reference or failure evidence."
                ),
                required_role="data_operations",
                requires_evidence=True,
            ),
        )
        return RouteDefinition(
            policy_id="seed-master-data",
            policy_version=1,
            category_id=category_id,
            route_kind="pilot",
            owner_role="mdg_process_owner",
            steps=steps,
        )
    if category_id == "mapping":
        steps = (
            RouteStep(
                order=1,
                step_id="confirm_mapping",
                kind="confirm_mapping_with_process_owner",
                description=(
                    "MDG Process Owner confirms the correct mapping with the relevant Process "
                    "Owner in the case-log conversation."
                ),
                required_role="mdg_process_owner",
            ),
            RouteStep(
                order=2,
                step_id="maintain_mapping",
                kind="maintain_mapping",
                description=(
                    "MDG Process Owner maintains the mapping and records changed scope "
                    "and evidence."
                ),
                required_role="mdg_process_owner",
                requires_evidence=True,
            ),
            RouteStep(
                order=3,
                step_id="mapping_approval",
                kind="review_and_approve_mapping",
                description=(
                    "The relevant Process Owner reviews and approves the mapping change in the "
                    "case-log conversation."
                ),
                required_role="process_owner",
                requires_approval=True,
            ),
            RouteStep(
                order=4,
                step_id="reprocess",
                kind="reprocess_document",
                description="Data Operations reprocesses the document.",
                required_role="data_operations",
            ),
            RouteStep(
                order=5,
                step_id="posting_outcome",
                kind="record_posting_outcome",
                description=(
                    "Data Operations records the CFIN posting reference or failure evidence."
                ),
                required_role="data_operations",
                requires_evidence=True,
            ),
        )
        return RouteDefinition(
            policy_id="seed-mapping",
            policy_version=1,
            category_id=category_id,
            route_kind="pilot",
            owner_role="mdg_process_owner",
            steps=steps,
        )
    if category_id == "unclassified":
        return RouteDefinition(
            policy_id="seed-unclassified",
            policy_version=1,
            category_id=category_id,
            route_kind="unclassified",
            owner_role="cfin_exception_manager",
            steps=(
                RouteStep(
                    order=1,
                    step_id="manual_investigation",
                    kind="manual_investigation",
                    description="CFIN Exception Manager assigns a human investigation owner.",
                    required_role="cfin_exception_manager",
                ),
            ),
        )
    return RouteDefinition(
        policy_id="seed-manual-" + category_id,
        policy_version=1,
        category_id=category_id,
        route_kind="manual",
        owner_role="cfin_exception_manager",
        steps=(
            RouteStep(
                order=1,
                step_id="manual_investigation",
                kind="manual_investigation",
                description="CFIN Exception Manager assigns a human investigation owner.",
                required_role="cfin_exception_manager",
            ),
        ),
    )


class InMemoryRouteRegistry:
    async def get_error_route(
        self,
        workspace_id: str,
        category_id: ErrorCategoryId,
        context: Mapping[str, str] | None = None,
    ) -> RouteDefinition:
        if not workspace_id.strip():
            raise ValueError("Workspace scope is required for route lookup")
        return _route(category_id)


class SupabaseRouteRegistry:
    def __init__(self, cloud: ServiceGateway):
        self.cloud = cloud

    async def get_error_route(
        self,
        workspace_id: str,
        category_id: ErrorCategoryId,
        context: Mapping[str, str] | None = None,
    ) -> RouteDefinition:
        response = await self.cloud.rpc(
            "cfin_get_error_route",
            {
                "workspace_id": workspace_id,
                "category_id": category_id,
                "routing_context": dict(context or {}),
            },
        )
        return RouteDefinition.model_validate(response)
