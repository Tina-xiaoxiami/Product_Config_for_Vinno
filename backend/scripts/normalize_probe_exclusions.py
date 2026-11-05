"""Preview/apply only source-proved exclusion corrections, with an online backup."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.probe_exclusion_repair import repair_exclusions
from app.utils.time import utcnow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--backup-dir', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text())
    repair_exclusions(args.database, args.source, evidence)
    backup = None
    if args.apply:
        if args.backup_dir is None:
            parser.error('--apply requires --backup-dir')
        args.backup_dir.mkdir(parents=True, exist_ok=True)
        backup = args.backup_dir / ('before-exclusion-normalization-' + utcnow().strftime('%Y%m%dT%H%M%S%f') + '.db')
        with sqlite3.connect(args.database.resolve().as_uri() + '?mode=ro', uri=True) as source, sqlite3.connect(backup) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('备份完整性检查失败，未执行修复')
    result = repair_exclusions(args.database, args.source, evidence, apply=args.apply)
    result['backup'] = str(backup) if backup else None
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({key: result[key] for key in ['applied', 'counts', 'template_version_id', 'backup']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
