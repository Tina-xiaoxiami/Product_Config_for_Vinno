"""Identify explicit numbered PDF sections, excluding table-of-contents entries."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import re
from pypdf import PdfReader
from tracker.services.search_index import file_snapshot

_HEADING = re.compile(r'^\s*(\d+(?:\.\d+)+)\s+(.+?)\s*$')
_TOC = re.compile(r'(?:\.{3,}|…{2,}|·{3,}|\s{3,})\s*\d+\s*$')


def pdf_section(path, expected_sha: str, source_id: str, query: str, locator: str = '') -> dict | None:
    if not query:
        return None
    try:
        before = file_snapshot(path)
        if before.digest != expected_sha:
            return None
        raw = before.path.read_bytes()
        if sha256(raw).hexdigest() != before.digest or file_snapshot(path) != before:
            return None
        reader = PdfReader(BytesIO(raw), strict=False)
        lines = [(page_no, line.strip()) for page_no, page in enumerate(reader.pages, 1)
                 for line in (page.extract_text() or '').splitlines() if line.strip()]
    except Exception:
        return None
    headings = []
    for index, (page_no, line) in enumerate(lines):
        match = _HEADING.match(line)
        if not match or _TOC.search(line):
            continue
        number, title = match.groups()
        headings.append((index, page_no, number, title))
    options = []
    for pos, (start, page_no, number, title) in enumerate(headings):
        level = len(number.split('.'))
        end = next((entry[0] for entry in headings[pos + 1:] if len(entry[2].split('.')) <= level), None)
        if end is None:
            continue
        content = lines[start:end]
        if query.casefold() not in '\n'.join(line for _, line in content).casefold():
            continue
        options.append((query.casefold() not in title.casefold(), start, page_no, number, title, content))
    if not options:
        return None
    locator_match = re.fullmatch(r'第 (\d+) 页(?: · \d+)?', locator or '')
    locator_status = 'query'
    if locator:
        if not locator_match:
            return None
        requested_page = int(locator_match.group(1))
        on_page = [item for item in options if item[2] <= requested_page <= item[5][-1][0]]
        if len(on_page) == 1:
            options = on_page
            locator_status = 'exact'
        elif on_page:
            return None
        else:
            toc_numbers = {match.group(1) for page, line in lines if page == requested_page
                           and query.casefold() in line.casefold() and _TOC.search(line)
                           if (match := _HEADING.match(line))}
            if len(toc_numbers) != 1:
                return None
            options = [item for item in options if item[3] in toc_numbers]
            if len(options) != 1:
                return None
            locator_status = 'toc_redirect'
    elif len(options) != 1:
        return None
    _, _, page_no, number, title, content = options[0]
    # An indexed page locator remains valid for comparison and PDF navigation.
    has_images = any(bool(reader.pages[page - 1].images) for page in set(number for number, _ in content))
    return {'source_id': source_id, 'locator_status': locator_status, 'locator': f'第 {page_no} 页', 'section_number': number,
            'title': title, 'start': page_no, 'end': content[-1][0],
            'content': '\n'.join(line for _, line in content), 'complete': True, 'text_complete': True,
            'has_images': has_images, 'images_complete': not has_images, 'blocks': []}
