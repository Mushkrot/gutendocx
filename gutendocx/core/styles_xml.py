import os
import shutil
import tempfile
import zipfile
from typing import Any, Dict, Iterable, List, Set

from lxml import etree


class StylesXml:
    def apply_overrides(self, document, overrides):
        raise NotImplementedError

    def remap_styles(self, document, rules):
        raise NotImplementedError


def cleanup_styles_xml(docx_path: str, keep_style_ids: Iterable[str]) -> Dict[str, Any]:
    """Remove unused styles from word/styles.xml in the given DOCX.

    Only styles whose styleId is present in keep_style_ids (plus any styles
    they depend on via basedOn/link/next and any default styles) are
    preserved. All other <w:style> entries are removed.
    """

    keep: Set[str] = {str(sid) for sid in (keep_style_ids or []) if sid}
    if not keep:
        return {"before": 0, "after": 0, "removed": [], "skipped": True}

    if not os.path.isfile(docx_path):
        return {"before": 0, "after": 0, "removed": [], "skipped": True}

    try:
        with zipfile.ZipFile(docx_path, "r") as zin:
            try:
                styles_xml = zin.read("word/styles.xml")
            except KeyError:
                return {"before": 0, "after": 0, "removed": [], "skipped": True}
    except Exception:
        return {"before": 0, "after": 0, "removed": [], "skipped": True}

    try:
        root = etree.fromstring(styles_xml)
    except Exception:
        return {"before": 0, "after": 0, "removed": [], "skipped": True}

    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ns = {"w": W_NS}

    styles: List[etree._Element] = root.xpath("w:style", namespaces=ns)  # type: ignore[attr-defined]

    all_ids: List[str] = []
    deps: Dict[str, Set[str]] = {}

    for st in styles:
        sid = st.get(f"{{{W_NS}}}styleId")
        if not sid:
            continue
        all_ids.append(sid)
        dset = deps.setdefault(sid, set())
        for tag in ("basedOn", "link", "next"):
            el = st.find(f"{{{W_NS}}}{tag}")
            if el is not None:
                val = el.get(f"{{{W_NS}}}val")
                if val:
                    dset.add(val)

    keep_closure: Set[str] = set(keep)

    # Always keep default styles (w:default="1") regardless of keep list.
    for st in styles:
        sid = st.get(f"{{{W_NS}}}styleId")
        if not sid:
            continue
        if st.get(f"{{{W_NS}}}default") == "1":
            keep_closure.add(sid)

    # Expand keep set to include dependencies (basedOn/link/next).
    changed = True
    while changed:
        changed = False
        for sid, dset in deps.items():
            if sid in keep_closure:
                for dep in dset:
                    if dep not in keep_closure:
                        keep_closure.add(dep)
                        changed = True

    delete_ids: Set[str] = set()
    for st in list(styles):
        sid = st.get(f"{{{W_NS}}}styleId")
        if not sid:
            continue
        if sid not in keep_closure:
            delete_ids.add(sid)
            parent = st.getparent()
            if parent is not None:
                parent.remove(st)

    if not delete_ids:
        return {
            "before": len(all_ids),
            "after": len(all_ids),
            "removed": [],
            "skipped": False,
        }

    new_styles_bytes = etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=False,
    )

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
            tmp_path = tmp.name

        with zipfile.ZipFile(docx_path, "r") as zin, zipfile.ZipFile(
            tmp_path, "w", zipfile.ZIP_DEFLATED
        ) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/styles.xml":
                    data = new_styles_bytes
                zout.writestr(item, data)

        shutil.move(tmp_path, docx_path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return {
        "before": len(all_ids),
        "after": len(all_ids) - len(delete_ids),
        "removed": sorted(delete_ids),
        "skipped": False,
    }
