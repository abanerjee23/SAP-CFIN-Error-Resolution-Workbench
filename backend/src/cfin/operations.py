"""First-family private intake and human workflow commands."""

import asyncio
import base64
import binascii
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from cfin.contracts import (
    Citation,
    IntakeManifest,
    ResolutionScope,
    ValidationCheck,
    validate_citations,
)
from cfin.demo_proof import validate_demo_proof
from cfin.error_analysis_operations import (
    error_analysis_detail,
    error_workbench_action,
    is_error_analysis,
    record_error_route_step,
)
from cfin.factual_operations import factual_action, factual_detail, is_factual
from cfin.fixture_loader import AGENT_FILES, load_md01
from cfin.gateway import ServiceGateway, UserGateway
from cfin.intake import commit_intake
from cfin.snapshots import restore_inputs

ROLE = Literal[
    "process_owner",
    "mapping_owner",
    "master_data_owner",
    "finance_owner",
    "validator",
    "mdg_process_owner",
    "data_operations",
    "cfin_exception_manager",
]


class IntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    delivery_key: str = Field(min_length=1, max_length=150)
    manifest: IntakeManifest
    original_log: str = Field(min_length=1, max_length=1_048_576)
    agent_files: dict[str, Any] | None = None
    acting_role: ROLE = "process_owner"


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    expected_version: int = Field(gt=0)
    action: Literal[
        "approve_reference",
        "analyse",
        "review_diagnosis",
        "review_summary",
        "start_investigation",
        "record_investigation",
        "start_work",
        "record_correction",
        "complete_work",
        "record_reprocessing",
        "record_validation",
        "finish_resolution",
        "assign",
        "block",
        "resume",
        "priority",
        "reopen",
        "due_date",
        "retry_notification",
        "owner_rule",
        "record_route_step",
        "comment",
        "record_approval",
        "set_status",
    ]
    acting_role: ROLE
    payload: dict[str, Any] = Field(default_factory=dict)
    request_key: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=150)


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    acting_role: ROLE
    filename: str = Field(min_length=1, max_length=150)
    content_type: Literal[
        "text/plain", "application/json", "application/pdf", "image/png", "image/jpeg",
        "message/rfc822"
    ]
    content_base64: str = Field(min_length=1, max_length=14_000_000)
    provenance: Literal["synthetic", "user_supplied"] | None = None


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    acting_role: ROLE
    kind: Literal["correction", "reprocessing", "validation"]
    human_confirmed: Literal[True]
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("human_confirmed", mode="before")
    @classmethod
    def explicit_boolean_attestation(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("Explicit boolean human confirmation is required")
        return value


def fixture_files() -> dict[str, bytes]:
    # Scenario/intake preparation only. Worker restoration never calls this helper.
    root = Path(__file__).resolve().parents[3] / "fixtures/MD-01/agent-visible"
    load_md01(root)  # Validate hash, allowlist, no symlinks and declared citations first.
    return {name: (root / name).read_bytes() for name in AGENT_FILES}


def _text(body: dict[str, Any], name: str) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > 10000:
        raise HTTPException(422, "A nonempty " + name.replace("_", " ") + " is required")
    return value


def _uuid(value: Any) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Select a valid saved record") from exc


class Operations:
    def __init__(self, user: UserGateway, service: ServiceGateway):
        self.user = user
        self.service = service

    async def get_case(self, token: str, workspace_id: UUID, case_id: UUID) -> dict[str, Any]:
        rows = await self.user.rows("cases", token, workspace_id, {"id": f"eq.{case_id}"})
        if len(rows) != 1:
            raise HTTPException(404, "Case not found")
        return rows[0]

    async def intake(self, token: str, actor_id: UUID, body: IntakeRequest) -> dict[str, Any]:
        return await commit_intake(self.user, self.service, token, actor_id, body)

    async def detail(self, token: str, workspace_id: UUID, case_id: UUID) -> dict[str, Any]:
        case = await self.get_case(token, workspace_id, case_id)
        tables = (
            "evidence_versions",
            "analysis_runs",
            "attempts",
            "milestones",
            "resolution_records",
            "activity",
            "proof_applicability",
            "milestone_proof",
            "case_reviews",
            "assignments",
            "notifications",
        )
        values = await asyncio.gather(
            *(
                self.user.rows(table, token, workspace_id, {"case_id": f"eq.{case_id}"})
                for table in tables
            )
        )
        data = dict(zip(tables, values, strict=True))
        if is_error_analysis(case):
            return await error_analysis_detail(self.user, token, workspace_id, case, data)
        if is_factual(case):
            return await factual_detail(self.user, token, workspace_id, case, data)
        reference_evidence = await self.user.rows(
            "evidence_versions", token, workspace_id, {"case_id": "is.null"}
        )
        intakes = await self.user.rows("intakes", token, workspace_id, {"case_id": f"eq.{case_id}"})
        current_intakes = [i for i in intakes if i.get("attempt_id") == case["current_attempt_id"]]
        current_intake = max(current_intakes, key=lambda i: i.get("received_at", ""), default=None)
        source_ids: set[str] = set()
        if current_intake:
            links = await self.user.rows(
                "intake_sources", token, workspace_id, {"intake_id": f"eq.{current_intake['id']}"}
            )
            source_ids = {link["evidence_id"] for link in links}
        else:
            current_run = next(
                (r for r in data["analysis_runs"] if r["id"] == case.get("requested_run_id")), None
            )
            if current_run:
                source_ids = {s["evidence"]["id"] for s in current_run["snapshot"]["sources"]}
        reference_evidence = [e for e in reference_evidence if e["id"] in source_ids]
        owner_rules = await self.user.rows(
            "owner_rules",
            token,
            workspace_id,
            {
                "category": f"eq.{case.get('category', 'cause_not_established')}",
                "target_system": f"eq.{case.get('target_system', '')}",
                "target_client": f"eq.{case.get('target_client', '')}",
                "company_code": f"eq.{case['business_context'].get('company_code', '')}",
                "chart_of_accounts": f"eq.{case['business_context'].get('chart_of_accounts', '')}",
                "interface": f"eq.{case.get('interface', '')}",
                "order": "version.desc",
                "limit": "1",
            },
        )
        reviews = await self.user.rows("reference_reviews", token, workspace_id)
        references = []
        for evidence in reference_evidence:
            if evidence["filename"] not in (
                "mapping-reference.json",
                "missing-gl-master-playbook.json",
            ):
                continue
            latest = max(
                (r for r in reviews if r["evidence_id"] == evidence["id"]),
                key=lambda r: r["version"],
                default=None,
            )
            raw = json.loads(await self.user.download(token, evidence))
            references.append(
                {
                    "evidence_id": evidence["id"],
                    "source_id": evidence["source_id"],
                    "source_version": evidence["source_version"],
                    "kind": evidence["kind"],
                    "reference_kind": "mapping" if evidence["kind"] == "reference" else "guidance",
                    "reuse_status": latest["decision"] if latest else "pending_review",
                    "review_version": latest["version"] if latest else 0,
                    "scope": raw.get("scope", raw.get("query_scope", {})),
                    "review": latest,
                }
            )
        evidence = data["evidence_versions"] + reference_evidence
        attempts = sorted(data["attempts"], key=lambda x: x.get("processing_order") or 0)
        milestones = sorted(data["milestones"], key=lambda x: x["recorded_at"])
        validations = [m for m in milestones if m["kind"] == "validation"]
        current = next((a for a in attempts if a["id"] == case["current_attempt_id"]), None)
        applicable = {
            (p["attempt_id"], p["work_cycle"], p["evidence_id"])
            for p in data["proof_applicability"]
        }
        cycle = case["work_cycle"]
        correction = next(
            (
                m
                for m in reversed(milestones)
                if m["kind"] == "correction" and m["work_cycle"] == cycle
            ),
            None,
        )
        reprocessing = next(
            (
                m
                for m in reversed(milestones)
                if m["kind"] == "reprocessing"
                and m["work_cycle"] == cycle
                and m["attempt_id"] == case["current_attempt_id"]
            ),
            None,
        )
        validation = next(
            (
                m
                for m in reversed(validations)
                if m["work_cycle"] == cycle and m["attempt_id"] == case["current_attempt_id"]
            ),
            None,
        )
        records = [
            r
            for r in data["resolution_records"]
            if r["work_cycle"] == cycle and r["attempt_id"] == case["current_attempt_id"]
        ]
        correction_proof = [
            p["evidence_id"]
            for p in data["milestone_proof"]
            if correction and p["milestone_id"] == correction["id"]
        ]
        resolved = bool(
            case["status"] == "document_reprocessed"
            and case["attempt_order_known"]
            and not case["unreviewed_new_failure"]
            and current
            and current["result"] == "successful"
            and current["validation_status"] == "passed"
            and correction
            and reprocessing
            and validation
            and validation["details"].get("status") == "passed"
            and records
            and correction_proof
            and all((case["current_attempt_id"], cycle, p) in applicable for p in correction_proof)
        )
        comparisons = None
        if current and current["result"] == "successful":
            target_proof = next(
                (
                    e
                    for e in reversed(evidence)
                    if e["provenance"].get("verified_observation", {}).get("kind") == "reprocessing"
                    and e["provenance"]["verified_observation"].get("attempt_key")
                    == current["attempt_key"]
                ),
                None,
            )
            published = next(
                (r for r in data["analysis_runs"] if r["id"] == case["published_run_id"]), None
            )
            if target_proof and published:
                saved_inputs = await restore_inputs(published["snapshot"], self.service)
                comparisons = validation_values(
                    saved_inputs, target_proof["provenance"]["verified_observation"]
                )
        return {
            "case": {**case, "resolved": resolved},
            "evidence": evidence,
            "runs": sorted(data["analysis_runs"], key=lambda x: x["created_at"], reverse=True),
            "references": references,
            "attempts": attempts,
            "milestones": milestones,
            "validations": validations,
            "resolution_records": records,
            "activity": sorted(data["activity"], key=lambda x: x["created_at"], reverse=True),
            "reviews": data["case_reviews"],
            "assignments": data["assignments"],
            "notifications": data["notifications"],
            "owner_rule": owner_rules[0] if owner_rules else None,
            "validation_comparisons": comparisons,
        }

    async def evidence(
        self, token: str, actor_id: UUID, case_id: UUID, body: EvidenceRequest
    ) -> dict[str, Any]:
        member = await self.user.require_member(
            token, actor_id, body.workspace_id, body.acting_role
        )
        case = await self.get_case(token, body.workspace_id, case_id)
        if case.get("linked_case_id"):
            raise HTTPException(409, "Use the linked canonical case")
        governed_case = is_factual(case) or is_error_analysis(case)
        provenance = body.provenance or ("user_supplied" if governed_case else "synthetic")
        if not governed_case and provenance != "synthetic":
            raise HTTPException(422, "Legacy simulation proof must be explicitly synthetic")
        if (
            provenance == "user_supplied"
            and (member or {}).get("workspaces", {}).get("synthetic") is not False
        ):
            raise HTTPException(422, "Real evidence requires an explicitly non-synthetic workspace")
        try:
            content = base64.b64decode(body.content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(422, "Evidence encoding is invalid") from exc
        if body.content_type in ("text/plain", "application/json", "message/rfc822"):
            try:
                content.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise HTTPException(422, "Text evidence must be UTF-8") from exc
        magic = {
            "application/pdf": b"%PDF-",
            "image/png": b"\x89PNG\r\n\x1a\n",
            "image/jpeg": b"\xff\xd8\xff",
        }
        if body.content_type in magic and not content.startswith(magic[body.content_type]):
            raise HTTPException(422, "Evidence type differs from its content")
        if body.content_type == "image/png":
            validate_demo_proof(content, case_id)
        storage = await self.service.store(
            body.workspace_id, content, body.filename, body.content_type
        )
        storage.update(
            source_id="human-proof-" + str(uuid4()),
            source_version="1",
            observed_at=datetime.now(UTC).isoformat(),
            provenance={
                "synthetic": provenance == "synthetic",
                "kind": provenance,
                "description": "Human-supplied evidence"
                if governed_case
                else "Human-supplied simulated proof",
            },
        )
        return await self.service.rpc(
            "cfin_register_evidence",
            {
                "actor_id": str(actor_id),
                "acting_role": body.acting_role,
                "workspace_id": str(body.workspace_id),
                "case_id": str(case_id),
                "attempt_id": case["current_attempt_id"],
                "work_cycle": case["work_cycle"],
                "kind": "proof",
                "storage": storage,
            },
        )

    async def simulate(
        self, token: str, actor_id: UUID, case_id: UUID, body: SimulationRequest
    ) -> dict[str, Any]:
        """An explicit human action invokes deterministic fictional SAP observations."""
        await self.user.require_member(token, actor_id, body.workspace_id, body.acting_role)
        case = await self.get_case(token, body.workspace_id, case_id)
        if case.get("linked_case_id"):
            raise HTTPException(409, "Use the linked canonical case")
        if is_factual(case):
            raise HTTPException(422, "Simulation is limited to compatible synthetic legacy cases")
        allowed_status = {
            "correction": "in_progress",
            "reprocessing": "complete",
            "validation": "document_reprocessed",
        }
        if case["status"] != allowed_status[body.kind]:
            raise HTTPException(409, "Complete the preceding human milestone first")
        if body.kind == "validation":
            if body.acting_role not in ("validator", "process_owner"):
                raise HTTPException(403, "Validator role required")
        elif body.acting_role != "process_owner":
            assignments = await self.user.rows(
                "assignments", token, body.workspace_id, {"case_id": f"eq.{case_id}"}
            )
            latest = max(assignments, key=lambda x: x["version"], default=None)
            if not latest or latest["assigned_user_id"] != str(actor_id):
                raise HTTPException(403, "Assigned owner or process owner required")
        runs = await self.user.rows(
            "analysis_runs", token, body.workspace_id, {"id": f"eq.{case['published_run_id']}"}
        )
        if not runs or not (runs[0].get("output") or {}).get("routing", {}).get("agent3_eligible"):
            raise HTTPException(422, "Applicable reviewed mapping and guidance are required")
        if body.kind in ("correction", "reprocessing") and (
            not case["attempt_order_known"]
            or case["unreviewed_new_failure"]
            or runs[0]["attempt_id"] != case["current_attempt_id"]
            or runs[0]["input_revision"] != case["input_revision"]
        ):
            raise HTTPException(409, "Review analysis for the current ordered attempt first")
        inputs = await restore_inputs(runs[0]["snapshot"], self.service)
        if body.kind in ("correction", "reprocessing"):
            current_reviews = await self.user.rows("reference_reviews", token, body.workspace_id)
            for source in runs[0]["snapshot"]["sources"]:
                if source["evidence"]["filename"] not in (
                    "mapping-reference.json",
                    "missing-gl-master-playbook.json",
                ):
                    continue
                latest_review = max(
                    (r for r in current_reviews if r["evidence_id"] == source["evidence"]["id"]),
                    key=lambda r: r["version"],
                    default=None,
                )
                if (
                    not latest_review
                    or latest_review["decision"] != "approved"
                    or latest_review["id"] != (source.get("review") or {}).get("id")
                ):
                    raise HTTPException(409, "Reference approval changed; review a fresh analysis")
            from cfin.workflow import build_diagnosis

            if not any(f.supported for f in build_diagnosis(inputs, "simulation-scope").findings):
                raise HTTPException(422, "Cause evidence is no longer applicable")
            if any(
                g.expires_on and g.expires_on < datetime.now(UTC).date() for g in inputs.guidance
            ):
                raise HTTPException(422, "Guidance expired; fresh review is required")
        now = datetime.now(UTC).isoformat()
        observation: dict[str, Any] = {
            "kind": body.kind,
            "synthetic": True,
            "simulation_only": True,
            "actual_actor_id": str(actor_id),
            "confirmed_at": now,
            "identity": inputs.manifest.identity.model_dump(mode="json"),
            "work_cycle": case["work_cycle"],
        }
        if body.kind == "correction":
            observation.update(
                explanation=_text(body.payload, "explanation"),
                target_system=case["target_system"],
                target_object=case["business_context"]["target_account"],
                attempt_key=inputs.manifest.attempt_id,
                corrected_components=["chart_account", "company_code_extension"],
            )
            if inputs.sources["mapping-reference.json"]["state"] == "confirmed_absent":
                observation["corrected_components"] = ["applicable_mapping"]
                observation["mapping_change"] = _mapping_change(inputs)
        elif body.kind == "reprocessing":
            attempt_key = _text(body.payload, "attempt_key")
            target_ref = _text(body.payload, "target_document_reference")
            order = body.payload.get("processing_order")
            if type(order) is not int or order <= (inputs.manifest.processing_order or 0):
                raise HTTPException(422, "A later processing order is required")
            processing_at = _text(body.payload, "processing_at")
            try:
                instant = datetime.fromisoformat(processing_at.replace("Z", "+00:00"))
                if instant.tzinfo is None or instant <= inputs.manifest.processing_at:
                    raise ValueError("Later aware timestamp required")
            except ValueError as exc:
                raise HTTPException(
                    422, "A later processing time with timezone is required"
                ) from exc
            source_lines = inputs.sources["source-posting.json"]["records"][1:]
            if inputs.sources["mapping-reference.json"]["state"] == "confirmed_absent":
                milestones, proofs, links = await asyncio.gather(
                    self.user.rows(
                        "milestones", token, body.workspace_id, {"case_id": f"eq.{case_id}"}
                    ),
                    self.user.rows(
                        "evidence_versions",
                        token,
                        body.workspace_id,
                        {"case_id": f"eq.{case_id}", "kind": "eq.proof"},
                    ),
                    self.user.rows(
                        "milestone_proof", token, body.workspace_id, {"case_id": f"eq.{case_id}"}
                    ),
                )
                change = _mapping_change(inputs)
                receipts = []
                for milestone in milestones:
                    if (
                        milestone.get("kind") != "correction"
                        or milestone.get("human_confirmed") is not True
                        or milestone.get("attempt_id") != case["current_attempt_id"]
                        or milestone.get("work_cycle") != case["work_cycle"]
                        or milestone.get("details", {}).get("target_system")
                        != case["target_system"]
                        or milestone.get("details", {}).get("target_object")
                        != change["target_account"]
                    ):
                        continue
                    for proof in proofs:
                        verified = proof.get("provenance", {}).get("verified_observation", {})
                        if (
                            proof.get("attempt_id") != case["current_attempt_id"]
                            or proof.get("work_cycle") != case["work_cycle"]
                            or verified.get("kind") != "correction"
                            or verified.get("synthetic") is not True
                            or verified.get("simulation_only") is not True
                            or verified.get("work_cycle") != case["work_cycle"]
                            or verified.get("attempt_key") != inputs.manifest.attempt_id
                            or verified.get("corrected_components") != ["applicable_mapping"]
                            or verified.get("mapping_change") != change
                            or verified.get("identity")
                            != inputs.manifest.identity.model_dump(mode="json")
                            or verified.get("actual_actor_id") != milestone.get("actor_id")
                            or proof.get("uploader_id") != milestone.get("actor_id")
                            or not any(
                                link.get("milestone_id") == milestone.get("id")
                                and link.get("evidence_id") == proof.get("id")
                                for link in links
                            )
                        ):
                            continue
                        receipts.append(
                            {
                                "milestone_id": milestone["id"],
                                "proof_id": proof["id"],
                                "actor_id": milestone["actor_id"],
                                "acting_role": milestone["acting_role"],
                                "workspace_id": str(body.workspace_id),
                                "case_id": str(case_id),
                                "attempt_id": case["current_attempt_id"],
                                "attempt_key": inputs.manifest.attempt_id,
                                "work_cycle": case["work_cycle"],
                                "human_confirmed": True,
                                "mapping_change": change,
                            }
                        )
                if not receipts:
                    raise HTTPException(422, "Save the authenticated mapping correction first")
                observation["mapping_correction"] = receipts[-1]
            mapping = _posting_mappings(inputs, observation)
            lines = []
            for source in source_lines:
                matched = [m for m in mapping if m["source_account"] == source["source_account"]]
                if len(matched) != 1:
                    raise HTTPException(422, "Applicable line mapping is ambiguous")
                lines.append(
                    {
                        "line_number": source["line_number"],
                        "source_account": source["source_account"],
                        "target_account": matched[0]["target_account"],
                        "debit": source["debit"],
                        "credit": source["credit"],
                        "currency": source["currency"],
                    }
                )
            posting = {
                "currency": inputs.manifest.business_context.currency,
                "company_code": inputs.manifest.business_context.company_code,
                "source_identity": inputs.manifest.identity.model_dump(mode="json"),
                "lines": lines,
            }
            observation.update(
                attempt_key=attempt_key,
                processing_order=order,
                processing_at=processing_at,
                result="successful",
                target_document_reference=target_ref,
                posting=posting,
            )
        else:
            attempts = await self.user.rows(
                "attempts", token, body.workspace_id, {"id": f"eq.{case['current_attempt_id']}"}
            )
            proof_rows = await self.user.rows(
                "evidence_versions",
                token,
                body.workspace_id,
                {"case_id": f"eq.{case_id}", "kind": "eq.proof"},
            )
            matching = [
                e
                for e in proof_rows
                if e["provenance"].get("verified_observation", {}).get("kind") == "reprocessing"
                and e["provenance"]["verified_observation"].get("attempt_key")
                == attempts[0]["attempt_key"]
            ]
            if not matching:
                raise HTTPException(422, "Saved current target posting proof is required")
            target = matching[-1]["provenance"]["verified_observation"]
            expected = validation_values(inputs, target)
            try:
                checks = [ValidationCheck.model_validate(x) for x in body.payload.get("checks", [])]
            except ValueError as exc:
                raise HTTPException(422, "Four explicit posting comparisons are required") from exc
            if {x.dimension for x in checks} != set(expected) or len(checks) != 4:
                raise HTTPException(422, "Four distinct posting comparisons are required")
            for check in checks:
                required = expected[check.dimension]
                if check.expected != required["expected"] or check.observed != required["observed"]:
                    raise HTTPException(422, "Compare the exact saved source and target values")
                if check.result == "passed" and check.expected != check.observed:
                    raise HTTPException(422, "A discrepancy cannot pass validation")
            observation.update(
                attempt_key=attempts[0]["attempt_key"],
                target_document_reference=attempts[0]["target_document_reference"],
                checks=[x.model_dump(mode="json") for x in checks],
                posting=target["posting"],
                status="failed" if any(x.result == "failed" for x in checks) else "passed",
            )
        content = json.dumps(observation, indent=2).encode()
        storage = await self.service.store(
            body.workspace_id, content, f"simulated-{body.kind}-{uuid4()}.json", "application/json"
        )
        storage.update(
            source_id="human-simulation-" + str(uuid4()),
            source_version="1",
            observed_at=now,
            provenance={
                "synthetic": True,
                "verified_observation": observation,
                "description": "Deterministic simulation initiated by this authenticated human",
            },
        )
        return await self.service.rpc(
            "cfin_register_evidence",
            {
                "actor_id": str(actor_id),
                "acting_role": body.acting_role,
                "workspace_id": str(body.workspace_id),
                "case_id": str(case_id),
                "attempt_id": case["current_attempt_id"],
                "work_cycle": case["work_cycle"],
                "kind": "proof",
                "storage": storage,
            },
        )

    async def action(
        self, token: str, actor_id: UUID, case_id: UUID, body: ActionRequest
    ) -> dict[str, Any]:
        await self.user.require_member(token, actor_id, body.workspace_id, body.acting_role)
        case = await self.get_case(token, body.workspace_id, case_id)
        if case.get("linked_case_id"):
            raise HTTPException(409, "Use the linked canonical case")
        # These RPCs check the immutable receipt before checking the case version.
        # Let an identical retry recover a committed save after a lost HTTP response.
        receipt_action = is_error_analysis(case) and body.action in {
            "record_route_step", "comment", "record_approval", "assign", "set_status",
            "finish_resolution",
        }
        if case["version"] != body.expected_version and not receipt_action:
            raise HTTPException(409, "The case changed. Refresh and try again")
        payload = dict(body.payload)
        common = {
            "workspace_id": str(body.workspace_id),
            "case_id": str(case_id),
            "expected_version": body.expected_version,
            "acting_role": body.acting_role,
            "request_key": body.request_key,
        }
        if is_error_analysis(case):
            if body.action != "record_route_step":
                return await error_workbench_action(
                    self.user, token, body.workspace_id, case, common, body.action, payload
                )
            return await record_error_route_step(
                self.user, token, body.workspace_id, case, common, payload
            )
        if is_factual(case):
            return await factual_action(
                self.user, token, body.workspace_id, case, body.action, payload, common
            )
        if body.action in ("review_summary", "start_investigation", "record_investigation"):
            raise HTTPException(422, "Use the legacy workflow actions for this historical case")
        if body.action == "approve_reference":
            detail = await self.detail(token, body.workspace_id, case_id)
            allowed = {reference["evidence_id"] for reference in detail["references"]}
            evidence = await self.user.rows(
                "evidence_versions",
                token,
                body.workspace_id,
                {"id": f"eq.{_uuid(payload.get('evidence_id'))}"},
            )
            if (
                len(evidence) != 1
                or evidence[0]["id"] not in allowed
                or evidence[0]["filename"]
                not in (
                    "mapping-reference.json",
                    "missing-gl-master-playbook.json",
                )
            ):
                raise HTTPException(422, "Select a reference version from this case's saved pack")
            raw = json.loads(await self.user.download(token, evidence[0]))
            return await self.user.rpc(
                "cfin_review_reference",
                token,
                {
                    **common,
                    "evidence_id": evidence[0]["id"],
                    "source_version": evidence[0]["source_version"],
                    "reference_kind": "mapping"
                    if evidence[0]["kind"] == "reference"
                    else "guidance",
                    "scope": raw.get("scope", raw.get("query_scope", {})),
                    "decision": payload.get("decision"),
                    "reason": _text(payload, "reason"),
                    "expected_review_version": payload.get("expected_review_version"),
                },
            )
        if body.action == "analyse":
            return await self.user.rpc("cfin_enqueue_run", token, common)
        if body.action == "review_diagnosis":
            review_run_id = payload.get("run_id")
            if review_run_id not in (case.get("requested_run_id"), case.get("published_run_id")):
                raise HTTPException(409, "Review the latest saved analysis or failure")
            runs = await self.user.rows(
                "analysis_runs", token, body.workspace_id, {"id": f"eq.{_uuid(review_run_id)}"}
            )
            if (
                not runs
                or runs[0]["state"] not in ("succeeded", "failed")
                or runs[0]["attempt_id"] != case["current_attempt_id"]
                or runs[0]["input_revision"] != case["input_revision"]
            ):
                raise HTTPException(409, "Review the latest saved analysis or failure")
            diagnosis = (runs[0].get("output") or {}).get("diagnosis") or {}
            citations = [
                c
                for f in diagnosis.get("findings", [])
                for check in f.get("checks", [])
                for c in check.get("citations", [])
            ]
            payload["cause_evidence"] = citations
            if payload.get("decision") == "Corrected":
                corrected = payload.get("findings")
                if not isinstance(corrected, dict):
                    raise HTTPException(422, "Record the corrected human findings")
                _text(corrected, "cause_label")
                _text(corrected, "explanation")
                gaps = corrected.get("gaps", [])
                if not isinstance(gaps, list) or any(
                    not isinstance(gap, str) or not gap.strip() for gap in gaps
                ):
                    raise HTTPException(422, "Record explicit gaps as text")
                try:
                    corrected_citations = [
                        Citation.model_validate(item).model_dump(mode="json")
                        for item in corrected.get("citations", [])
                    ]
                    if corrected_citations:
                        await validate_snapshot_citations(
                            corrected_citations, runs[0]["snapshot"], self.service
                        )
                except (ValueError, TypeError) as exc:
                    raise HTTPException(422, "Corrected findings need valid citations") from exc
                if payload.get("cause_confirmed") is True and not corrected_citations:
                    raise HTTPException(422, "Confirming a corrected cause requires evidence")
                payload["findings"] = {
                    "cause_label": corrected["cause_label"],
                    "explanation": corrected["explanation"],
                    "gaps": gaps,
                    "citations": corrected_citations,
                    "provenance": "human_correction",
                }
                payload["cause_evidence"] = corrected_citations
            else:
                payload["findings"] = diagnosis
        if body.action == "start_work":
            if payload.get("target_change_authority") is not True:
                raise HTTPException(422, "Explicit simulated change authority is required")
            _text(payload, "approved_attributes")
        if body.action.startswith("record_") or body.action == "finish_resolution":
            if payload.get("human_confirmed") is not True:
                raise HTTPException(422, "Explicit human attestation is required")
            proof_ids = payload.get("proof_ids")
            if not isinstance(proof_ids, list) or not proof_ids:
                raise HTTPException(422, "Saved private proof is required")
            for value in proof_ids:
                proof = await self.user.rows(
                    "evidence_versions",
                    token,
                    body.workspace_id,
                    {"id": f"eq.{_uuid(value)}", "case_id": f"eq.{case_id}", "kind": "eq.proof"},
                )
                if len(proof) != 1:
                    raise HTTPException(422, "Proof must belong to this case")
                await self.user.download(token, proof[0])
        if body.action == "record_validation":
            try:
                checks = [ValidationCheck.model_validate(x) for x in payload.get("checks", [])]
            except ValueError as exc:
                raise HTTPException(422, "Validation checks are invalid") from exc
            payload["checks"] = [x.model_dump(mode="json") for x in checks]
        if body.action == "finish_resolution":
            try:
                payload["scope"] = ResolutionScope.model_validate(payload.get("scope")).model_dump()
                payload["cause_evidence"] = [
                    Citation.model_validate(x).model_dump(mode="json")
                    for x in payload.get("cause_evidence", [])
                ]
                runs = await self.user.rows(
                    "analysis_runs",
                    token,
                    body.workspace_id,
                    {"id": f"eq.{case.get('published_run_id') or case.get('requested_run_id')}"},
                )
                if payload["cause_evidence"]:
                    if not runs:
                        raise ValueError("Saved input snapshot required")
                    await validate_snapshot_citations(
                        payload["cause_evidence"], runs[0]["snapshot"], self.service
                    )
            except ValueError as exc:
                raise HTTPException(422, "Resolution scope or citations are invalid") from exc
        return await self.user.rpc(
            "cfin_case_action", token, {**common, "action": body.action, "data": payload}
        )


async def validate_snapshot_citations(
    citations: list[dict[str, Any]], snapshot: dict[str, Any], service: ServiceGateway
) -> None:
    """Human citations use the exact immutable catalogue reviewed by this run."""
    inputs = await restore_inputs(snapshot, service)
    validate_citations(
        [Citation.model_validate(c) for c in citations],
        list(inputs.catalogue),
        attempt_id=inputs.manifest.attempt_id,
    )


def validation_values(inputs: Any, target: dict[str, Any]) -> dict[str, dict[str, str]]:
    source = inputs.sources["source-posting.json"]
    header = source["records"][0]
    source_lines = source["records"][1:]
    mapping = {m["source_account"]: m["target_account"] for m in _posting_mappings(inputs, target)}
    observed_lines = target["posting"]["lines"]
    amount_expected = "; ".join(
        f"{x['line_number']}: {x['debit']} debit / {x['credit']} credit {x['currency']}"
        for x in source_lines
    )
    amount_observed = "; ".join(
        f"{x['line_number']}: {x['debit']} debit / {x['credit']} credit {x['currency']}"
        for x in observed_lines
    )
    accounts_expected = "; ".join(
        f"{x['line_number']}: {mapping[x['source_account']]}" for x in source_lines
    )
    accounts_observed = "; ".join(
        f"{x['line_number']}: {x['target_account']}" for x in observed_lines
    )
    identity = inputs.manifest.identity.model_dump(exclude={"workspace_id"})
    target_identity = {
        k: v for k, v in target["posting"]["source_identity"].items() if k != "workspace_id"
    }
    return {
        "amount_currency": {"expected": amount_expected, "observed": amount_observed},
        "company": {
            "expected": header["source_company_code"],
            "observed": target["posting"]["company_code"],
        },
        "accounts": {"expected": accounts_expected, "observed": accounts_observed},
        "source_target_reference": {
            "expected": json.dumps(identity, sort_keys=True),
            "observed": json.dumps(target_identity, sort_keys=True),
        },
    }


def _mapping_change(inputs: Any) -> dict[str, str]:
    """The approved design is an intended change, never an observed mapping row."""
    mapping = inputs.sources["mapping-reference.json"]
    source = next(
        source
        for source in inputs.catalogue
        if source.source_id == mapping["source_id"]
        and source.source_version == mapping["source_version"]
    )
    governance = source.governance
    records = [
        row
        for row in mapping.get("independent_target_records", [])
        if row.get("source_account") == mapping["query_scope"].get("source_account")
        and row.get("target_account") == inputs.manifest.business_context.target_account
        and row.get("reference_kind") == "independent_target_design"
    ]
    if (
        governance is None
        or governance.reuse_status != "approved"
        or governance.approved_version != source.source_version
        or not governance.reviewer
        or len(records) != 1
    ):
        raise HTTPException(422, "Exact approved independent target design required")
    row = records[0]
    return {
        "source_account": row["source_account"],
        "target_account": row["target_account"],
        "independent_target_record_id": row["record_id"],
        "mapping_source_id": source.source_id,
        "mapping_source_version": source.source_version,
    }


def _posting_mappings(inputs: Any, target: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = inputs.sources["mapping-reference.json"]
    records = list(mapping["records"])
    if mapping["state"] == "confirmed_absent":
        receipt = target.get("mapping_correction", {})
        change = _mapping_change(inputs)
        if not isinstance(receipt, dict):
            raise HTTPException(422, "Saved mapping correction receipt required")
        if (
            receipt.get("mapping_change") != change
            or receipt.get("human_confirmed") is not True
            or receipt.get("attempt_key") != inputs.manifest.attempt_id
            or receipt.get("workspace_id") != inputs.manifest.identity.workspace_id
            or receipt.get("acting_role") not in ROLE.__args__
            or type(receipt.get("work_cycle")) is not int
            or receipt["work_cycle"] < 1
        ):
            raise HTTPException(422, "Saved mapping correction receipt required")
        for field in ("milestone_id", "proof_id", "actor_id", "case_id", "attempt_id"):
            _uuid(receipt.get(field))
        records.extend(mapping.get("unaffected_mapping_records", []))
        # This post-correction state is kept in the successful proof. The
        # immutable failure-time lookup remains empty and confirmed absent.
        records.append(change)
    accounts = [row.get("source_account") for row in records]
    if len(accounts) != len(set(accounts)):
        raise HTTPException(422, "Applicable line mapping is ambiguous")
    required = {
        row["source_account"] for row in inputs.sources["source-posting.json"]["records"][1:]
    }
    if not required <= set(accounts):
        raise HTTPException(422, "Every source line needs its saved applicable mapping")
    return records
