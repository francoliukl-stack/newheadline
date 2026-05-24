from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Dict


class SecretStore:
    def __init__(
        self,
        path: Path,
        service: str = "weekly-headlines-settings",
        use_keychain: bool = True,
    ) -> None:
        self.path = path
        self.service = service
        self.use_keychain = use_keychain
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def set(self, key: str, value: str) -> None:
        if value == "":
            self.delete(key)
            return
        if self.use_keychain and self._security(["add-generic-password", "-U", "-s", self.service, "-a", key, "-w", value]):
            return
        data = self._read_file()
        data[key] = value
        self._write_file(data)

    def get(self, key: str) -> str:
        if self.use_keychain:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", self.service, "-a", key, "-w"],
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        return self._read_file().get(key, "")

    def delete(self, key: str) -> None:
        if self.use_keychain:
            self._security(["delete-generic-password", "-s", self.service, "-a", key])
        data = self._read_file()
        if key in data:
            del data[key]
            self._write_file(data)

    def _security(self, args: list[str]) -> bool:
        try:
            return subprocess.run(["security", *args], capture_output=True, check=False).returncode == 0
        except FileNotFoundError:
            return False

    def _read_file(self) -> Dict[str, str]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write_file(self, data: Dict[str, str]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.chmod(self.path, 0o600)
