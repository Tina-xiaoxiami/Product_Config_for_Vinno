"""Replace only verified text tokens in the Cart template's existing shapes."""

from collections import defaultdict
from io import BytesIO
from zipfile import ZipFile

from lxml import etree


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
    offset = 0
    for run in runs:
        length = len(run.text or "")
        if length:
            run.text = updated[offset:offset + length]
        offset += length


def replace_tokens(data, patches):
    if not patches:
        return data
    updates = defaultdict(list)
    for rule, replacement in patches:
        if len(rule.original) != len(replacement):
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
