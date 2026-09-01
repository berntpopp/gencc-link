"""Guard the GeneFoundry deploy contract for the numeric image user.

The fleet controller's deployment overlay must declare a numeric non-root
`user` for every service; the release Compose files must never declare one,
since the shared release gate forbids it there.
"""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
NUMERIC_USER = re.compile(r"^[1-9][0-9]*:[1-9][0-9]*$")


class _TolerantLoader(yaml.SafeLoader):
    """SafeLoader that tolerates unknown custom tags (e.g. Compose `!reset`)."""


_TolerantLoader.add_multi_constructor(
    "!",
    lambda loader, suffix, node: (
        loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None
    ),
)


def _load_compose(path: Path) -> dict:
    # _TolerantLoader subclasses yaml.SafeLoader; it only adds tolerance for
    # unknown custom tags (e.g. Compose's `!reset`), so this is not arbitrary
    # object instantiation despite the loader argument.
    return yaml.load(path.read_text(), Loader=_TolerantLoader)  # noqa: S506


def test_deploy_overlay_declares_numeric_user_for_every_service() -> None:
    compose = _load_compose(ROOT / "docker" / "docker-compose.npm.yml")
    services = compose["services"]
    assert services, "expected at least one service in docker-compose.npm.yml"
    for name, service in services.items():
        user = service.get("user")
        assert user is not None, f"service {name!r} is missing a numeric user"
        assert NUMERIC_USER.match(str(user)), (
            f"service {name!r} user {user!r} is not numeric non-root uid:gid"
        )


def test_release_compose_files_do_not_declare_user() -> None:
    release_config = json.loads((ROOT / "container-release.json").read_text())
    compose_files = release_config["service"]["compose_files"]
    assert compose_files, "expected container-release.json to list compose files"
    for rel_path in compose_files:
        compose = _load_compose(ROOT / rel_path)
        for name, service in compose["services"].items():
            assert "user" not in service, (
                f"release compose file {rel_path!r} service {name!r} must not declare user"
            )
