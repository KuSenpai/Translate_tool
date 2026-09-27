"""Read a .docx file into an ordered list of `Block`s (paragraphs, headings, runs).

Streams word/document.xml with lxml `iterparse` instead of loading it through python-docx:
novels are often hundreds of MB of XML with tens of thousands of paragraphs split into many
tiny runs, and python-docx's per-run style lookups make that take many minutes.
"""
from __future__ import annotations

import re
import time
import zipfile
from pathlib import Path
from typing import Optional

from lxml import etree

from ..errors import DocxError
from ..logging_setup import get_logger
from .models import Block, Run

log = get_logger("DOCX")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_P, _R, _TBL, _BODY = W + "p", W + "r", W + "tbl", W + "body"
# Elements that wrap runs inside a paragraph (hyperlinks, tracked insertions, fields, content controls...).
_RUN_CONTAINERS = {W + t for t in ("hyperlink", "ins", "smartTag", "sdt", "sdtContent", "fldSimple",
                                   "customXml", "moveTo", "dir", "bdo")}
_ALIGN = {"center": "center", "right": "right", "end": "right", "both": "justify", "distribute": "justify",
          "left": "left", "start": "left"}
_HEADING_NAME = re.compile(r"^(heading|tiêu đề|제목)\s*(\d)$", re.IGNORECASE)
_OFF = {"0", "false", "off", "none"}


def _flag(rpr, tag: str) -> Optional[bool]:
    """Toggle property (w:b, w:i) of an rPr element: None when not set."""
    if rpr is None:
        return None
    el = rpr.find(W + tag)
    if el is None:
        return None
    return el.get(W + "val") not in _OFF


class _Styles:
    def __init__(self, zf: zipfile.ZipFile):
        self.raw: dict[str, dict] = {}
        self.default_para: Optional[str] = None
        self._memo: dict[tuple, bool] = {}
        try:
            root = etree.fromstring(zf.read("word/styles.xml"))
        except KeyError:
            return
        for s in root.iter(W + "style"):
            sid = s.get(W + "styleId")
            name_el, based_el = s.find(W + "name"), s.find(W + "basedOn")
            rpr = s.find(W + "rPr")
            ppr = s.find(W + "pPr")
            outline = ppr.find(W + "outlineLvl") if ppr is not None else None
            self.raw[sid] = {
                "name": name_el.get(W + "val") if name_el is not None else sid,
                "based": based_el.get(W + "val") if based_el is not None else None,
                "b": _flag(rpr, "b"), "i": _flag(rpr, "i"),
                "outline": int(outline.get(W + "val")) if outline is not None else None,
            }
            if s.get(W + "type") == "paragraph" and s.get(W + "default") in ("1", "true"):
                self.default_para = sid

    def flag(self, sid: Optional[str], key: str) -> bool:
        """Bold/italic of a style, following basedOn inheritance."""
        memo_key = (sid, key)
        if memo_key not in self._memo:
            val, cur, seen = None, sid, 0
            while cur and cur in self.raw and seen < 15:
                val = self.raw[cur][key]
                if val is not None:
                    break
                cur, seen = self.raw[cur]["based"], seen + 1
            self._memo[memo_key] = bool(val)
        return self._memo[memo_key]

    def heading_level(self, sid: Optional[str]) -> Optional[int]:
        st = self.raw.get(sid or "")
        if not st:
            return None
        name = (st["name"] or "").strip()
        if name.lower() == "title":
            return 1
        m = _HEADING_NAME.match(name)
        if m:
            return max(1, min(3, int(m.group(2))))
        if st["outline"] is not None and st["outline"] <= 2:
            return st["outline"] + 1
        return None


def _iter_runs(el):
    for c in el:
        if c.tag == _R:
            yield c
        elif c.tag in _RUN_CONTAINERS:
            yield from _iter_runs(c)


def _run_text(r) -> str:
    parts = []
    for c in r:
        tag = c.tag
        if tag == W + "t":
            parts.append(c.text or "")
        elif tag == W + "tab":
            parts.append("\t")
        elif tag in (W + "br", W + "cr"):
            parts.append("\n")
        elif tag == W + "noBreakHyphen":
            parts.append("-")
    return "".join(parts)


def _in_textbox(p) -> bool:
    """Paragraphs inside text boxes / drawings are skipped (Word stores them twice)."""
    anc = p.getparent()
    while anc is not None and anc.tag != _BODY:
        tag = anc.tag
        if tag.endswith("}txbxContent") or tag.endswith("}AlternateContent") or tag.endswith("}textbox"):
            return True
        anc = anc.getparent()
    return False


def _read_paragraph(p, styles: _Styles) -> Block:
    ppr = p.find(W + "pPr")
    style_id, align, level = styles.default_para, None, None
    if ppr is not None:
        ps = ppr.find(W + "pStyle")
        if ps is not None:
            style_id = ps.get(W + "val")
        jc = ppr.find(W + "jc")
        if jc is not None:
            align = _ALIGN.get(jc.get(W + "val"))
        ol = ppr.find(W + "outlineLvl")
        if ol is not None and ol.get(W + "val", "9").isdigit() and int(ol.get(W + "val")) <= 2:
            level = int(ol.get(W + "val")) + 1
    level = level or styles.heading_level(style_id)
    para_b = styles.flag(style_id, "b") if level is None else False
    para_i = styles.flag(style_id, "i")

    runs: list[Run] = []
    for r in _iter_runs(p):
        text = _run_text(r)
        if not text:
            continue
        rpr = r.find(W + "rPr")
        b, i, u = _flag(rpr, "b"), _flag(rpr, "i"), False
        if rpr is not None:
            rs = rpr.find(W + "rStyle")
            if rs is not None:
                cs = rs.get(W + "val")
                b = styles.flag(cs, "b") if b is None else b
                i = styles.flag(cs, "i") if i is None else i
            ue = rpr.find(W + "u")
            u = ue is not None and ue.get(W + "val", "single") not in _OFF
        b = para_b if b is None else b
        i = para_i if i is None else i
        prev = runs[-1] if runs else None
        if prev is not None and prev.b == b and prev.i == i and prev.u == u:
            prev.text += text  # merge adjacent runs with identical formatting
        else:
            runs.append(Run.model_construct(text=text, b=b, i=i, u=u))
    return Block.model_construct(type="heading" if level else "paragraph", level=level, align=align, runs=runs)


def read_docx(path: str | Path) -> list[Block]:
    path = Path(path)
    if not path.exists():
        raise DocxError(f"File không tồn tại: {path.name}", code="DOCX_NOT_FOUND")
    if path.suffix.lower() != ".docx":
        raise DocxError("Chỉ hỗ trợ file .docx (Word 2007 trở lên). File .doc cũ cần được lưu lại dưới dạng .docx.",
                        code="DOCX_BAD_TYPE")
    started = time.time()
    blocks: list[Block] = []
    try:
        with zipfile.ZipFile(path) as zf:
            styles = _Styles(zf)
            with zf.open("word/document.xml") as xml:
                for _, el in etree.iterparse(xml, events=("end",), tag=(_P, _TBL), huge_tree=True):
                    if el.tag == _P:
                        if not _in_textbox(el):
                            blocks.append(_read_paragraph(el, styles))
                        el.clear(keep_tail=True)
                    parent = el.getparent()
                    if parent is not None and parent.tag == _BODY:  # free memory as we go
                        while el.getprevious() is not None:
                            del parent[0]
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError, OSError) as e:
        raise DocxError(f"Không đọc được file Word (file hỏng hoặc không phải .docx): {e}", code="DOCX_UNREADABLE")
    log.info("Loaded file %s (%d blocks, %.1fs)", path.name, len(blocks), time.time() - started)
    return blocks
