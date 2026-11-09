"""Load the operator's reviewed Cart template, snapshot and page bindings."""

import os
from pathlib import Path
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


MARKET_FOLDERS = {"domestic": "国内", "overseas": "海外"}
CART_TEXT = re.compile(r"(?<![a-z])cart(?![a-z])|trolley|台车|推车|电池面板|电源面板", re.IGNORECASE)
Market = Literal["domestic", "overseas"]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Page = Annotated[int, Field(ge=1, le=200)]
Code = Annotated[str, StringConstraints(pattern=r"^V[0-9]+$")]
IPN = Annotated[str, StringConstraints(pattern=r"^[0-9]+(-[0-9]+)?$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Anchor(StrictModel):
    series: str
    version: str
    sha256: Digest


class TokenRule(StrictModel):
    series: tuple[str, ...] = Field(min_length=1)
    code: Code
    ipn: IPN
    field: Literal["ipn", "v_code"]
    targets: tuple[tuple[Page, Annotated[str, StringConstraints(pattern=r"^[0-9]+$")]], ...] = Field(min_length=1)

    @property
    def original(self):
        return self.ipn if self.field == "ipn" else self.code


class Template(StrictModel):
    filename: str
    sha256: Digest
    anchors: tuple[Anchor, ...] = Field(min_length=1)
    rules: tuple[TokenRule, ...] = ()
    review_notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_bindings(self):
        if Path(self.filename).name != self.filename or "\\" in self.filename or not self.filename.endswith(".pptx"):
            raise ValueError("模板文件名必须是 PPTX 文件名")
        series = {anchor.series for anchor in self.anchors}
        if len(series) != len(self.anchors):
            raise ValueError("同一系列只可绑定一份配置基线")
        for rule in self.rules:
            if not set(rule.series) <= series or len(set(rule.series)) != len(rule.series):
                raise ValueError("替换规则必须绑定唯一的已核验系列")
            if len(set(rule.targets)) != len(rule.targets):
                raise ValueError("替换规则的页面定位重复")
        return self


class Rules(StrictModel):
    version: str = ""
    templates: dict[Market, Template] = Field(default_factory=dict)
    common_pages: dict[Code, tuple[Page, ...]] = Field(default_factory=dict)
    market_pages: dict[Market, dict[Code, tuple[Page, ...]]] = Field(default_factory=dict)
    ipn_pages: dict[IPN, tuple[Page, ...]] = Field(default_factory=dict)

    @property
    def known_codes(self):
        mapped = set(self.common_pages).union(*(pages.keys() for pages in self.market_pages.values()))
        return mapped | {rule.code for template in self.templates.values() for rule in template.rules}

    @property
    def known_ipns(self):
        return set(self.ipn_pages).union(rule.ipn for template in self.templates.values() for rule in template.rules)

    def market(self, name):
        for market, template in self.templates.items():
            if any(anchor.series == name for anchor in template.anchors):
                return market
        suffix = name.rsplit("-", 1)[-1].strip().casefold()
        return {"china": "domestic", "oversea": "overseas", "overseas": "overseas"}.get(suffix)

    @model_validator(mode="after")
    def validate_markets(self):
        names = [anchor.series for template in self.templates.values() for anchor in template.anchors]
        if len(names) != len(set(names)):
            raise ValueError("同一系列不可绑定不同市场")
        if self.templates and not self.version:
            raise ValueError("模板规则必须有版本号")
        return self


def load_rules():
    path = os.environ.get("CART_RELEASE_RULES_FILE")
    if not path:
        return Rules()
    with Path(path).open("rb") as stream:
        data = stream.read(128 * 1024 + 1)
    if len(data) > 128 * 1024:
        raise ValueError("Cart 规则文件过大")
    return Rules.model_validate_json(data)
