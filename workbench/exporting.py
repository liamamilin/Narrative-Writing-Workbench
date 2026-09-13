"""Pure text export helpers for Product V0.2.

Article exports contain only the requested title/body. They deliberately know
nothing about plans, reviews, model calls, settings, or database internals.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import quote


FORMATS = {"md": "text/markdown", "txt": "text/plain"}


@dataclass(frozen=True)
class ExportArtifact:
    content: str
    media_type: str
    filename: str
    ascii_filename: str

    @property
    def headers(self):
        encoded = quote(self.filename, safe="")
        return {
            "Content-Disposition": (
                f'attachment; filename="{self.ascii_filename}"; '
                f"filename*=UTF-8''{encoded}"
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        }


def normalized_title(title):
    return re.sub(r"\s+", " ", title or "").strip()


def markdown_title(title):
    return re.sub(r"([\\`*_\[\]<>#])", r"\\\1", normalized_title(title))


def filename_base(title, fallback):
    base = normalized_title(title)
    base = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]+', "-", base)
    base = re.sub(r"\s+", " ", base).strip(" .-")
    return (base[:80].rstrip(" .-") or fallback)


def build_export(*, content, title, identifier, format_, include_title=True):
    if format_ not in FORMATS:
        raise ValueError("format must be md or txt")
    if type(include_title) is not bool:
        raise ValueError("include_title must be boolean")
    heading = normalized_title(title)
    rendered = content
    if include_title and heading:
        if format_ == "md":
            heading = f"# {markdown_title(heading)}"
        rendered = f"{heading}\n\n{content}"
    base = filename_base(title, f"draft-{identifier}")
    return ExportArtifact(
        content=rendered,
        media_type=FORMATS[format_],
        filename=f"{base}.{format_}",
        ascii_filename=f"draft-{identifier}.{format_}",
    )
