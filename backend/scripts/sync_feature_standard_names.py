"""Preview or apply standard names to all explicit mappings, with a mandatory backup."""
import argparse
import asyncio
import json
from pathlib import Path
import sqlite3
import os
import tempfile
import sys
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app.models  # noqa: F401
from app.services.feature_standard_sync import build_standard_sync_plan, sync_all_standard_names
from app.utils.time import utcnow


def prepare_report(args):
    protected = [args.database, *(Path(str(args.database)+suffix) for suffix in ('-wal','-shm','-journal'))]
    if any(args.report.resolve() == source.resolve() or
           (args.report.exists() and source.exists() and os.path.samefile(args.report,source)) for source in protected):
        raise ValueError('报告不能覆盖数据库或其链接/日志文件')
    if args.report.suffix.lower() != '.json':
        raise ValueError('报告必须保存为独立的 .json 文件')
    if args.report.exists():
        with args.report.open('rb') as existing:
            if existing.read(16) == b'SQLite format 3\x00':
                raise ValueError('报告不能覆盖任何SQLite数据库或备份')
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=args.report.parent,prefix='.standard-name-report-',suffix='.json',delete=False) as handle:
        return Path(handle.name)


async def run(args):
    temporary = prepare_report(args)
    engine = create_async_engine('sqlite+aiosqlite:///' + str(args.database.resolve()))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            plan = await build_standard_sync_plan(db)
            temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
            if args.apply:
                args.backup_dir.mkdir(parents=True, exist_ok=True)
                backup = args.backup_dir / ('before-standard-name-sync-' + utcnow().strftime('%Y%m%dT%H%M%S%f') + '.db')
                with sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro',uri=True) as source, sqlite3.connect(backup) as target:
                    source.backup(target)
                    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('备份校验失败，未执行修改')
                await db.rollback()
                plan = {**await sync_all_standard_names(db), 'backup':str(backup)}
            temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
            temporary.replace(args.report)
            print(json.dumps({'checked':len(plan['checked']),'changed':sum(row['changed'] for row in plan['checked']),
                              'skipped':len(plan['skipped']),'applied':args.apply,'report':str(args.report)},ensure_ascii=False))
    finally:
        temporary.unlink(missing_ok=True)
        await engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--backup-dir',type=Path)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not args.database.is_file():parser.error('数据库文件不存在')
    if args.apply and args.backup_dir is None:parser.error('--apply requires --backup-dir')
    try:
        asyncio.run(run(args))
    except (ValueError, OSError) as error:
        parser.error(str(error))

if __name__=='__main__':main()
