"""Resolve legacy probe exclusions using only an explicit application catalog."""
from collections.abc import Iterable
import re


def expand_exclusion_name(name: str, application_names: Iterable[str]) -> list[str]:
    """Expand a shared suffix only when the catalog admits exactly one reading."""
    name = name.strip()
    catalog = {value.strip() for value in application_names if isinstance(value, str)}
    if name in catalog:
        return [name]
    parts = [part.strip() for part in re.split(r"[\\/]", name)]
    if len(parts) < 2 or not all(parts) or parts[-1] not in catalog:
        return [name]
    matches = set()
    for start in range(1, len(parts[-1]) + 1):
        suffix = parts[-1][start:]
        expanded = tuple([part + suffix for part in parts[:-1]] + [parts[-1]])
        if all(value in catalog for value in expanded):
            matches.add(expanded)
    return list(next(iter(matches))) if len(matches) == 1 else [name]


def _parenthesis_groups(text: str) -> list[tuple[int, int]]:
    stack = []
    groups = []
    pairs = {")": "(", "）": "（"}
    for index, char in enumerate(text):
        if char in "(（":
            stack.append((char, index))
        elif char in ")）":
            if not stack or stack[-1][0] != pairs[char]:
                raise ValueError("排除限制的括号不平衡，请核对原单元格")
            _, start = stack.pop()
            if not stack:
                groups.append((start, index))
    if stack:
        raise ValueError("排除限制的括号不平衡，请核对原单元格")
    return groups


def _split_exclusions(text: str) -> list[str]:
    depth = 0
    start = 0
    names = []
    for index, char in enumerate(text):
        if char in "(（":
            depth += 1
        elif char in ")）":
            depth -= 1
        elif char in ",，、" and depth == 0:
            names.append(text[start:index].strip())
            start = index + 1
    names.append(text[start:].strip())
    return [name for name in names if name]


def parse_exclusions(cell_text: str, application_names: Iterable[str]) -> list[str] | None:
    """Keep full unknown restrictions; malformed exclusion syntax is an error."""
    text = str(cell_text or "").strip()
    if "除" not in text:
        return None
    groups = _parenthesis_groups(text)
    names = []
    outside = []
    end = 0
    for start, close in groups:
        outside.append(text[end:start])
        end = close + 1
        content = text[start + 1:close].strip()
        if content.startswith("除"):
            tokens = _split_exclusions(content[1:])
            if not tokens:
                raise ValueError("排除限制为空，请核对原单元格")
            names.extend(tokens)
        elif "除" in content:
            raise ValueError("排除限制必须完整写在括号内并以“除”开头")
    outside.append(text[end:])
    if "除" in "".join(outside) or not names:
        raise ValueError("排除限制必须完整写在括号内并以“除”开头")
    catalog = tuple(application_names)
    return list(dict.fromkeys(
        expanded for name in names for expanded in expand_exclusion_name(name, catalog)
    ))
