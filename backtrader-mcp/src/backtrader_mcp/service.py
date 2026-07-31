"""Composition root and transport-neutral product API."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from .audit import audit_independence
from .catalog import CatalogService
from .changes import ChangeService
from .contracts import ARCHETYPES, StrategySpec
from .data import DatasetService
from .doctor import doctor_report
from .drafts import DraftService
from .jobs import JobService
from .locks import LockManager
from .reports import compare_metrics, render_markdown
from .security import TokenSigner
from .settings import Settings
from .state import StateStore


class BacktraderMCPService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.settings.initialize()
        self.state = StateStore(self.settings.state_root)
        self.locks = LockManager(self.settings.state_root / "locks")
        self.signer = TokenSigner(self.settings.state_root)
        self.datasets = DatasetService(self.settings, self.state)
        self.catalog = CatalogService(self.settings, self.state)
        self.drafts = DraftService(self.settings, self.state, self.signer, self.locks)
        self.changes = ChangeService(
            self.settings, self.state, self.signer, self.locks, self.drafts
        )
        self.jobs = JobService(
            self.settings,
            self.state,
            self.locks,
            self.drafts,
            self.datasets,
            self.signer,
        )
        self.recovery = {
            "transactions": self.changes.recover_transactions(),
            "jobs": self.jobs.recover_jobs(),
        }

    def product_info(self) -> dict[str, Any]:
        return {
            "name": "backtrader-mcp",
            "version": "0.1.0",
            "mcp_sdk": ">=2.0.0,<2.1",
            "transport": "stdio",
            "tasks_extension": False,
            "job_api": [
                "prepare_strategy_run",
                "start_strategy_run",
                "get_run_status",
                "cancel_strategy_run",
                "get_run_result",
            ],
            "state_root": str(self.settings.state_root),
            "source_root_ids": sorted(self.settings.source_roots),
            "target_root_ids": sorted(self.settings.target_roots),
            "runtime_ids": sorted(self.settings.runtimes),
            "recovery": self.recovery,
        }

    def doctor(self) -> dict[str, Any]:
        return doctor_report(self.settings)

    def inspect_dataset(self, root_id: str, relative_path: str) -> dict[str, Any]:
        return self.datasets.inspect_dataset(root_id, relative_path)

    def register_dataset(
        self, root_id: str, relative_path: str, column_map: dict[str, str]
    ) -> dict[str, Any]:
        return self.datasets.register_dataset(root_id, relative_path, column_map)

    def register_local_dataset(self, data_spec: dict[str, Any]) -> dict[str, Any]:
        return self.datasets.register_local_dataset(data_spec)

    def preview_dataset(self, dataset_id: str, limit: int = 20) -> dict[str, Any]:
        return self.datasets.preview_dataset(dataset_id, limit)

    def derive_tabular_dataset(
        self,
        source_dataset_id: str,
        transform_profile_id: str,
        typed_params: dict[str, Any],
        expected_manifest_hash: str,
    ) -> dict[str, Any]:
        return self.datasets.derive_tabular_dataset(
            source_dataset_id,
            transform_profile_id,
            typed_params,
            expected_manifest_hash,
        )

    def get_catalog_snapshot(self) -> dict[str, Any]:
        return self.catalog.get_snapshot()

    def search_strategy_catalog(
        self, query: str = "", archetype: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        return self.catalog.search(query, archetype, limit)

    def refresh_strategy_catalog(
        self,
        source_root_id: str,
        expected_previous_snapshot_hash: str | None = None,
        package_root_id: str | None = None,
    ) -> dict[str, Any]:
        return self.catalog.refresh_source_catalog(
            source_root_id,
            expected_previous_snapshot_hash,
            package_root_id,
        )

    def inspect_strategy(
        self, strategy_id: str, expected_source_hash: str | None = None
    ) -> dict[str, Any]:
        return self.catalog.inspect_strategy(strategy_id, expected_source_hash)

    def list_strategy_templates(self) -> dict[str, Any]:
        return self.catalog.list_templates()

    def get_strategy_contract(self) -> dict[str, Any]:
        schema = json.loads(
            files("backtrader_mcp")
            .joinpath("schemas", "strategy-spec.schema.json")
            .read_text(encoding="utf-8")
        )
        return {
            "schema_version": "strategy-contract-v1",
            "strategy_spec_schema": schema,
            "archetypes": list(ARCHETYPES),
            "output_profiles": ["single_test", "python_bundle"],
        }

    def create_strategy_draft(
        self, strategy_spec: dict[str, Any], scaffold_profile: str | None = None
    ) -> dict[str, Any]:
        return self.drafts.create_draft(strategy_spec, scaffold_profile)

    def validate_strategy_spec(self, strategy_spec: dict[str, Any]) -> dict[str, Any]:
        spec = StrategySpec.parse(strategy_spec)
        dataset = self.datasets.get_dataset(spec.dataset_id)
        dataset_feeds = {feed["name"] for feed in dataset["feeds"]}
        diagnostics = []
        for feed, dataset_feed in zip(spec.feeds, spec.dataset_feed_names):
            if dataset_feed not in dataset_feeds:
                diagnostics.append(
                    {
                        "code": "dataset_feed_missing",
                        "feed": feed["name"],
                        "dataset_feed": dataset_feed,
                    }
                )
        canonical = spec.as_dict()
        return {
            "schema_version": "strategy-spec-validation-v1",
            "status": "passed" if not diagnostics else "failed",
            "spec": canonical,
            "spec_hash": canonical["spec_hash"],
            "dataset_id": spec.dataset_id,
            "diagnostics": diagnostics,
        }

    def get_strategy_draft(self, draft_id: str) -> dict[str, Any]:
        return self.drafts.get_draft(draft_id)

    def update_strategy_draft(
        self,
        draft_id: str,
        relative_path: str,
        content: str,
        expected_revision: int,
        expected_file_hash: str,
    ) -> dict[str, Any]:
        return self.drafts.update_draft_file(
            draft_id,
            relative_path,
            content,
            expected_revision,
            expected_file_hash,
        )

    def validate_strategy_draft(self, draft_id: str, expected_revision: int) -> dict[str, Any]:
        return self.drafts.validate_draft(draft_id, expected_revision)

    def apply_strategy_repair(
        self,
        draft_id: str,
        validation_id: str,
        relative_path: str,
        content: str,
        expected_revision: int,
        expected_file_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self.drafts.apply_strategy_repair(
            draft_id,
            validation_id,
            relative_path,
            content,
            expected_revision,
            expected_file_hash,
            idempotency_key,
        )

    def prepare_strategy_changes(
        self,
        draft_id: str,
        validation_token: str,
        target_root_id: str,
        target_relative_dir: str,
        expected_target_hashes: dict[str, str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self.changes.prepare_strategy_changes(
            draft_id,
            validation_token,
            target_root_id,
            target_relative_dir,
            expected_target_hashes,
            idempotency_key,
        )

    def apply_strategy_changes(
        self,
        change_set_id: str,
        change_token: str,
        approval_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self.changes.apply_strategy_changes(
            change_set_id,
            change_token,
            approval_id,
            idempotency_key,
        )

    def prepare_strategy_run(
        self,
        draft_id: str,
        validation_token: str,
        dataset_id: str,
        runtime_id: str = "default",
        timeout_seconds: int = 60,
        run_profile_id: str = "fixed_tests",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        return self.jobs.prepare_strategy_run(
            draft_id,
            validation_token,
            dataset_id,
            runtime_id,
            timeout_seconds,
            run_profile_id,
            idempotency_key,
        )

    def start_strategy_run(
        self,
        run_plan_id: str,
        run_token: str,
        approval_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self.jobs.start_strategy_run(
            run_plan_id,
            run_token,
            approval_id,
            idempotency_key,
        )

    def get_run_status(self, job_id: str) -> dict[str, Any]:
        return self.jobs.get_run_status(job_id)

    def cancel_strategy_run(self, job_id: str, idempotency_key: str) -> dict[str, Any]:
        return self.jobs.cancel_strategy_run(job_id, idempotency_key)

    def get_run_result(self, job_id: str) -> dict[str, Any]:
        return self.jobs.get_run_result(job_id)

    def compare_strategy_runs(self, left_run_id: str, right_run_id: str) -> dict[str, Any]:
        left = self.jobs.get_run_result(left_run_id)
        right = self.jobs.get_run_result(right_run_id)
        comparison = compare_metrics(left["metrics"], right["metrics"])
        binding_diagnostics = []
        for name in ("artifact_hash", "dataset_semantic_hash"):
            left_value = left["extensions"].get(name)
            right_value = right["extensions"].get(name)
            if left_value != right_value:
                binding_diagnostics.append(
                    {
                        "code": "provenance_mismatch",
                        "binding": name,
                        "left": left_value,
                        "right": right_value,
                    }
                )
        return {
            **comparison,
            "left_run_id": left_run_id,
            "right_run_id": right_run_id,
            "status": (
                "mismatched"
                if binding_diagnostics or comparison["status"] == "mismatched"
                else "matched"
            ),
            "diagnostics": binding_diagnostics + comparison["diagnostics"],
        }

    def render_strategy_report(
        self, run_id: str, output_format: str = "markdown"
    ) -> dict[str, Any]:
        result = self.jobs.get_run_result(run_id)
        if output_format == "markdown":
            rendered: str | dict[str, Any] = render_markdown(result)
            media_type = "text/markdown"
        elif output_format == "json":
            rendered = result
            media_type = "application/json"
        else:
            from .errors import InvalidRequest

            raise InvalidRequest("output_format must be markdown or json")
        return {
            "run_id": run_id,
            "output_format": output_format,
            "media_type": media_type,
            "content": rendered,
        }

    def audit_independence(self) -> dict[str, Any]:
        return audit_independence()
