"""Read-only, IPN-bound projections of current configuration descriptions.

Stored questions, answers and evidence remain the historical source of truth.
Only names with a unique identity are projected; the same context powers search.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.feature_identity import clean_feature_name

_IPN = re.compile(r"(?i)(?<![A-Za-z0-9])IPN\s*[:：]?\s*(\d{7})(?!\d)")
_ANNOTATION = re.compile(r"[（(]\s*IPN\s*[:：]?\s*(?P<ipn>\d{7})\s*[）)]", re.I)


def _anchors(value: str) -> list[tuple[str, str]]:
    """Accept explicit name annotations, not arbitrary sentence/name guesses."""
    anchors = []
    for match in _ANNOTATION.finditer(value):
        before = value[:match.start()].rstrip()
        if before.endswith(('”', '"')):
            quote = '“' if before.endswith('”') else '"'
            start = before.rfind(quote, 0, len(before) - 1)
            name = before[start + 1:-1] if start >= 0 else ''
        else:
            fragment = re.split(r'[。；;：:\n，,]', before)[-1].strip()
            name = fragment.rsplit('不等同于', 1)[-1].strip()
        if name and len(name) <= 80 and not re.search(r'[？?！!]|(?:支持|包括|对应|提供|采用|属于|用于|可以)', name):
            anchors.append((name, match['ipn']))
    # Existing controlled answers also use “NAME以主IPN 1234567查询”.
    for match in re.finditer(r'([^。；;：:\n，,]+?)以主IPN\s*(\d{7})查询', value, re.I):
        anchors.append((match[1].strip(), match[2]))
    return anchors


@dataclass
class KnowledgeNameContext:
    current: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, set[str]] = field(default_factory=dict)
    item_ids: dict[str, int] = field(default_factory=dict)
    blocked: set[str] = field(default_factory=set)

    def add_alias(self, name: str, ipn: str) -> None:
        if not name:
            return
        self.aliases.setdefault(name, set()).add(ipn)
        cleaned = clean_feature_name(name)
        if cleaned:
            self.aliases.setdefault(cleaned, set()).add(ipn)

    def explicit_ipns(self, value: str) -> set[str]:
        return set(_IPN.findall(value))

    def named_ipns(self, value: str) -> set[str]:
        if not self.aliases:
            return set()
        pattern = re.compile('|'.join(re.escape(name) for name in sorted(self.aliases, key=len, reverse=True)))
        return {ipn for match in pattern.finditer(value) for ipn in self.aliases[match[0]]}

    def project(self, value: str, *, explicit_ipns: set[str] | None = None) -> tuple[str, list[dict]]:
        allowed = explicit_ipns if explicit_ipns is not None else self.explicit_ipns(value)
        eligible = {name: next(iter(ipns)) for name, ipns in self.aliases.items()
                    if len(ipns) == 1 and next(iter(ipns)) in self.current
                    and (not allowed or next(iter(ipns)) in allowed)}
        if not eligible:
            return value, []
        pattern = re.compile('|'.join(re.escape(name) for name in sorted(eligible, key=len, reverse=True)))
        bindings = []
        def replace(match):
            name = match[0]
            # Never rewrite the inside of a longer Latin identifier.
            if ((match.start() and name[0].isascii() and name[0].isalnum() and value[match.start()-1].isascii() and value[match.start()-1].isalnum())
                    or (match.end() < len(value) and name[-1].isascii() and name[-1].isalnum() and value[match.end()].isascii() and value[match.end()].isalnum())):
                return name
            ipn = eligible[name]
            current = self.current[ipn]
            if name != current:
                binding = {'ipn': ipn, 'source_name': name, 'current_name': current, 'config_item_id': self.item_ids[ipn]}
                if binding not in bindings:
                    bindings.append(binding)
            return current
        return pattern.sub(replace, value), bindings

    def question(self, question: str, answer: str = '') -> tuple[str, str, list[dict]]:
        explicit = self.explicit_ipns(question + '\n' + answer)
        displayed_question, first = self.project(question, explicit_ipns=explicit)
        displayed_answer, second = self.project(answer, explicit_ipns=explicit)
        return displayed_question, displayed_answer, first + [row for row in second if row not in first]


async def load_name_context(session: AsyncSession) -> KnowledgeNameContext:
    """Load one bounded catalog per request, shared by all projected rows."""
    context = KnowledgeNameContext()
    tables = set((await session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).scalars())
    if 'config_items' not in tables:
        return context
    rows = (await session.execute(text('SELECT id,ipn,zh_desc FROM config_items'))).mappings().all()
    by_ipn: dict[str, list] = {}
    for row in rows:
        ipn = str(row['ipn'] or '').strip()
        if ipn:
            by_ipn.setdefault(ipn, []).append(row)
    for ipn, matches in by_ipn.items():
        # Register all names for collision detection, including invalid identities.
        for row in matches:
            context.add_alias(clean_feature_name(row['zh_desc']), ipn)
        if len(matches) != 1 or not clean_feature_name(matches[0]['zh_desc']):
            context.blocked.add(ipn)
            continue
        context.current[ipn] = clean_feature_name(matches[0]['zh_desc'])
        context.item_ids[ipn] = int(matches[0]['id'])
    if {'knowledge_questions', 'knowledge_answers'} <= tables:
        sources = (await session.execute(text('''
            SELECT q.question_text,a.answer_text FROM knowledge_questions q
            JOIN knowledge_answers a ON a.question_id=q.id
            WHERE a.review_status='published' AND q.status='answered'
        '''))).all()
        for question, answer in sources:
            for name, ipn in _anchors(str(question or '') + '\n' + str(answer or '')):
                context.add_alias(name, ipn)
                # A trailing dimension qualifier may be omitted by a question;
                # it remains bound to this IPN and still participates in collisions.
                base = re.sub(r'\s*\([^()]+\)$', '', clean_feature_name(name))
                if base != clean_feature_name(name):
                    context.add_alias(base, ipn)
    return context
