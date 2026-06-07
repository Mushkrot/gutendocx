from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from docx.oxml.ns import qn

from .scan import _style_name


WORD_CLEANUP_REPLACEMENT = "^p"
_PATTERN_SPLIT_RE = re.compile(r"[\s,;]+")
_SUPPORTED_CODES = {"p", "l"}


def parse_word_cleanup_patterns(value: Any) -> List[str]:
    """Parse user-entered Word mark patterns into normalized ^p/^l sequences."""

    raw_parts: List[str] = []
    if isinstance(value, str):
        raw_parts.extend(_PATTERN_SPLIT_RE.split(value.strip()))
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            if isinstance(item, str):
                raw_parts.extend(_PATTERN_SPLIT_RE.split(item.strip()))
    elif value is None:
        raw_parts = []
    else:
        raise ValueError("Word cleanup patterns must be text or a list of text patterns.")

    patterns: List[str] = []
    seen = set()
    for raw in raw_parts:
        part = str(raw or "").strip()
        if not part:
            continue
        normalized = _normalize_word_cleanup_pattern(part)
        if normalized not in seen:
            patterns.append(normalized)
            seen.add(normalized)
    return patterns


def _normalize_word_cleanup_pattern(pattern: str) -> str:
    tokens: List[str] = []
    pos = 0
    while pos < len(pattern):
        if pattern[pos] != "^" or pos + 1 >= len(pattern):
            raise ValueError(
                f"Unsupported Word cleanup pattern '{pattern}'. Use only ^p and ^l."
            )
        code = pattern[pos + 1].lower()
        if code not in _SUPPORTED_CODES:
            raise ValueError(
                f"Unsupported Word cleanup code '^{pattern[pos + 1]}'. Use only ^p and ^l."
            )
        tokens.append(f"^{code}")
        pos += 2
    if not tokens:
        raise ValueError("Word cleanup pattern is empty.")
    return "".join(tokens)


def _pattern_tokens(pattern: str) -> Tuple[str, ...]:
    normalized = _normalize_word_cleanup_pattern(pattern)
    return tuple(normalized[i + 1] for i in range(0, len(normalized), 2))


def _manual_line_break_count(p) -> int:
    count = 0
    try:
        for br in p._element.xpath(".//w:br"):
            br_type = br.get(qn("w:type"))
            if br_type in (None, "", "textWrapping"):
                count += 1
    except Exception:
        return 0
    return count


def _has_page_column_or_section_break(p) -> bool:
    try:
        if p._element.xpath('.//w:br[@w:type="page" or @w:type="column"]'):
            return True
        if p._element.xpath("./w:pPr/w:sectPr"):
            return True
    except Exception:
        return True
    try:
        if bool(getattr(p.paragraph_format, "page_break_before", False)):
            return True
    except Exception:
        pass
    return False


def _has_field_or_object_content(p) -> bool:
    checks = (
        ".//w:fldChar",
        ".//w:instrText",
        ".//w:drawing",
        ".//w:pict",
        ".//w:object",
    )
    try:
        return any(p._element.xpath(path) for path in checks)
    except Exception:
        return True


def _is_protected_style_name(name: str, config: Dict[str, Any]) -> bool:
    protected_names = {
        "Title",
        "Subtitle",
        "Author",
        "Cover Title",
        "Cover Subtitle",
        "Cover Author",
        "Header",
        "Footer",
    }
    detected_mapping = (config or {}).get("detected_style_mapping", {}) or {}
    detected_heading_names = {
        str(v)
        for k, v in detected_mapping.items()
        if str(k) in ("Headings", "Heading1", "Heading2", "Heading3", "Heading4") and v
    }
    lname = name.lower()
    return (
        name in protected_names
        or name.startswith("Heading ")
        or name.startswith("Heading")
        or name in detected_heading_names
        or lname.startswith("toc")
    )


def _is_cleanable_blank_paragraph(p, config: Dict[str, Any]) -> bool:
    try:
        text = p.text or ""
    except Exception:
        return False
    if text.strip():
        return False

    name = _style_name(getattr(p, "style", None)) or ""
    if name and _is_protected_style_name(name, config):
        return False
    if _has_page_column_or_section_break(p):
        return False
    if _has_field_or_object_content(p):
        return False
    return True


def _contains_pattern(tokens: List[str], pattern: Tuple[str, ...]) -> bool:
    if not pattern or len(pattern) > len(tokens):
        return False
    plen = len(pattern)
    for start in range(0, len(tokens) - plen + 1):
        if tuple(tokens[start : start + plen]) == pattern:
            return True
    return False


def _gap_matches(records: List[Dict[str, Any]], patterns: List[Tuple[str, ...]]) -> bool:
    tokens: List[str] = []
    for rec in records:
        tokens.append("p")
        tokens.extend("l" for _ in range(int(rec.get("line_breaks", 0))))
    return any(_contains_pattern(tokens, pattern) for pattern in patterns)


def _gap_tokens(records: List[Dict[str, Any]]) -> List[str]:
    tokens: List[str] = []
    for rec in records:
        tokens.append("p")
        tokens.extend("l" for _ in range(int(rec.get("line_breaks", 0))))
    return tokens


def _token_pattern_to_word_code(tokens: Sequence[str]) -> str:
    return "".join(f"^{token}" for token in tokens)


def _iter_cleanable_gaps(doc, config: Dict[str, Any], body_start: int) -> List[List[Dict[str, Any]]]:
    gaps: List[List[Dict[str, Any]]] = []
    current_gap: List[Dict[str, Any]] = []

    def flush_gap() -> None:
        nonlocal current_gap
        if current_gap:
            gaps.append(current_gap)
            current_gap = []

    paragraphs_snapshot = list(getattr(doc, "paragraphs", []) or [])
    for idx, p in enumerate(paragraphs_snapshot):
        if idx < body_start:
            continue
        if _is_cleanable_blank_paragraph(p, config):
            current_gap.append(
                {
                    "paragraph": p,
                    "line_breaks": _manual_line_break_count(p),
                }
            )
        else:
            flush_gap()
    flush_gap()
    return gaps


def analyze_word_cleanup(doc, config: Dict[str, Any], body_start: int) -> Dict[str, Any]:
    """Return safe cleanup recommendations for parasite ^p/^l body gaps."""

    gaps = _iter_cleanable_gaps(doc, config, body_start)
    candidates: Dict[str, Dict[str, Any]] = {}

    def add_candidate(pattern: str, gap: List[Dict[str, Any]]) -> None:
        cur = candidates.setdefault(
            pattern,
            {
                "pattern": pattern,
                "occurrences": 0,
                "sample_gap_shapes": [],
                "confidence": "high",
            },
        )
        cur["occurrences"] += 1
        if len(cur["sample_gap_shapes"]) < 3:
            cur["sample_gap_shapes"].append(_token_pattern_to_word_code(_gap_tokens(gap)))

    for gap in gaps:
        if len(gap) >= 2:
            add_candidate("^p^p", gap)
        for rec in gap:
            line_breaks = int(rec.get("line_breaks", 0))
            if line_breaks > 0:
                add_candidate("^p" + ("^l" * line_breaks), gap)

    recommended_patterns = sorted(
        candidates.keys(),
        key=lambda p: (
            0 if p == "^p^p" else 1,
            len(p),
            p,
        ),
    )
    pattern_tokens = [_pattern_tokens(pattern) for pattern in recommended_patterns]

    matched_gaps: List[List[Dict[str, Any]]] = []
    for gap in gaps:
        if _gap_matches(gap, pattern_tokens):
            matched_gaps.append(gap)

    paragraphs_to_remove = sum(len(gap) for gap in matched_gaps)
    line_breaks_to_remove = sum(int(rec.get("line_breaks", 0)) for gap in matched_gaps for rec in gap)
    total_cleanable_paragraphs = sum(len(gap) for gap in gaps)
    total_cleanable_line_breaks = sum(int(rec.get("line_breaks", 0)) for gap in gaps for rec in gap)

    candidates_list = [
        {
            **candidates[pattern],
            "reason": "Repeated blank paragraph gap" if pattern == "^p^p" else "Blank paragraph with manual line breaks",
        }
        for pattern in recommended_patterns
    ]

    report_lines: List[str] = []
    if recommended_patterns:
        report_lines.append(
            f"Found {len(matched_gaps)} cleanup gap(s). Recommended cleanup would remove "
            f"{paragraphs_to_remove} empty paragraph(s) and {line_breaks_to_remove} manual line break(s)."
        )
        report_lines.append("Text paragraphs, headings, TOC, section/page breaks, fields, and embedded objects are skipped.")
    else:
        report_lines.append("No high-confidence parasite Word-mark cleanup candidates were found.")

    return {
        "recommended_patterns": recommended_patterns,
        "candidates": candidates_list,
        "summary": {
            "cleanable_gaps": len(gaps),
            "recommended_gaps": len(matched_gaps),
            "cleanable_paragraphs": total_cleanable_paragraphs,
            "cleanable_line_breaks": total_cleanable_line_breaks,
            "paragraphs_to_remove": paragraphs_to_remove,
            "line_breaks_to_remove": line_breaks_to_remove,
        },
        "report": "\n".join(report_lines),
    }


def apply_word_cleanup(doc, config: Dict[str, Any], body_start: int) -> Dict[str, Any]:
    cleanup_cfg = ((config or {}).get("word_cleanup") or {}) or {}
    enabled = bool(cleanup_cfg.get("enabled", False))
    raw_patterns = cleanup_cfg.get("patterns", [])
    replacement = cleanup_cfg.get("replacement") or WORD_CLEANUP_REPLACEMENT

    patterns: List[str] = []
    if enabled:
        patterns = parse_word_cleanup_patterns(raw_patterns)
    else:
        try:
            patterns = parse_word_cleanup_patterns(raw_patterns)
        except ValueError:
            patterns = []

    result: Dict[str, Any] = {
        "enabled": enabled,
        "patterns": patterns,
        "replacement": WORD_CLEANUP_REPLACEMENT,
        "applied": False,
        "gaps_modified": 0,
        "paragraphs_removed": 0,
        "line_breaks_removed": 0,
    }

    if not enabled or not patterns:
        return result
    if replacement != WORD_CLEANUP_REPLACEMENT:
        raise ValueError("Word cleanup replacement is fixed to ^p in this version.")

    pattern_tokens = [_pattern_tokens(pattern) for pattern in patterns]
    matched_records: List[Dict[str, Any]] = []
    for gap in _iter_cleanable_gaps(doc, config, body_start):
        if _gap_matches(gap, pattern_tokens):
            matched_records.extend(gap)
            result["gaps_modified"] += 1

    for rec in matched_records:
        p = rec.get("paragraph")
        if p is None:
            continue
        parent = p._element.getparent()
        if parent is None:
            continue
        parent.remove(p._element)
        result["paragraphs_removed"] += 1
        result["line_breaks_removed"] += int(rec.get("line_breaks", 0))

    result["applied"] = bool(result["paragraphs_removed"] or result["line_breaks_removed"])
    return result
