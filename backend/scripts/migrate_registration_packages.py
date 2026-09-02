"""将既有注册证、差异表和导入批次绑定为首个受控资料包。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.registration_packages import (  # noqa: E402
    migrate_existing_registration_package,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=BACKEND_ROOT / "product_config.db")
    parser.add_argument("--certificate-document-id", type=int, required=True)
    parser.add_argument("--difference-document-id", type=int, required=True)
    parser.add_argument("--import-batch-id", type=int, required=True)
    parser.add_argument("--country-code", default="CN")
    parser.add_argument("--unit-code", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--product-series")
    parser.add_argument("--registration-number", required=True)
    parser.add_argument("--identity-source", default="registration_certificate")
    parser.add_argument("--confirmed-by", default="baseline_migration")
    parser.add_argument("--change-note", default="现有注册数据基线迁移")
    args = parser.parse_args()

    result = migrate_existing_registration_package(
        args.database,
        certificate_document_id=args.certificate_document_id,
        difference_document_id=args.difference_document_id,
        import_batch_id=args.import_batch_id,
        country_code=args.country_code,
        unit_code=args.unit_code,
        display_name=args.display_name,
        product_series=args.product_series,
        registration_number=args.registration_number,
        identity_source=args.identity_source,
        confirmed_by=args.confirmed_by,
        change_note=args.change_note,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
