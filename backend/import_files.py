#!/usr/bin/env python3
"""
导入三个Excel文件
"""
import asyncio
import sys
sys.path.insert(0, '/Users/xiami/Documents/项目/产品配置管理系统/backend')

import aiohttp
import aiofiles
from pathlib import Path

async def import_file(filepath, api_base="http://localhost:3006"):
    """导入单个文件"""
    import os

    filename = os.path.basename(filepath)
    print(f"\n导入: {filename}")
    print("-" * 80)

    # 使用requests（同步方式，因为FastAPI导入也是同步的）
    import requests

    url = f"{api_base}/api/import-export/import"

    with open(filepath, 'rb') as f:
        files = {'file': (filename, f, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
        data = {'clear_existing': 'true'}

        try:
            response = requests.post(url, files=files, data=data, timeout=300)
            if response.status_code == 200:
                result = response.json()
                print(f"  ✅ 成功: {result.get('message', 'OK')}")
                return True
            else:
                print(f"  ❌ 失败: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            return False

async def main():
    files = [
        "/Users/xiami/Downloads/Spec/Export_SpecExcel_20260529102338.xlsx",
        "/Users/xiami/Downloads/Spec/Export_SpecExcel_20260529102149.xlsx",
        "/Users/xiami/Downloads/Spec/Export_SpecExcel_20260529101436.xlsx"
    ]

    print("开始导入三个Excel文件")
    print("=" * 80)

    results = []
    for filepath in files:
        success = await import_file(filepath)
        results.append((filepath, success))

    print("\n" + "=" * 80)
    print("导入完成:")
    for filepath, success in results:
        status = "✅ 成功" if success else "❌ 失败"
        print(f"  {status}: {Path(filepath).name}")

if __name__ == "__main__":
    asyncio.run(main())
