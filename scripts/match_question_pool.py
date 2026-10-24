"""Run or resume the owner's whole-pool matching ledger, without a web server."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def main():
    os.environ.setdefault('STUDY_LOCAL_CODEX','1' if (ROOT/'.local-codex/provider.py').is_file() else '0')
    from backend.routine_review import get_store, model_config, reference_store, execute_run, ai_caller
    from backend.question_pool import storage_path
    parser=argparse.ArgumentParser(description='全量套路匹配；不修改正式题库或课程')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--new',action='store_true',help='冻结当前全部原题并启动新批次')
    mode.add_argument('--resume',metavar='RUN_ID',help='继续指定批次，跳过完成项')
    mode.add_argument('--retry-failed',metavar='RUN_ID',help='重试指定批次失败项并继续剩余题')
    mode.add_argument('--status',action='store_true',help='只查看最近批次')
    mode.add_argument('--report',action='store_true',help='导出最近批次的全部套路统计')
    mode.add_argument('--configure',metavar='RUN_ID',help='更新剩余题的模型设置，保持暂停')
    parser.add_argument('--engine',choices=('codex_luna','deepseek'),default='deepseek',help='匹配方式；Codex 仅支持安装本地接入的电脑')
    parser.add_argument('--concurrency',type=int,default=3,help='并发批次数，范围 1–16，默认 3')
    parser.add_argument('--legacy-run-id',help='可选的历史结果提示批次ID；仅内容哈希一致时使用')
    args=parser.parse_args()
    store=get_store()
    if args.configure:
        config=model_config(args.engine); ai_caller(config)
        run=store.configure(args.configure,config)
        print(json.dumps(summary(run),ensure_ascii=False),flush=True)
        return 0
    if args.status or args.report or not (args.new or args.resume or args.retry_failed):
        run=store.run()
        print(json.dumps(summary(run),ensure_ascii=False),flush=True)
        if args.report and run:
            print(str(store.write_report(run['run_id'])),flush=True)
        return 0
    if args.new:
        config=model_config(args.engine); ai_caller(config)
        catalog=reference_store().read()['catalog']
        if args.engine=='codex_luna':
            from backend.routine_classification import digest
            config.update(catalog_hash=digest(catalog),legacy_run_id=args.legacy_run_id,
                          preserve_prior_humans_as_history=True)
        run=store.create('cli-'+uuid.uuid4().hex,catalog,config,storage_path())
    else:
        current=store.run(args.resume or args.retry_failed)
        if current['model_config'].get('prompt_profile') is None:
            parser.error('请先用 --configure RUN_ID --engine codex_luna（或 deepseek）应用省费设置。')
        run=store.control(args.resume or args.retry_failed,'resume' if args.resume else 'retry_failed')
    print(json.dumps(summary(run),ensure_ascii=False),flush=True)
    last=[0]
    def progress(current):
        import time
        if time.monotonic()-last[0]>15:
            print(json.dumps(summary(current),ensure_ascii=False),flush=True)
            last[0]=time.monotonic()
    try:
        result=execute_run(store,run['run_id'],concurrency=max(1,min(16,args.concurrency)),progress=progress)
    except KeyboardInterrupt:
        store.control(run['run_id'],'pause')
        print('任务中断，结果已逐题保存；使用 --resume 继续。',flush=True)
        return 130
    print(json.dumps(summary(result),ensure_ascii=False),flush=True)
    return 0 if result['status']=='done' and not result['counts'].get('error') else 1


def summary(run):
    if not run: return {'run':None}
    return {k:run[k] for k in ('run_id','status','total','processed','counts','review_counts','kind_counts','needs_content','calls','reason','model_config','usage')}


if __name__=='__main__':
    raise SystemExit(main())
