import os
import re


_REPORTS_DIR = "reports"


def _path_slug(path: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-")


def _default_output_path(repo: str, path: str) -> str:
    owner_repo = repo.replace("/", "-")
    return os.path.join(_REPORTS_DIR, f"{owner_repo}-{_path_slug(path)}.md")


def parse_sections(markdown: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_title is not None:
        sections.append((current_title, "\n".join(current_lines).strip()))
    return sections


def render(markdown: str, repo: str, path: str, output_path: str | None = None) -> str:
    if output_path is None:
        output_path = _default_output_path(repo, path)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# {repo} / {path}\n\n")
        f.write(markdown)
        f.write("\n")

    return output_path
