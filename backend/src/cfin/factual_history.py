"""Bounded, authorised reviewed history supplied exclusively after evidence selection."""

import hashlib
import json
from typing import Any

from cfin.contracts import Citation
from cfin.gateway import ServiceGateway
from cfin.knowledge import concept_vector, register_history_for_run, vector_literal
from cfin.log_only_contracts import (
    ExecutionBinding,
    HistoricalCaseEvidence,
    HistoryRetrievalResult,
    HydratedSelection,
    LogAnalysisResult,
)
from cfin.log_only_sources import source_lines

MAX_HISTORY_CASES = 3
MAX_HISTORY_BYTES = 24_000
MAX_ORIGINAL_BYTES = 8_192
MAX_HISTORY_QUERY = 1_000


def selected_history_query(selection: HydratedSelection) -> tuple[str, bool]:
    """Observed messages and exact field values, never diagnosis or leading log bytes."""
    parts: list[str] = []
    for entry in selection.selected_entries:
        for value in (
            entry.message_class,
            entry.message_number,
            *(
                f"{field.name_as_logged}={field.value_as_logged}"
                for field in [*entry.fields, *entry.message_variables]
            ),
            entry.raw_text.strip(),
        ):
            if value and value not in parts:
                parts.append(value)
    query = " ".join(parts)
    return query[:MAX_HISTORY_QUERY], len(query) > MAX_HISTORY_QUERY


class FactualHistoryReader:
    def __init__(
        self,
        cloud: ServiceGateway,
        binding: ExecutionBinding,
        actor_id: str,
        excluded_case_ids: tuple[str, ...] | list[str] = (),
        *,
        category_id: str | None = None,
        routing_context: dict[str, str] | None = None,
    ):
        self.cloud, self.binding, self.actor_id = cloud, binding, str(actor_id)
        self.excluded = {binding.case_id, *map(str, excluded_case_ids)}
        self.category_id = category_id
        self.routing_context = dict(routing_context or {})

    def _scope(self) -> dict[str, Any]:
        return {
            "workspace_id": self.binding.workspace_id,
            "actor_id": self.actor_id,
            "current_case_id": self.binding.case_id,
            "excluded_case_ids": sorted(self.excluded),
        }

    async def _load(self, knowledge_id: str, version: int) -> dict[str, Any]:
        return await self.cloud.rpc(
            "cfin_load_history_evidence",
            {
                **self._scope(),
                "knowledge_id": knowledge_id,
                "version": version,
            },
        )

    async def retrieve(self, selection: HydratedSelection) -> HistoryRetrievalResult:
        query, query_limited = selected_history_query(selection)
        if not query:
            return HistoryRetrievalResult(status="completed")
        limitations = (
            ["History query was bounded to 1,000 observed characters."] if query_limited else []
        )
        candidates: list[HistoricalCaseEvidence] = []
        total = 0
        try:
            search_payload = {
                **self._scope(),
                "query": query,
                "context": self.routing_context,
                "limit": 5,
                "query_vector": vector_literal(concept_vector(query)),
            }
            if self.category_id:
                search_payload["category_id"] = self.category_id
            response = await self.cloud.rpc(
                "cfin_search_error_analysis_history" if self.category_id else "cfin_search_history",
                search_payload,
            )
            for hit in response["items"][:5]:
                if str(hit.get("case_id")) in self.excluded:
                    continue
                if len(candidates) == MAX_HISTORY_CASES:
                    limitations.append("History reader inspected at most three reviewed cases.")
                    break
                try:
                    material = await self._load(str(hit["id"]), hit["version"])
                    knowledge, case = material["knowledge"], material["case"]
                    if (
                        str(case["id"]) in self.excluded
                        or str(case["workspace_id"]) != self.binding.workspace_id
                        or str(knowledge["id"]) != str(hit["id"])
                        or knowledge["version"] != hit["version"]
                        or knowledge.get("reuse_state") != "approved"
                        or str(knowledge["case_id"]) != str(case["id"])
                        or case.get("evaluation_only") is True
                    ):
                        raise ValueError("Historical scope or eligibility changed")
                    original_content, original_citations = [], []
                    if len(material["originals"]) > 8:
                        limitations.append("Only the first eight historical originals were read.")
                    for original in material["originals"][:8]:
                        if (
                            original.get("kind") != "original_log"
                            or str(original.get("workspace_id")) != self.binding.workspace_id
                            or str(original.get("case_id")) != str(case["id"])
                            or original.get("content_type") != "text/plain"
                            or not 0 < original.get("byte_size", 0) <= MAX_ORIGINAL_BYTES
                        ):
                            limitations.append(
                                "A historical original was outside the text reading envelope."
                            )
                            continue
                        raw = await self.cloud.download(original)
                        if (
                            len(raw) != original["byte_size"]
                            or hashlib.sha256(raw).hexdigest() != original["sha256"]
                        ):
                            raise ValueError("Historical original failed integrity verification")
                        text = raw.decode("utf-8", errors="strict")
                        if not text.strip():
                            continue
                        original_content.append(
                            {
                                "source_id": original["source_id"],
                                "source_version": original["source_version"],
                                "filename": original["filename"],
                                "text": text,
                                "read_completely": True,
                            }
                        )
                        original_citations.append(
                            Citation(
                                source_id=original["source_id"],
                                source_version=original["source_version"],
                                attempt_id=original.get("attempt_id"),
                                line_start=1,
                                line_end=len(source_lines(raw)),
                            )
                        )
                    if not original_citations:
                        limitations.append(
                            "A reviewed case was omitted because its original was unavailable."
                        )
                        continue
                    # Exact reviewed resolution is kept distinct from original-log observations.
                    content = json.dumps(
                        {
                            "case": {"id": case["id"]},
                            "reviewed_knowledge": {
                                key: knowledge.get(key)
                                for key in (
                                    "id",
                                    "version",
                                    "lesson",
                                    "scope",
                                    "reviewed_at",
                                )
                            },
                            "human_resolution": material["resolution"],
                            "originals": original_content,
                            "attribution": (
                                "Prior reviewed case only; not evidence of the current cause."
                            ),
                        },
                        ensure_ascii=False,
                    )
                    size = len(content.encode())
                    if total + size > MAX_HISTORY_BYTES:
                        limitations.append(
                            "A historical case exceeded the remaining reading envelope."
                        )
                        continue
                    total += size
                    candidates.append(
                        HistoricalCaseEvidence(
                            case_id=str(case["id"]),
                            knowledge_id=str(knowledge["id"]),
                            knowledge_version=knowledge["version"],
                            content=content,
                            citations=(
                                Citation(
                                    source_id="knowledge-" + str(knowledge["id"]),
                                    source_version=str(knowledge["version"]),
                                    record_id=str(knowledge["id"]),
                                ),
                                *original_citations,
                            ),
                        )
                    )
                except Exception:
                    limitations.append(
                        "A historical candidate could not be read or was no longer eligible."
                    )
            return HistoryRetrievalResult(
                status="completed",
                candidates=tuple(candidates),
                limitation=" ".join(dict.fromkeys(limitations)) or None,
            )
        except Exception:
            return HistoryRetrievalResult(
                status="unavailable",
                limitation=(
                    "Reviewed history could not be searched; current facts remain available."
                ),
            )

    async def finalize(self, result: LogAnalysisResult) -> LogAnalysisResult:
        """Register only cited exact versions; unused candidates cannot block publication."""
        if not result.summary or not result.summary.related_cases:
            return result
        retained = []
        for reference in result.summary.related_cases:
            try:
                material = await self._load(reference.knowledge_id, reference.knowledge_version)
                knowledge = material["knowledge"]
                if (
                    knowledge["id"] != reference.knowledge_id
                    or knowledge["version"] != reference.knowledge_version
                    or knowledge.get("reuse_state") != "approved"
                    or str(material["case"]["id"]) != reference.case_id
                    or reference.case_id in self.excluded
                ):
                    continue
                retained.append(reference)
            except Exception:
                continue
        try:
            if retained:
                await register_history_for_run(
                    self.cloud,
                    self.binding.workspace_id,
                    self.actor_id,
                    self.binding.run_id,
                    [
                        {"id": item.knowledge_id, "version": item.knowledge_version}
                        for item in retained
                    ],
                )
        except Exception:
            # Registration is atomic. Current-log analysis remains useful independently.
            retained = []
        if len(retained) == len(result.summary.related_cases):
            return result
        limitation = "Some historical references were withheld because access or approval changed."
        payload = result.model_dump(mode="json")
        payload["summary"]["related_cases"] = [item.model_dump(mode="json") for item in retained]
        payload["limitations"] = list(dict.fromkeys([*result.limitations, limitation]))
        payload["history"]["limitation"] = " ".join(
            filter(None, [result.history.limitation, limitation])
        )
        return LogAnalysisResult.model_validate(payload)
