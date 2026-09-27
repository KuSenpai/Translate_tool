"""Format-preserving content model shared by reader, editor and writer."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Run(BaseModel):
    text: str
    b: bool = False   # bold
    i: bool = False   # italic
    u: bool = False   # underline


class Block(BaseModel):
    type: Literal["paragraph", "heading"] = "paragraph"
    level: Optional[int] = None            # heading level (1..3)
    align: Optional[Literal["left", "center", "right", "justify"]] = None
    runs: list[Run] = Field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


def blocks_to_text(blocks: list[Block]) -> str:
    return "\n\n".join(b.text for b in blocks)
