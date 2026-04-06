from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MigrationStep:
    from_version: tuple[int, int]
    to_version: tuple[int, int]
    module_path: str

    @property
    def name(self) -> str:
        return self.module_path.rsplit(".", 1)[-1]

    def version_text(self) -> str:
        return f"{self.to_version[0]}.{self.to_version[1]}"


MIGRATIONS: tuple[MigrationStep, ...] = (
    MigrationStep((0, 2), (0, 3), "services.migrations.v0_2_to_0_3"),
)
