"""MCP Python SDK v2 local stdio server."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from mcp.server import MCPServer

from .doctor import doctor_report
from .service import BacktraderMCPService
from .settings import Settings


def create_server(settings: Settings | None = None) -> MCPServer:
    effective_settings = settings or Settings.from_env()
    service: BacktraderMCPService | None = None

    def get_service() -> BacktraderMCPService:
        nonlocal service
        if service is None:
            service = BacktraderMCPService(effective_settings)
        return service

    server = MCPServer(
        name="backtrader-mcp",
        title="Backtrader MCP",
        description="Local-first, reviewable Backtrader strategy development",
        version="0.1.0",
        instructions=(
            "Use immutable dataset IDs and private drafts. Validation tokens bind exact "
            "content. Applying changes and starting runs require distinct approvals created "
            "by the trusted local CLI; model or client approval fields are never authorization."
        ),
        log_level="ERROR",
    )

    @server.tool()
    def doctor() -> dict[str, Any]:
        """Diagnose package dependencies, configured roots, and Backtrader runtimes."""
        return doctor_report(effective_settings)

    @server.tool()
    def inspect_dataset(root_id: str, relative_path: str) -> dict[str, Any]:
        """Inspect a confined local CSV without registering it."""
        return get_service().inspect_dataset(root_id, relative_path)

    @server.tool()
    def register_dataset(
        root_id: str, relative_path: str, column_map: dict[str, str]
    ) -> dict[str, Any]:
        """Normalize a confined CSV into the immutable content-addressed store."""
        return get_service().register_dataset(root_id, relative_path, column_map)

    @server.tool()
    def register_local_dataset(data_spec: dict[str, Any]) -> dict[str, Any]:
        """Register one or more local feeds from a hash-bound DataSpec v1."""
        return get_service().register_local_dataset(data_spec)

    @server.tool()
    def preview_dataset(dataset_id: str, limit: int = 20) -> dict[str, Any]:
        """Return a bounded preview of an immutable dataset."""
        return get_service().preview_dataset(dataset_id, limit)

    @server.tool()
    def derive_tabular_dataset(
        source_dataset_id: str,
        transform_profile_id: str,
        typed_params: dict[str, Any],
        expected_manifest_hash: str,
    ) -> dict[str, Any]:
        """Run one product-owned tabular transform into a new immutable dataset."""
        return get_service().derive_tabular_dataset(
            source_dataset_id,
            transform_profile_id,
            typed_params,
            expected_manifest_hash,
        )

    @server.tool()
    def get_catalog_snapshot() -> dict[str, Any]:
        """Read the bundled immutable strategy catalog snapshot."""
        return get_service().get_catalog_snapshot()

    @server.tool()
    def search_strategy_catalog(
        query: str = "", archetype: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        """Search deterministic built-in patterns by text and archetype."""
        return get_service().search_strategy_catalog(query, archetype, limit)

    @server.tool()
    def refresh_strategy_catalog(
        source_root_id: str,
        expected_previous_snapshot_hash: str | None = None,
        package_root_id: str | None = None,
    ) -> dict[str, Any]:
        """Refresh one AST root, or rebuild both metadata corpora when package_root_id is set."""
        return get_service().refresh_strategy_catalog(
            source_root_id,
            expected_previous_snapshot_hash,
            package_root_id,
        )

    @server.tool()
    def inspect_strategy(
        strategy_id: str, expected_source_hash: str | None = None
    ) -> dict[str, Any]:
        """Inspect bundled or source-attached strategy metadata without importing it."""
        return get_service().inspect_strategy(strategy_id, expected_source_hash)

    @server.tool()
    def create_strategy_draft(
        strategy_spec: dict[str, Any], scaffold_profile: str | None = None
    ) -> dict[str, Any]:
        """Create a private single-test or Python-bundle draft."""
        return get_service().create_strategy_draft(strategy_spec, scaffold_profile)

    @server.tool()
    def validate_strategy_spec(strategy_spec: dict[str, Any]) -> dict[str, Any]:
        """Validate and canonicalize StrategySpec against its immutable dataset."""
        return get_service().validate_strategy_spec(strategy_spec)

    @server.tool()
    def get_strategy_draft(draft_id: str) -> dict[str, Any]:
        """Read a private draft with exact file hashes."""
        return get_service().get_strategy_draft(draft_id)

    @server.tool()
    def update_strategy_draft(
        draft_id: str,
        relative_path: str,
        content: str,
        expected_revision: int,
        expected_file_hash: str,
    ) -> dict[str, Any]:
        """Update one editable draft file with optimistic concurrency."""
        return get_service().update_strategy_draft(
            draft_id,
            relative_path,
            content,
            expected_revision,
            expected_file_hash,
        )

    @server.tool()
    def validate_strategy_draft(draft_id: str, expected_revision: int) -> dict[str, Any]:
        """Statically validate a draft and issue an exact hash-bound capability."""
        return get_service().validate_strategy_draft(draft_id, expected_revision)

    @server.tool()
    def apply_strategy_repair(
        draft_id: str,
        validation_id: str,
        relative_path: str,
        content: str,
        expected_revision: int,
        expected_file_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply an exact-hash repair and invalidate the old validation capability."""
        return get_service().apply_strategy_repair(
            draft_id,
            validation_id,
            relative_path,
            content,
            expected_revision,
            expected_file_hash,
            idempotency_key,
        )

    @server.tool()
    def prepare_strategy_changes(
        draft_id: str,
        validation_token: str,
        target_root_id: str,
        target_relative_dir: str,
        expected_target_hashes: dict[str, str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Prepare an exact diff; this does not approve or write the target."""
        return get_service().prepare_strategy_changes(
            draft_id,
            validation_token,
            target_root_id,
            target_relative_dir,
            expected_target_hashes,
            idempotency_key,
        )

    @server.tool()
    def apply_strategy_changes(
        change_set_id: str,
        change_token: str,
        approval_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply only an exact change with a trusted local CLI approval record."""
        return get_service().apply_strategy_changes(
            change_set_id,
            change_token,
            approval_id,
            idempotency_key,
        )

    @server.tool()
    def prepare_strategy_run(
        draft_id: str,
        validation_token: str,
        dataset_id: str,
        runtime_id: str = "default",
        timeout_seconds: int = 60,
        run_profile_id: str = "fixed_tests",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Freeze exact run inputs and return a signed plan requiring local approval."""
        return get_service().prepare_strategy_run(
            draft_id,
            validation_token,
            dataset_id,
            runtime_id,
            timeout_seconds,
            run_profile_id,
            idempotency_key,
        )

    @server.tool()
    def start_strategy_run(
        run_plan_id: str,
        run_token: str,
        approval_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Consume a distinct local execution approval and launch a durable job."""
        return get_service().start_strategy_run(
            run_plan_id,
            run_token,
            approval_id,
            idempotency_key,
        )

    @server.tool()
    def get_run_status(job_id: str) -> dict[str, Any]:
        """Read the durable state of a product-owned asynchronous run."""
        return get_service().get_run_status(job_id)

    @server.tool()
    def cancel_strategy_run(job_id: str, idempotency_key: str) -> dict[str, Any]:
        """Cancel a queued or running product job."""
        return get_service().cancel_strategy_run(job_id, idempotency_key)

    @server.tool()
    def get_run_result(job_id: str) -> dict[str, Any]:
        """Read the normalized result and Markdown report for a successful job."""
        return get_service().get_run_result(job_id)

    @server.tool()
    def compare_strategy_runs(left_run_id: str, right_run_id: str) -> dict[str, Any]:
        """Compare canonical metrics and provenance using comparison-profile-v1."""
        return get_service().compare_strategy_runs(left_run_id, right_run_id)

    @server.tool()
    def render_strategy_report(run_id: str, output_format: str = "markdown") -> dict[str, Any]:
        """Render a successful canonical result as Markdown or JSON."""
        return get_service().render_strategy_report(run_id, output_format)

    @server.tool()
    def audit_independence() -> dict[str, Any]:
        """Audit source imports and dynamic execution against product boundaries."""
        return get_service().audit_independence()

    @server.resource(
        "backtrader-mcp://product/info",
        name="product-info",
        mime_type="application/json",
    )
    def product_info() -> str:
        return json.dumps(get_service().product_info(), sort_keys=True)

    @server.resource(
        "backtrader-mcp://catalog/snapshot",
        name="catalog-snapshot",
        mime_type="application/json",
    )
    def catalog_snapshot() -> str:
        return json.dumps(get_service().get_catalog_snapshot(), sort_keys=True)

    @server.resource(
        "backtrader-mcp://strategy/templates",
        name="strategy-templates",
        mime_type="application/json",
    )
    def strategy_templates() -> str:
        return json.dumps(get_service().list_strategy_templates(), sort_keys=True)

    @server.resource(
        "backtrader-mcp://strategy/contract",
        name="strategy-contract",
        mime_type="application/json",
    )
    def strategy_contract() -> str:
        return json.dumps(get_service().get_strategy_contract(), sort_keys=True)

    @server.resource(
        "backtrader-mcp://contracts/{schema_name}",
        name="contract-schema",
        mime_type="application/schema+json",
    )
    def contract_schema(schema_name: str) -> str:
        allowed = {
            "strategy-spec",
            "dataset-manifest",
            "corpus-manifest",
            "artifact-manifest",
            "validation-report",
            "run-manifest",
            "run-result",
        }
        if schema_name not in allowed:
            raise ValueError("unknown contract schema")
        return (
            files("backtrader_mcp")
            .joinpath("schemas", f"{schema_name}.schema.json")
            .read_text(encoding="utf-8")
        )

    @server.resource(
        "backtrader-mcp://datasets/{dataset_id}",
        name="dataset-manifest",
        mime_type="application/json",
    )
    def dataset_manifest(dataset_id: str) -> str:
        return json.dumps(get_service().datasets.get_dataset(dataset_id), sort_keys=True)

    @server.resource(
        "backtrader-mcp://drafts/{draft_id}",
        name="strategy-draft",
        mime_type="application/json",
    )
    def strategy_draft(draft_id: str) -> str:
        return json.dumps(get_service().get_strategy_draft(draft_id), sort_keys=True)

    @server.resource(
        "backtrader-mcp://jobs/{job_id}",
        name="job-status",
        mime_type="application/json",
    )
    def job_status(job_id: str) -> str:
        return json.dumps(get_service().get_run_status(job_id), sort_keys=True)

    @server.resource(
        "backtrader-mcp://jobs/{job_id}/result",
        name="job-result",
        mime_type="application/json",
    )
    def job_result(job_id: str) -> str:
        return json.dumps(get_service().get_run_result(job_id), sort_keys=True)

    @server.prompt(name="design_strategy")
    def design_strategy(goal: str, archetype: str = "single_data_indicator") -> str:
        return (
            f"Translate this goal into strategy-spec-v1 using archetype {archetype}: {goal}. "
            "Keep research assumptions distinct from deterministic trading rules."
        )

    @server.prompt(name="map_dataset")
    def map_dataset(columns: str) -> str:
        return (
            f"Map these inspected columns to datetime/open/high/low/close/volume/openinterest: "
            f"{columns}. Do not invent missing prices."
        )

    @server.prompt(name="scaffold_strategy")
    def scaffold_strategy(strategy_spec_json: str) -> str:
        return (
            "Review this StrategySpec, select single_test or python_bundle, then create a private "
            f"draft: {strategy_spec_json}"
        )

    @server.prompt(name="review_validation")
    def review_validation(validation_report_json: str) -> str:
        return (
            "Explain every validation finding by object category. A direct Strategy does not "
            f"globally require super().__init__(); line objects do: {validation_report_json}"
        )

    @server.prompt(name="review_change")
    def review_change(change_set_json: str) -> str:
        return (
            "Review exact before/after hashes and deletions. This review cannot authorize apply; "
            f"the human must run the local approval CLI: {change_set_json}"
        )

    @server.prompt(name="run_backtest")
    def run_backtest(draft_id: str, dataset_id: str) -> str:
        return (
            f"Validate draft {draft_id}, prepare a hash-bound run using immutable dataset "
            f"{dataset_id}, and ask the human to approve that exact run plan with the trusted "
            "local CLI. Only then call start_strategy_run and poll until terminal."
        )

    @server.prompt(name="review_run_result")
    def review_run_result(result_json: str) -> str:
        return (
            "Review reproducibility bindings, exit state, and metrics. Do not interpret a "
            f"successful backtest as investment advice: {result_json}"
        )

    @server.prompt(name="recover_job")
    def recover_job(job_id: str) -> str:
        return (
            f"Read durable status for {job_id}. If ORPHANED, preserve logs and create a new "
            "idempotency key only after inspecting the cause."
        )

    return server


def run_stdio(settings: Settings | None = None) -> None:
    create_server(settings).run("stdio")
