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


def _anchors(value: str, *, question: str = '', known_names: dict[str, set[str]] | None = None) -> list[tuple[str, str]]:
    """Prove name boundaries from a title, an approved name, or a comparison.

    A free sentence adjacent to IPN is not itself a feature name. Choosing a
    proved suffix leaves qualifiers and negation outside the projected span.
    """
    anchors = []
    known_names = known_names or {}
    def proved_name(fragment: str, ipn: str, *, comparison: bool = False) -> str:
        # Exact approved/configuration names are stronger than a title.
        known = [name for name, identities in known_names.items()
                 if ipn in identities and fragment.endswith(name)]
        if known:
            return max(known, key=len)
        # Strip complete grammatical operators, never arbitrary character
        # suffixes: "建议" must not leave a bogus name beginning with "议".
        operators = ('并非', '不是', '并不', '不再', '不会', '不能', '不得', '不应', '无需', '不支持',
                     '尚未支持', '尚未', '未支持', '已支持', '请确保', '确保', '建议', '推荐',
                     '仅限', '仅', '只', '新增', '增加', '升级', '更新', '启用', '禁用', '关闭', '打开', '开启', '具备', '实现', '采用', '通过', '支持', '未', '已', '请', '应当', '应',
                     '需', '必须', '可以', '可能', '可', '不', '非', '是', '尚', '暂未', '暂',
                     '确认', '不要', '不必', '没有', '从未', '从不', '是否', '有无', '包括', '包含')
        operator = re.compile('^(?:' + '|'.join(re.escape(word) for word in sorted(operators, key=len, reverse=True)) + ')')
        name = fragment
        while match := operator.match(name):
            name = name[match.end():].lstrip()
        base = re.sub(r'\s*\([^()]+\)$', '', clean_feature_name(name))
        # Unknown free clauses are not accepted merely because they are also
        # present in a question. Such fragments need an approved identity.
        uncertain = re.search(r'[？?！!]|(?:支持|包括|对应|提供|采用|属于|用于|可以|建议|请|[的是为了将])', name)
        uncertain_prefix = re.match(r'^[这那该此本其在将把对从经由予让如若虽尽凡按依有能要得改升增减删换变调修启停关开加合整执进完优实建推采通支提适作用考选保]', name)
        if not name or len(name) > 80 or uncertain or uncertain_prefix:
            return ''
        if len(base) >= 4 and (name in question or base in question):
            return name
        # A comparison supplies a controlled grammatical name boundary, e.g.
        # "不等同于DICOM接口包(IPN...)". Operators remain outside that name.
        if comparison:
            return name
        return ''
    for match in _ANNOTATION.finditer(value):
        before = value[:match.start()].rstrip()
        comparison = False
        if before.endswith(('”', '"')):
            quote = '“' if before.endswith('”') else '"'
            start = before.rfind(quote, 0, len(before) - 1)
            name = before[start + 1:-1] if start >= 0 else ''
        else:
            fragment = re.split(r'[。；;：:\n，,]', before)[-1].strip()
            comparison = '不等同于' in fragment
            name = fragment.rsplit('不等同于', 1)[-1].strip()
        name = proved_name(name, match['ipn'], comparison=comparison)
        if name:
            anchors.append((name, match['ipn']))
    # Existing controlled answers also use “NAME以主IPN 1234567查询”.
    for match in re.finditer(r'([^。；;：:\n，,]+?)以主IPN\s*(\d{7})查询', value, re.I):
        name = proved_name(match[1].strip(), match[2])
        if name:
            anchors.append((name, match[2]))
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

    def name_matches(self, value: str) -> list[set[str]]:
        if not self.aliases:
            return []
        pattern = re.compile('|'.join(re.escape(name) for name in sorted(self.aliases, key=len, reverse=True)))
        return [self.aliases[match[0]] for match in pattern.finditer(value)]

    def named_ipns(self, value: str) -> set[str]:
        return {ipn for matches in self.name_matches(value) for ipn in matches}

    def ambiguous_query(self, value: str) -> bool:
        return not self.explicit_ipns(value) and any(len(matches) > 1 for matches in self.name_matches(value))

    def project(self, value: str, *, explicit_ipns: set[str] | None = None) -> tuple[str, list[dict]]:
        allowed = explicit_ipns if explicit_ipns is not None else self.explicit_ipns(value)
        eligible = {name: next(iter(ipns)) for name, ipns in self.aliases.items()
                    if len(ipns) == 1 and next(iter(ipns)) in self.current
                    and (not allowed or next(iter(ipns)) in allowed)}
        if not eligible:
            return value, []
        pattern = re.compile('|'.join(re.escape(name) for name in sorted(self.aliases, key=len, reverse=True)))
        bindings = []
        def replace(match):
            name = match[0]
            if name not in eligible:
                return name
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
    if {'features', 'feature_names', 'feature_config_item_links'} <= tables:
        aliases = (await session.execute(text("""
            SELECT f.ipn,n.name FROM features f
            JOIN feature_names n ON n.feature_id=f.id
            JOIN feature_config_item_links l ON l.feature_id=f.id
            JOIN config_items c ON c.id=l.config_item_id
            WHERE n.language='cn' AND n.review_status='approved'
              AND l.relation_type='primary' AND l.review_status='approved'
              AND TRIM(c.ipn)=TRIM(f.ipn)
              AND (SELECT COUNT(*) FROM feature_config_item_links p
                   WHERE p.feature_id=f.id AND p.relation_type='primary' AND p.review_status='approved')=1
        """))).all()
        for ipn, name in aliases:
            context.add_alias(str(name), str(ipn).strip())
    if {'knowledge_questions', 'knowledge_answers'} <= tables:
        sources = (await session.execute(text('''
            SELECT q.question_text,a.answer_text FROM knowledge_questions q
            JOIN knowledge_answers a ON a.question_id=q.id
            WHERE a.review_status='published' AND q.status='answered'
        '''))).all()
        for question, answer in sources:
            for name, ipn in _anchors(str(answer or ''), question=str(question or ''), known_names=context.aliases):
                context.add_alias(name, ipn)
                # A trailing dimension qualifier may be omitted by a question;
                # it remains bound to this IPN and still participates in collisions.
                base = re.sub(r'\s*\([^()]+\)$', '', clean_feature_name(name))
                if base != clean_feature_name(name):
                    context.add_alias(base, ipn)
    return context
