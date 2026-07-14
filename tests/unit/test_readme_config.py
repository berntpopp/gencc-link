"""README Standard v1 guard -- docs/configuration.md is the FULL env-var reference.

README.md routes every configuration question to docs/configuration.md and claims
it documents *every* ``GENCC_LINK_*`` variable. A hand-maintained table cannot keep
that promise on its own: a field added to ``ServerSettings`` is instantly settable
by an operator and instantly missing from the docs, and nothing notices. That is
precisely how the CORS block and the download caps went undocumented.

So this test owns the claim. The variable names are *derived* from the live
settings model -- the same model pydantic-settings actually reads env vars into --
and every one of them must appear in docs/configuration.md.

If this fails you added a setting: document it, or the README is lying.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings

from gencc_link.config import ServerSettings

CONFIG_DOC = Path(__file__).resolve().parents[2] / "docs" / "configuration.md"

#: The prefix/delimiter contract. Unprefixed names are silently IGNORED by
#: pydantic-settings (extra="ignore"), so documenting one would be worse than
#: not documenting it at all -- the operator edits it and nothing happens.
ENV_PREFIX = "GENCC_LINK_"
NESTED_DELIMITER = "__"


def _settable_env_vars(model: type[BaseModel], prefix: str = ENV_PREFIX) -> set[str]:
    """Every env var name that resolves into a field of ``model``, recursively."""
    names: set[str] = set()
    for field_name, field in model.model_fields.items():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            nested = f"{prefix}{field_name.upper()}{NESTED_DELIMITER}"
            names |= _settable_env_vars(annotation, nested)
        else:
            names.add(f"{prefix}{field_name.upper()}")
    return names


def test_env_prefix_contract_is_what_the_docs_claim() -> None:
    """The documented prefix/delimiter must be the ones the settings model uses."""
    config = ServerSettings.model_config
    assert config.get("env_prefix") == ENV_PREFIX
    assert config.get("env_nested_delimiter") == NESTED_DELIMITER
    # extra="ignore" is why unprefixed legacy names must never be documented as
    # working: pydantic-settings drops them without a warning.
    assert config.get("extra") == "ignore"
    assert issubclass(ServerSettings, BaseSettings)


def test_configuration_doc_documents_every_settable_variable() -> None:
    documented = CONFIG_DOC.read_text(encoding="utf-8")
    missing = sorted(var for var in _settable_env_vars(ServerSettings) if var not in documented)

    assert not missing, (
        "docs/configuration.md is missing settable environment variables, but "
        "README.md promises it documents every GENCC_LINK_* variable. Add a row "
        f"for each of: {missing}"
    )
