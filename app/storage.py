from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

from .models import AppSettings, SENSITIVE_FIELDS
from .secrets import SecretStore


MASK = "********"


class SettingsStore:
    def __init__(self, db_path: Path, secret_store: SecretStore) -> None:
        self.db_path = db_path
        self.secret_store = secret_store
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def load(self, masked: bool = True) -> AppSettings:
        raw = self._load_raw()
        settings = AppSettings.model_validate(raw or {})
        data = settings.model_dump(mode="json")
        for field in SENSITIVE_FIELDS:
            section, name = field.split(".")
            secret = self.secret_store.get(field)
            if masked:
                data[section][name] = MASK if secret else ""
            else:
                data[section][name] = secret
        return AppSettings.model_validate(data)

    def save(self, settings: AppSettings) -> AppSettings:
        incoming = settings.model_dump(mode="json")
        current = self.load(masked=False).model_dump(mode="json")
        persisted = deepcopy(incoming)

        for field in SENSITIVE_FIELDS:
            section, name = field.split(".")
            value = incoming[section].get(name, "")
            if value == MASK:
                value = current[section].get(name, "")
            self.secret_store.set(field, value)
            persisted[section][name] = ""

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "insert or replace into settings (id, payload) values (1, ?)",
                (json.dumps(persisted, ensure_ascii=False),),
            )
        return self.load(masked=True)

    def export_public(self) -> Dict[str, Any]:
        return self.load(masked=True).model_dump(mode="json")

    def reset(self) -> AppSettings:
        default_settings = AppSettings()
        for field in SENSITIVE_FIELDS:
            self.secret_store.delete(field)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "insert or replace into settings (id, payload) values (1, ?)",
                (json.dumps(default_settings.model_dump(mode="json"), ensure_ascii=False),),
            )
        return self.load(masked=True)

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("create table if not exists settings (id integer primary key, payload text not null)")

    def _load_raw(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("select payload from settings where id = 1").fetchone()
        if not row:
            return {}
        return json.loads(row[0])
