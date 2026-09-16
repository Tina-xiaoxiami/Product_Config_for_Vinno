"""导出 Excel 时的文本安全处理。

以 ``=`` 开头的字符串在 xlsx 里会被当成**公式**。导出件是发给同事打开的文件，
配置项名称、IPN、描述、功能名称这些都来自上传的 Excel，因此一条
``=HYPERLINK("http://…","点击")`` 或 DDE 载荷（``=cmd|' /c calc'!A0``）就能在
别人打开导出件时求值。

这里在保存前把这类单元格强制标记为文本类型：openpyxl 决定 ``data_type`` 时只看
内容是否以 ``=`` 开头，改成 ``'s'`` 之后内容一字不改，但不再作为公式存储。
"""

from __future__ import annotations

from typing import Any


def neutralize_formulas(workbook: Any) -> int:
    """把工作簿里以 ``=`` 开头的文本单元格标记为文本，返回处理的单元格数。

    只应在导出前调用（不要用于读取内部文件的代码路径）。
    """

    neutralized = 0
    for worksheet in workbook.worksheets:
        for row in worksheet.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, str) and value.startswith("="):
                    cell.data_type = "s"
                    neutralized += 1
    return neutralized
