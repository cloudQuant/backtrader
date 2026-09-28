"""Keep the local fake AccountActor candidate outside production imports.

This is a source-level non-registration guard only. It does not establish
writer exclusion, provider authority, account-state completeness, or G6-P.
"""

from pathlib import Path


_FORBIDDEN_REFERENCES = (
    "_local_fake_account_actor_candidate",
    "fake_actor_service",
)


def test_production_sources_do_not_reference_the_local_fake_actor_candidate():
    repository_root = Path(__file__).resolve().parents[3]
    source_roots = (
        repository_root / "backtrader_runtime",
        repository_root / "backtrader",
    )
    candidate_directory = "_local_fake_account_actor_candidate"

    references = []
    for source_root in source_roots:
        for source_path in source_root.rglob("*.py"):
            relative_parts = source_path.relative_to(source_root).parts
            if candidate_directory in relative_parts or "__pycache__" in relative_parts:
                continue
            try:
                source = source_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                references.append(f"{source_path}: source unreadable ({type(error).__name__})")
                continue
            for forbidden in _FORBIDDEN_REFERENCES:
                if forbidden in source:
                    references.append(f"{source_path}: contains {forbidden!r}")

    assert not references, "local fake Actor referenced by production source:\n" + "\n".join(
        references
    )
