"""Replace only verified text tokens in the Cart template's existing shapes."""

from collections import defaultdict
from io import BytesIO
from unicodedata import east_asian_width
from zipfile import ZipFile

from lxml import etree

from app.services.cart_release_rules import FactRule


NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


def _patch_shape(root, page, shape_id, old, new):
    shapes = root.xpath(".//p:sp[p:nvSpPr/p:cNvPr/@id=$sid]", namespaces=NS, sid=shape_id)
    matches = []
    if len(shapes) == 1:
        for paragraph in shapes[0].findall("./p:txBody/a:p", NS):
            runs = paragraph.findall("./a:r/a:t", NS)
            line = "".join(run.text or "" for run in runs)
            start = line.find(old)
            if start >= 0:
                matches.append((runs, line, start))
    if len(matches) != 1 or matches[0][1].count(old) != 1:
        raise ValueError(f"第 {page} 页形状 {shape_id} 的原文定位不唯一或不匹配")
    runs, line, start = matches[0]
    updated = line[:start] + new + line[start + len(old):]
    if len(old) != len(new):
        offset = 0
        for run in runs:
            value = run.text or ""
            relative = start - offset
            if relative >= 0 and value[relative:relative + len(old)] == old:
                run.text = value[:relative] + new + value[relative + len(old):]
                return
            offset += len(value)
        raise ValueError(f"第 {page} 页形状 {shape_id} 的可变事实跨越多个样式段")
    offset = 0
    for run in runs:
        length = len(run.text or "")
        if length:
            run.text = updated[offset:offset + length]
        offset += length


def _width(text):
    return sum(2 if east_asian_width(char) in ("W", "F", "A") else 1 for char in text)


def replace_tokens(data, patches):
    if not patches:
        return data
    updates = defaultdict(list)
    for rule, replacement in patches:
        if isinstance(rule, FactRule):
            if not replacement.isprintable() or _width(replacement) > _width(rule.original):
                raise ValueError("事实文字超过核验版面容量或包含换行")
        elif len(rule.original) != len(replacement):
            raise ValueError("替换长度与原料号不一致")
        for page, shape_id in rule.targets:
            updates[f"ppt/slides/slide{page}.xml"].append((page, shape_id, rule.original, replacement))
    output = BytesIO()
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    with ZipFile(BytesIO(data)) as source, ZipFile(output, "w") as destination:
        names = source.namelist()
        if sum(member.file_size for member in source.infolist()) > 64 * 1024 * 1024:
            raise ValueError("模板展开后超过大小上限")
        if len(set(names)) != len(names) or updates.keys() - set(names):
            raise ValueError("模板页面结构与已核验的定位不一致")
        destination.comment = source.comment
        for member in source.infolist():
            content = source.read(member)
            if member.filename in updates:
                root = etree.fromstring(content, parser)
                for patch in updates[member.filename]:
                    _patch_shape(root, *patch)
                content = etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
            destination.writestr(member, content)
    return output.getvalue()



def build_candidate(data, patches):
    """Keep independent verified edits when another binding fails its layout checks."""
    try:
        return replace_tokens(data, patches), patches, []
    except ValueError:
        if not patches:
            raise
    applied, rejected = [], []
    content = data
    for patch in patches:
        try:
            content = replace_tokens(data, [*applied, patch])
        except ValueError as error:
            rejected.append({
                "pages": sorted({page for page, _ in patch[0].targets}), "detail": str(error),
            })
        else:
            applied.append(patch)
    return content if applied else None, applied, rejected
