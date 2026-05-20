import hashlib
import json
import os
import re
from typing import Any

_CACHE_DIR = ".archaeologist_cache"


def _repo_slug(repo: str) -> str:
    return repo.replace("/", "-")


def _path_slug(path: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-")


def fetch_cache_path(repo: str, path: str) -> str:
    return os.path.join(_CACHE_DIR, _repo_slug(repo), f"{_path_slug(path)}.json")


def summaries_cache_path(repo: str, path: str) -> str:
    return os.path.join(_CACHE_DIR, _repo_slug(repo), f"{_path_slug(path)}-summaries.json")


def load(cache_file: str) -> dict[str, Any] | None:
    try:
        with open(cache_file, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save(cache_file: str, data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def chunk_hash(chunk: dict[str, Any]) -> str:
    content = json.dumps(chunk["commits"], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode()).hexdigest()[:16]
