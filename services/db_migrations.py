from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MigrationStep:
    from_version: int
    to_version: int
    file_path: Path

    @property
    def name(self) -> str:
        return self.file_path.name

    def version_text(self) -> str:
        return str(self.to_version)


_MIGRATION_FILE_RE = re.compile(r"^(\d+)-(\d+)\.py$")


def _discover_migrations() -> tuple[MigrationStep, ...]:
    migrations_dir = Path(__file__).resolve().parent / "migrations"
    steps: list[MigrationStep] = []

    if not migrations_dir.is_dir():
        return ()

    for file_path in migrations_dir.iterdir():
        if not file_path.is_file():
            continue
        match = _MIGRATION_FILE_RE.match(file_path.name)
        if not match:
            continue
        from_version = int(match.group(1))
        to_version = int(match.group(2))
        steps.append(
            MigrationStep(
                from_version=from_version,
                to_version=to_version,
                file_path=file_path,
            )
        )

    steps.sort(key=lambda s: (s.from_version, s.to_version, s.file_path.name))
    return tuple(steps)


MIGRATIONS: tuple[MigrationStep, ...] = _discover_migrations()
