"""Owner-only full-pool classification and unlimited, durable human review.

The frozen pool and all decisions live outside the formal learning databases.
Workers call the existing pure matching engine, never the full solver or OCR.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import closing, contextmanager
from contextvars import copy_context
from pathlib import Path
import json
import os
import sqlite3
import threading
import time
import uuid
from urllib.error import HTTPError
from typing import Optional, List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StrictBool, StrictInt

from backend import routine_classification as rc
from backend.data_paths import data_path
from backend.routine_matching import MatchFailure, match_question, build_review_entry

ROOT = Path(__file__).resolve().parent.parent
_ACTIVE = set()
_ACTIVE_LOCK = threading.RLock()
REVIEW_STATES = {'pending', 'confirmed', 'deferred', 'rejected'}
KINDS = {'new_routine_candidate', 'insufficient_content', 'ambiguous_match', 'matching_incomplete'}


def require_owner():
    from backend.question_pool import _require_owner
    _require_owner()


def model_config(engine='deepseek'):
    if engine == 'codex_luna':
        from backend.local_models import routine_config
        return routine_config()
    from backend import settings
    api = settings.get_api().get('deepseek') or {}
    maximum = int(settings.get_limits().get('api_max_tokens', 8192))
    return {'model': settings.get_teacher_config('liangliang')['solver']['model'],
            'base_url': api.get('base_url') or 'https://api.deepseek.com/v1',
            'engine':'deepseek', 'temperature': .1, 'max_tokens':min(1024,maximum),
            'audit_max_tokens':min(2048,maximum), 'thinking':'disabled', 'json_output':True,
            'prompt_profile':rc.CACHE_PROMPT_VERSION, 'warm_prefix':True}


def get_store():
    require_owner()
    return ReviewStore(data_path('routine-review.sqlite3', ROOT / '.runtime/routine-review.sqlite3'))


def reference_store():
    from backend.routine_matching_api import get_store as reference
    return reference()


def ai_caller(config, usage_callback=None):
    if config.get('engine') == 'codex_luna':
        from backend.local_models import provider
        return provider().routine_caller(config,usage_callback)
    from backend import settings
    from backend.jobs import provider_slot, request_timeout
    key = settings.get_api_key('deepseek')
    if not key:
        raise HTTPException(503, '请先在系统设置中配置 AI Key。')
    timeout = min(120, int(settings.get_limits().get('api_timeout_seconds', 120)))
    def call(system, user, item):
        with provider_slot('deepseek'):
            return rc.make_http_caller(config, api_key=key, timeout=request_timeout(timeout), usage_callback=usage_callback)(system, user, item)
    return call


def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class ReviewStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''
          CREATE TABLE IF NOT EXISTS review_runs (
            run_id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, catalog_json TEXT NOT NULL,
            config_json TEXT NOT NULL, status TEXT NOT NULL, job_id TEXT, worker_pid INTEGER,
            stop INTEGER NOT NULL DEFAULT 0, reason TEXT DEFAULT '', revision INTEGER DEFAULT 0,
            calls INTEGER DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS review_items (
            run_id TEXT NOT NULL REFERENCES review_runs(run_id), item_id INTEGER NOT NULL,
            item_json TEXT NOT NULL, provenance_json TEXT NOT NULL, content_hash TEXT NOT NULL,
            cache_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', result_json TEXT,
            primary_id TEXT, secondary_json TEXT DEFAULT '[]', confidence TEXT DEFAULT '',
            kind TEXT DEFAULT '', needs_content INTEGER NOT NULL, review_status TEXT DEFAULT 'pending',
            marks_json TEXT DEFAULT '[]', note TEXT DEFAULT '', human_json TEXT, catalog_json TEXT,
            PRIMARY KEY(run_id,item_id));
          CREATE INDEX IF NOT EXISTS review_group ON review_items(run_id,primary_id,review_status,item_id);
          CREATE INDEX IF NOT EXISTS review_status ON review_items(run_id,status,kind,item_id);
          CREATE TABLE IF NOT EXISTS review_cache (
            cache_key TEXT PRIMARY KEY, result_json TEXT NOT NULL, status TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS review_humans (
            item_id INTEGER NOT NULL, content_hash TEXT NOT NULL, decision_json TEXT NOT NULL,
            PRIMARY KEY(item_id,content_hash));
          CREATE TABLE IF NOT EXISTS review_history (
            id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, item_id INTEGER NOT NULL,
            decision_json TEXT NOT NULL, created_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS review_usage (
            id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, item_id INTEGER NOT NULL,
            stage TEXT NOT NULL, usage_json TEXT NOT NULL, created_at REAL NOT NULL);
          CREATE INDEX IF NOT EXISTS review_usage_run ON review_usage(run_id,id);
          CREATE TABLE IF NOT EXISTS review_configs (
            id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, config_json TEXT NOT NULL, created_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS review_batch_responses (
            id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, item_ids_json TEXT NOT NULL,
            response_text TEXT, validation_errors_json TEXT NOT NULL, created_at REAL NOT NULL);
        ''')
        self.path.chmod(0o600)
        try:
            yield conn
        finally:
            conn.close()

    def create(self, request_id, catalog, config, pool_path):
        require_owner()
        rc.validate_catalog(catalog)
        run_id, now = uuid.uuid4().hex, time.time()
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old = conn.execute('SELECT run_id FROM review_runs WHERE request_id=?', (request_id,)).fetchone()
            if old:
                conn.rollback()
                return self.run(old['run_id'])
            if conn.execute("SELECT 1 FROM review_runs WHERE status!='archived' LIMIT 1").fetchone():
                raise HTTPException(409, '已有全量匹配任务，请暂停或继续原进度；不能重新匹配全部原题。')
            active = conn.execute("SELECT run_id,worker_pid,updated_at FROM review_runs WHERE status IN ('running','queued')").fetchall()
            for row in active:
                if _alive(row['worker_pid']) and now - row['updated_at'] < 300:
                    raise HTTPException(409, '已有全量任务在运行，请查看或暂停该批次。')
                conn.execute("UPDATE review_runs SET status='interrupted',stop=1,reason='进程已中断，可继续匹配' WHERE run_id=?", (row['run_id'],))
            with closing(sqlite3.connect(Path(pool_path).resolve().as_uri() + '?mode=ro', uri=True)) as source:
                source.row_factory = sqlite3.Row
                source.execute('BEGIN')
                conn.execute('INSERT INTO review_runs(run_id,request_id,catalog_json,config_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                             (run_id, request_id, rc_json(catalog), rc_json(config), 'ready', now, now))
                provenance = {}
                for origin in source.execute('SELECT o.*,s.name,s.url,s.filename,s.file_token FROM pool_occurrences o JOIN pool_sources s ON s.id=o.source_id ORDER BY o.id'):
                    raw = json.loads(origin['raw_json'] or '{}')
                    record = {k: origin[k] for k in ('source_id','source_key','page_start','page_end','question_no','name','url','filename')}
                    record['has_file'] = bool(origin['file_token'])
                    record['raw'] = {k: raw[k] for k in ('image_refs','image_assets','original_file','source_root','question_assets','graphic_file','file_sha256','paper') if k in raw}
                    provenance.setdefault(origin['item_id'], []).append(record)
                catalog_hash = rc.digest(catalog)
                for row in source.execute('SELECT * FROM pool_items ORDER BY id'):
                    item = {k: row[k] for k in ('id','version','question','solution','answer','completeness')}
                    item['categories'] = json.loads(row['categories_json'])
                    content_hash = rc.digest(item)
                    key = rc.cache_key(item, catalog, config, catalog_hash)
                    cached = conn.execute('SELECT * FROM review_cache WHERE cache_key=?', (key,)).fetchone()
                    human = conn.execute('SELECT decision_json FROM review_humans WHERE item_id=? AND content_hash=?', (item['id'],content_hash)).fetchone()
                    result = json.loads(cached['result_json']) if cached else {}
                    classification = result.get('classification', {})
                    decision = json.loads(human[0]) if human else None
                    if decision and decision['review_status']!='pending':
                        classification.update(primary_routine_id=decision['primary_routine_id'],secondary_routine_ids=decision['secondary_routine_ids'])
                        result['classification'] = classification
                    conn.execute('''INSERT INTO review_items(run_id,item_id,item_json,provenance_json,content_hash,cache_key,status,result_json,
                      primary_id,secondary_json,confidence,kind,needs_content,review_status,marks_json,note,human_json)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (run_id,item['id'],rc_json(item),rc_json(provenance.get(item['id'],[])),content_hash,key,
                       'classified' if human and decision['review_status']!='pending' else cached['status'] if cached else 'pending',rc_json(result) if result else None,
                       classification.get('primary_routine_id'),rc_json(classification.get('secondary_routine_ids',[])),classification.get('confidence',''),
                       result.get('review',{}).get('kind','') if result.get('review') else '',
                       int(not item['solution'].strip() or item['completeness']!='complete'),
                       decision['review_status'] if decision else 'pending',rc_json(decision['marks']) if decision else '[]',
                       decision['note'] if decision else '',rc_json(decision) if decision else None))
                source.rollback()
            conn.commit()
        return self.run(run_id)

    def run(self, run_id=None):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM review_runs WHERE run_id=? AND status!='archived'" if run_id else "SELECT * FROM review_runs WHERE status!='archived' ORDER BY created_at ASC LIMIT 1", (run_id,) if run_id else ()).fetchone()
            if row is None:
                if run_id:
                    raise HTTPException(404, '批次不存在。')
                return None
            run = dict(row)
            if run['status'] in ('running','queued') and (not _alive(run['worker_pid']) or time.time()-run['updated_at']>300):
                conn.execute("UPDATE review_runs SET status='interrupted',stop=1,reason='进程已中断，可继续匹配' WHERE run_id=?", (run['run_id'],))
                conn.commit()
                run.update(status='interrupted',stop=1,reason='进程已中断，可继续匹配')
            run['catalog'] = json.loads(run.pop('catalog_json'))
            run['model_config'] = json.loads(run.pop('config_json'))
            run['total'] = conn.execute('SELECT count(*) FROM review_items WHERE run_id=?', (run['run_id'],)).fetchone()[0]
            for key,column in [('counts','status'),('review_counts','review_status'),('kind_counts','kind')]:
                run[key] = {r[0]:r[1] for r in conn.execute(f'SELECT {column},count(*) FROM review_items WHERE run_id=? GROUP BY {column}', (run['run_id'],))}
            run['needs_content'] = conn.execute('SELECT count(*) FROM review_items WHERE run_id=? AND needs_content=1',(run['run_id'],)).fetchone()[0]
            run['processed'] = sum(run['counts'].get(k,0) for k in ('classified','error'))
            metrics = ('prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens','reasoning_tokens')
            expressions=['COUNT(*) AS requests']
            for key in metrics:
                expressions += [f"SUM(json_extract(usage_json,'$.{key}')) AS {key}",f"COUNT(json_extract(usage_json,'$.{key}')) AS observed_{key}"]
            values=conn.execute('SELECT '+','.join(expressions)+' FROM review_usage WHERE run_id=?',(run['run_id'],)).fetchone()
            run['usage']={key:values[key] for key in ('requests',*metrics)}
            run['usage']['observed']={key:values['observed_'+key] for key in metrics}
            hit,miss = run['usage']['prompt_cache_hit_tokens'],run['usage']['prompt_cache_miss_tokens']
            run['usage']['cache_hit_ratio'] = hit/(hit+miss) if hit is not None and miss is not None and hit+miss else None
            run['catalog_hash'] = rc.digest(run['catalog'])
            run.pop('request_id',None)
            return run

    def control(self, run_id, action):
        with self.connection() as conn, conn:
            row = conn.execute('SELECT * FROM review_runs WHERE run_id=?',(run_id,)).fetchone()
            if not row:
                raise HTTPException(404,'批次不存在。')
            if action == 'pause':
                conn.execute("UPDATE review_runs SET stop=1,status=CASE WHEN status IN ('ready','queued') THEN 'paused' ELSE status END,reason='正在暂停，已发出请求将保存后停止' WHERE run_id=?",(run_id,))
            elif action in ('resume','retry_failed','rematch'):
                if row['status'] in ('running','queued') and _alive(row['worker_pid']):
                    raise HTTPException(409,'请先等待当前任务暂停或结束。')
                if action == 'retry_failed':
                    conn.execute("UPDATE review_items SET status=CASE WHEN json_extract(result_json,'$.audit_pending')=1 THEN 'matching' ELSE 'pending' END WHERE run_id=? AND status='error' AND (human_json IS NULL OR json_extract(human_json,'$.review_status')='pending')",(run_id,))
                conn.execute("UPDATE review_runs SET stop=0,status='ready',reason='',updated_at=? WHERE run_id=?",(time.time(),run_id))
        return self.run(run_id)

    def configure(self, run_id, config):
        """Change only unfinished work. Completed results keep their old cache identity."""
        require_owner()
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM review_runs WHERE run_id=?',(run_id,)).fetchone()
            if row is None: raise HTTPException(404,'批次不存在。')
            if row['status'] in ('running','queued') and _alive(row['worker_pid']):
                raise HTTPException(409,'请先暂停当前批次，再切换匹配方式。')
            catalog=json.loads(row['catalog_json'])
            conn.execute('INSERT INTO review_configs(run_id,config_json,created_at) VALUES (?,?,?)',(run_id,row['config_json'],time.time()))
            for saved in conn.execute("SELECT item_id,result_json FROM review_items WHERE run_id=? AND status='classified'",(run_id,)).fetchall():
                result=json.loads(saved['result_json'] or '{}')
                if result.get('classification',{}).get('method_summary') and 'model_config_snapshot' not in result:
                    result['model_config_snapshot']=json.loads(row['config_json'])
                    conn.execute('UPDATE review_items SET result_json=? WHERE run_id=? AND item_id=?',(rc_json(result),run_id,saved['item_id']))
            for item in conn.execute("SELECT item_id,item_json,catalog_json FROM review_items WHERE run_id=? AND status!='classified'",(run_id,)).fetchall():
                effective=json.loads(item['catalog_json']) if item['catalog_json'] else catalog
                key=rc.cache_key(json.loads(item['item_json']),effective,config)
                conn.execute('UPDATE review_items SET cache_key=? WHERE run_id=? AND item_id=?',(key,run_id,item['item_id']))
            conn.execute("UPDATE review_runs SET config_json=?,status='paused',stop=1,reason='匹配方式已更新，已有结果保留；继续后仅处理剩余题。',updated_at=? WHERE run_id=?",(rc_json(config),time.time(),run_id))
            conn.commit()
        return self.run(run_id)

    def record_usage(self, run_id, item, stage, usage):
        with self.connection() as conn,conn:
            conn.execute('INSERT INTO review_usage(run_id,item_id,stage,usage_json,created_at) VALUES (?,?,?,?,?)',
                         (run_id,item['id'],stage,rc_json(usage),time.time()))

    def record_request(self, run_id):
        with self.connection() as conn,conn:
            conn.execute('UPDATE review_runs SET calls=calls+1,updated_at=? WHERE run_id=?',(time.time(),run_id))

    def record_batch_response(self, run_id, item_ids, raw, errors):
        with self.connection() as conn,conn:
            conn.execute('INSERT INTO review_batch_responses(run_id,item_ids_json,response_text,validation_errors_json,created_at) VALUES (?,?,?,?,?)',
                         (run_id,rc_json(item_ids),raw if isinstance(raw,str) else rc_json(raw) if raw is not None else None,rc_json(errors),time.time()))

    def set_state(self, run_id, status, reason='', job_id=None):
        with self.connection() as conn, conn:
            conn.execute('UPDATE review_runs SET status=?,reason=?,worker_pid=?,job_id=COALESCE(?,job_id),updated_at=? WHERE run_id=?',
                         (status,reason,os.getpid(),job_id,time.time(),run_id))

    def stopping(self, run_id):
        with self.connection() as conn:
            return bool(conn.execute('SELECT stop FROM review_runs WHERE run_id=?',(run_id,)).fetchone()[0])

    def save_result(self, run_id, item_id, result, status, calls=0):
        classification = result.get('classification',{})
        review = result.get('review') or {}
        with self.connection() as conn, conn:
            row = conn.execute('SELECT cache_key,human_json FROM review_items WHERE run_id=? AND item_id=?',(run_id,item_id)).fetchone()
            conn.execute('INSERT OR REPLACE INTO review_cache VALUES (?,?,?)',(row['cache_key'],rc_json(result),status))
            # A human may review while this exact request is in flight.
            human=json.loads(row['human_json'] or 'null')
            if not human or human['review_status']=='pending':
                conn.execute('UPDATE review_items SET status=?,result_json=?,primary_id=?,secondary_json=?,confidence=?,kind=? WHERE run_id=? AND item_id=?',
                             (status,rc_json(result),classification.get('primary_routine_id'),rc_json(classification.get('secondary_routine_ids',[])),classification.get('confidence',''),review.get('kind',''),run_id,item_id))
            else:
                conn.execute('UPDATE review_items SET status=?,result_json=? WHERE run_id=? AND item_id=?',(status,rc_json(result),run_id,item_id))
            conn.execute('UPDATE review_runs SET calls=calls+?,updated_at=? WHERE run_id=?',(calls,time.time(),run_id))

    def rows(self, run_id, filters=None, page=1, page_size=50):
        where, params = filter_sql(run_id,filters or {})
        with self.connection() as conn:
            total = conn.execute('SELECT count(*) FROM review_items'+where,params).fetchone()[0]
            rows = conn.execute('SELECT * FROM review_items'+where+' ORDER BY item_id LIMIT ? OFFSET ?',params+[page_size,(page-1)*page_size]).fetchall()
            return {'data':[self.public(row,False) for row in rows],'total':total,'page':page,'page_size':page_size}

    def public(self, row, full=True):
        data = dict(row)
        item = json.loads(data.pop('item_json'))
        data['item'] = item
        data['result'] = json.loads(data.pop('result_json') or '{}')
        data['secondary_ids'] = json.loads(data.pop('secondary_json'))
        data['marks'] = json.loads(data.pop('marks_json'))
        data['human'] = json.loads(data.pop('human_json') or 'null')
        provenance = json.loads(data.pop('provenance_json'))
        if full:
            data['occurrences'] = provenance
            data['assets'] = [{'index':i,'name':p.name,'image':p.suffix.lower() in ('.png','.jpg','.jpeg','.gif','.webp')} for i,p in enumerate(asset_paths(provenance))]
        else:
            data['item'] = {k:v for k,v in item.items() if k not in ('solution','answer')}
            data['result'] = {'error':data['result'].get('error')}
        # Source version changes require a new snapshot, never silently mutate it.
        data['source_stale'] = False
        return data

    def item(self, run_id, item_id):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM review_items WHERE run_id=? AND item_id=?',(run_id,item_id)).fetchone()
            if not row:
                raise HTTPException(404,'题目不在此批次中。')
            data = self.public(row)
        from backend.question_pool import storage_path
        with closing(sqlite3.connect(Path(storage_path()).resolve().as_uri()+'?mode=ro',uri=True)) as conn:
            current = conn.execute('SELECT version FROM pool_items WHERE id=?',(item_id,)).fetchone()
        data['source_stale'] = current is None or current[0] != data['item']['version']
        # Supplement saved classifications with the pool's current attachments.
        # The frozen question, AI conclusion and human decisions stay intact.
        from backend.question_pool import get_item
        from backend.question_assets import pool_asset_data
        if current is not None:
            data['source_assets'] = pool_asset_data(get_item(item_id))
        return data

    def groups(self, run_id):
        run = self.run(run_id)
        # Human-created catalogue entries can be used without rebilling the batch.
        current = reference_store().read()['catalog']
        catalog = {r['id']:r for r in run['catalog']['routines']}
        catalog.update({r['id']:r for r in current['routines']})
        with self.connection() as conn:
            counts = {r[0]:r for r in conn.execute("SELECT primary_id,count(*),sum(review_status='confirmed'),sum(needs_content) FROM review_items WHERE run_id=? GROUP BY primary_id",(run_id,))}
        return {'catalog':current,'groups':[{**r,'total':counts[rid][1] if rid in counts else 0,'confirmed':counts[rid][2] if rid in counts else 0,'needs_content':counts[rid][3] if rid in counts else 0} for rid,r in catalog.items()],
                'unmatched':counts[None][1] if None in counts else 0,'revision':run['revision']}

    def write_report(self, run_id):
        """Small statistics export; detailed question results stay in SQLite."""
        run = self.run(run_id)
        groups = self.groups(run_id)
        states = {'ready':'等待匹配','queued':'排队中','running':'匹配中','paused':'已暂停','interrupted':'已中断','done':'处理完成'}
        lines = ['# 全量套路匹配统计', '',
                 f"批次：{run['run_id']} · 状态：{states.get(run['status'],run['status'])}", '',
                 f"当前模型：{run['model_config']['model']} · 提示词：{run['model_config'].get('prompt_profile','旧版')}", '',
                 '这是当前保存进度；只有已处理数等于快照总数时，才代表全部题目已处理。', '',
                 '| 项目 | 数量 |', '|---|---:|',
                 f"| 快照总题数 | {run['total']} |", f"| 已处理 | {run['processed']} |",
                 f"| 已有匹配结果 | {run['counts'].get('classified',0)} |",
                 f"| 等待匹配或复查 | {run['total']-run['processed']} |",
                 f"| 待补资料（全快照） | {run['needs_content']} |",
                 f"| 新套路候选 | {run['kind_counts'].get('new_routine_candidate',0)} |",
                 f"| 归属待确认 | {run['kind_counts'].get('ambiguous_match',0)} |",
                 f"| 请求失败 | {run['counts'].get('error',0)} |",
                 f"| 人工确认 | {run['review_counts'].get('confirmed',0)} |",
                 f"| 暂未归组（含等待匹配） | {groups['unmatched']} |", '',
                 '## 模型用量', '', f"请求尝试：{run['calls']}；有用量明细的响应：{run['usage']['requests']}。旧请求无法回补明细。", '',
                 '| 用量 | 已记录 tokens |', '|---|---:|']
        for key,label in [('prompt_tokens','输入'),('prompt_cache_hit_tokens','输入缓存命中'),('prompt_cache_miss_tokens','输入未命中'),('completion_tokens','输出（含思考）'),('reasoning_tokens','输出中的思考')]:
            value=run['usage'][key]
            lines.append(f"| {label} | {value if value is not None else '未返回明细'} |")
        lines.extend(['', '## 各套路题数', '', '| 编号 | 板块 | 套路 | 题数 | 已确认 | 待补资料 |', '|---|---|---|---:|---:|---:|'])
        def cell(value):
            return str(value).replace('\n',' ').replace('|','\\|')
        for group in groups['groups']:
            lines.append('| '+' | '.join(cell(group[k]) for k in ('id','category','name','total','confirmed','needs_content'))+' |')
        path = self.path.parent / ('routine-review-'+run['run_id']+'-report.md')
        temporary = path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        temporary.chmod(0o600)
        temporary.replace(path)
        return path

    def decide(self, run_id, request):
        require_owner()
        run = self.run(run_id)
        catalog = reference_store().read()['catalog']
        valid = {r['id'] for r in catalog['routines']} | {r['id'] for r in run['catalog']['routines']}
        if request.action == 'assign' and not request.primary_id:
            raise HTTPException(422,'改组需要指定主套路。')
        if request.primary_id and request.primary_id not in valid:
            raise HTTPException(422,'主套路编号无效。')
        if len(set(request.secondary_ids))!=len(request.secondary_ids) or not set(request.secondary_ids)<=valid or request.primary_id in request.secondary_ids:
            raise HTTPException(422,'辅助套路编号无效或重复。')
        where, params = filter_sql(run_id,request.filters if request.all_filtered else {})
        if not request.all_filtered:
            if not request.item_ids:
                raise HTTPException(422,'请选择题目。')
            where += ' AND item_id IN ('+','.join('?' for _ in request.item_ids)+')'
            params += request.item_ids
        from backend.question_pool import storage_path
        with closing(sqlite3.connect(Path(storage_path()).resolve().as_uri()+'?mode=ro',uri=True)) as source:
            versions = dict(source.execute('SELECT id,version FROM pool_items'))
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            revision = conn.execute('SELECT revision FROM review_runs WHERE run_id=?',(run_id,)).fetchone()[0]
            if revision != request.expected_revision:
                raise HTTPException(409,'审核结果已变更，请刷新后重新提交。')
            rows = conn.execute('SELECT * FROM review_items'+where,params).fetchall()
            if request.all_filtered and request.expected_count is not None and len(rows)!=request.expected_count:
                raise HTTPException(409,'筛选结果数量已变化，请刷新后重新审核。')
            if not request.all_filtered and len(rows)!=len(set(request.item_ids)):
                raise HTTPException(404,'部分题目不在此批次中。')
            decisions=[]
            for row in rows:
                item=json.loads(row['item_json'])
                if versions.get(item['id'])!=item['version']:
                    raise HTTPException(409,f'原题 {item["id"]} 已改变，请建立新快照后审核。')
                primary = request.primary_id if request.action=='assign' else row['primary_id']
                if request.action=='confirm' and not primary:
                    raise HTTPException(422,f'原题 {item["id"]} 尚无归属，请先指定套路。')
                decision={'primary_routine_id':primary,'secondary_routine_ids':request.secondary_ids if request.action=='assign' else json.loads(row['secondary_json']),
                          'review_status':{'confirm':'confirmed','assign':'confirmed','defer':'deferred','reject':'rejected','mark':row['review_status']}[request.action],
                          'marks':request.marks if request.marks is not None else json.loads(row['marks_json']),
                          'note':request.note if request.note is not None else row['note'],'item_version':item['version'],'content_hash':row['content_hash']}
                decisions.append((row,decision))
            for row,decision in decisions:
                encoded=rc_json(decision)
                conn.execute('UPDATE review_items SET primary_id=?,secondary_json=?,review_status=?,marks_json=?,note=?,human_json=? WHERE run_id=? AND item_id=?',
                             (decision['primary_routine_id'],rc_json(decision['secondary_routine_ids']),decision['review_status'],rc_json(decision['marks']),decision['note'],encoded,run_id,row['item_id']))
                conn.execute('INSERT OR REPLACE INTO review_humans VALUES (?,?,?)',(row['item_id'],row['content_hash'],encoded))
                conn.execute('INSERT INTO review_history(run_id,item_id,decision_json,created_at) VALUES (?,?,?,?)',(run_id,row['item_id'],encoded,time.time()))
            conn.execute('UPDATE review_runs SET revision=revision+1 WHERE run_id=?',(run_id,))
            conn.commit()
        return {'updated':len(decisions),'revision':revision+1,'advisory_only':True}


def rc_json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def filter_sql(run_id, filters):
    allowed={'routine_id','category','keyword','confidence','completeness','review_status','status','kind','needs_content'}
    if set(filters)-allowed:
        raise HTTPException(422,'不支持的筛选字段。')
    clauses=['run_id=?']; params=[run_id]
    for key,column in [('routine_id','primary_id'),('confidence','confidence'),('review_status','review_status'),('status','status'),('kind','kind')]:
        value=filters.get(key)
        if not value:
            continue
        if key=='routine_id' and value=='unmatched':
            clauses.append('primary_id IS NULL')
        else:
            clauses.append(column+'=?'); params.append(value)
    if filters.get('category'):
        clauses.append("EXISTS(SELECT 1 FROM json_each(json_extract(item_json,'$.categories')) WHERE value=?)")
        params.append(filters['category'])
    if filters.get('completeness'):
        clauses.append("json_extract(item_json,'$.completeness')=?"); params.append(filters['completeness'])
    if filters.get('needs_content') in (True,'1',1):
        clauses.append('needs_content=1')
    if filters.get('keyword'):
        clauses.append("(json_extract(item_json,'$.question') LIKE ? ESCAPE '\\' OR note LIKE ? ESCAPE '\\')")
        term='%'+str(filters['keyword']).replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        params.extend([term,term])
    return ' WHERE '+' AND '.join(clauses),params


def asset_paths(provenance):
    paths=[]
    from backend.question_pool import files_directory, source_asset_path
    allowed=[files_directory().parent.resolve(),(ROOT/'.runtime/question-pool').resolve()]
    for origin in provenance:
        raw=origin.get('raw') or {}
        original=source_asset_path(raw['original_file']) if raw.get('original_file') else None
        candidates=[]
        if original and original.suffix.lower() in ('.pdf','.docx','.txt','.tex','.png','.jpg','.jpeg'):
            candidates.append(original)
        if original:
            snapshot=next((p for p in original.parents if p.parent.name=='snapshots'),None)
            if snapshot:
                candidates.extend(snapshot/a['path'] for a in raw.get('image_assets',[]) if isinstance(a,dict) and a.get('path'))
        base=source_asset_path(raw['source_root']) if raw.get('source_root') else None
        if base:
            candidates.extend(base/a['path'] for a in raw.get('image_refs',[]) if isinstance(a,dict) and isinstance(a.get('path'),str))
        for candidate in candidates:
            path=candidate.resolve()
            if path.is_file() and any(path.is_relative_to(root) for root in allowed) and path not in paths:
                paths.append(path)
    return paths


def execute_run(store, run_id, caller=None, concurrency=8, progress=None, job_id=None, only_item_id=None):
    require_owner()
    from backend.jobs import ensure_active, JobStopped
    run=store.run(run_id)
    from backend.local_models import validate_routine_config
    validate_routine_config(run['model_config'])
    lock_key=(str(store.path.resolve()),run_id)
    with _ACTIVE_LOCK:
        if lock_key in _ACTIVE:
            raise HTTPException(409,'此批次已在运行。')
        _ACTIVE.add(lock_key)
    fatal=threading.Event(); fatal_reason=[]
    try:
        with store.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT status,worker_pid FROM review_runs WHERE run_id=?',(run_id,)).fetchone()
            if row['status']=='running' and _alive(row['worker_pid']):
                raise HTTPException(409,'此批次已在其他进程运行。')
            if store.stopping(run_id):
                return run
            conn.execute("UPDATE review_runs SET status='running',worker_pid=?,job_id=COALESCE(?,job_id),updated_at=? WHERE run_id=?",(os.getpid(),job_id,time.time(),run_id))
            conn.commit()
            query="SELECT * FROM review_items WHERE run_id=? AND status IN ('pending','matching') AND (human_json IS NULL OR json_extract(human_json,'$.review_status')='pending')"
            params=[run_id]
            if only_item_id is not None:
                query+=' AND item_id=?'; params.append(only_item_id)
            rows=conn.execute(query+' ORDER BY item_id',params).fetchall()
        if rows and caller is None:
            caller=ai_caller(run['model_config'],lambda item,stage,usage:store.record_usage(run_id,item,stage,usage))
        def classify(row):
            if fatal.is_set() or store.stopping(run_id):
                return
            ensure_active()
            item=json.loads(row['item_json']); initial=json.loads(row['result_json'] or '{}')
            catalog=json.loads(row['catalog_json']) if row['catalog_json'] else run['catalog']
            calls=0
            def counted(system,user,item):
                nonlocal calls
                ensure_active()
                if fatal.is_set() or store.stopping(run_id):
                    raise JobStopped('匹配已暂停')
                calls+=1
                try:
                    return caller(system,user,item)
                except Exception as exc:
                    if getattr(exc,'status_code',getattr(exc,'code',None)) in (400,401,402,403,404,429,503):
                        fatal.set(); fatal_reason.append('模型认证、额度、余额或配置异常，请处理后继续；不会自动切换付费模型。')
                    raise
            def checkpoint(partial):
                store.save_result(run_id,item['id'],partial,'matching')
            try:
                matched=match_question(item,catalog,counted,attempts=2,
                                       initial=initial if initial.get('audit_pending') else None,checkpoint=checkpoint,
                                       cache_friendly=run['model_config'].get('prompt_profile')==rc.CACHE_PROMPT_VERSION)
                matched['model_config_snapshot']=run['model_config']
                matched['review']=build_review_entry({'status':'classified','item':item,**matched},catalog)
                store.save_result(run_id,item['id'],matched,'classified',calls)
            except MatchFailure as exc:
                if isinstance(exc.cause,JobStopped):
                    store.save_result(run_id,item['id'],exc.partial,'matching' if exc.partial.get('audit_pending') else 'pending',calls)
                else:
                    result={**exc.partial,'error':rc._safe_failure(exc.cause)}
                    result['review']=build_review_entry({'status':'error','item':item,**result},catalog)
                    store.save_result(run_id,item['id'],result,'error',calls)
            except ValueError:
                # Invalid source records remain visible and must not stop the pool.
                store.save_result(run_id,item['id'],{
                    'error':'原题格式不完整，请补齐题干或板块资料后重试。',
                    'review':{'kind':'insufficient_content','reasons':['原题格式不完整，暂时无法匹配。']},
                },'error',calls)
        def classify_batch(batch):
            from backend.local_models import provider
            return provider().classify_batch(batch,store=store,run=run,caller=caller,fatal=fatal,fatal_reason=fatal_reason)
        workers=max(1,min(8,concurrency))
        batch_mode=run['model_config'].get('engine')=='codex_luna'
        if batch_mode:
            from backend.local_models import provider
            work=provider().matching_batches(rows,run['model_config'])
        else: work=rows
        iterator=iter(work); pending=set(); last_update=0; last_report=0
        warm_completed=0
        with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='routine-review') as executor:
            while True:
                ensure_active()
                stopping=fatal.is_set() or store.stopping(run_id)
                # Warm with two useful items, never an extra paid preload request.
                slots=1 if run['model_config'].get('warm_prefix') and warm_completed<2 else workers
                while not stopping and len(pending)<slots:
                    row=next(iterator,None)
                    if row is None: break
                    context=copy_context()
                    pending.add(executor.submit(context.run,classify_batch if batch_mode else classify,row))
                if not pending: break
                done,pending=wait(pending,timeout=1,return_when=FIRST_COMPLETED)
                for future in done: future.result()
                warm_completed+=len(done)
                if time.monotonic()-last_update>=2:
                    with store.connection() as conn,conn:
                        conn.execute('UPDATE review_runs SET updated_at=? WHERE run_id=?',(time.time(),run_id))
                    if progress: progress(store.run(run_id))
                    last_update=time.monotonic()
                if time.monotonic()-last_report>=30:
                    store.write_report(run_id)
                    last_report=time.monotonic()
        if fatal.is_set() or store.stopping(run_id):
            store.set_state(run_id,'paused',fatal_reason[0] if fatal_reason else '已暂停，可从已保存进度继续')
        else:
            state=store.run(run_id)
            store.set_state(run_id,'paused' if only_item_id is not None and state['processed']<state['total'] else 'done',
                            '单题重匹配完成，可继续全量任务' if only_item_id is not None and state['processed']<state['total'] else '')
        store.write_report(run_id)
        return store.run(run_id)
    except BaseException:
        store.set_state(run_id,'interrupted','任务中断；已保存结果，可继续匹配。')
        raise
    finally:
        with _ACTIVE_LOCK: _ACTIVE.discard(lock_key)


def validate_job_args(args):
    require_owner()
    if set(args)-{'run_id','item_id'} or not isinstance(args.get('run_id'),str):
        raise ValueError('匹配任务只接受批次编号。')
    get_store().run(args['run_id'])
    if 'item_id' in args:
        if type(args['item_id']) is not int or args['item_id']<1: raise ValueError('题目编号无效。')
        get_store().item(args['run_id'],args['item_id'])
    return {k:v for k,v in args.items() if k in ('run_id','item_id')}


def run_job(args,ctx):
    store=get_store()
    def progress(run):
        ctx.progress('routine_match',round(100*run['processed']/max(1,run['total'])),
                     f"已处理 {run['processed']}/{run['total']} · 失败 {run['counts'].get('error',0)} · 已审核 {run['review_counts'].get('confirmed',0)}")
    run=execute_run(store,args['run_id'],progress=progress,job_id=ctx.job_id,only_item_id=args.get('item_id'))
    return {'run_id':run['run_id'],'total':run['total'],'counts':run['counts'],'status':run['status'],'review_url':'/routine-review.html?run='+run['run_id']}


def enqueue_run(store, run_id, request_id, item_id=None):
    from backend.jobs import submit_job
    args={'run_id':run_id}
    if item_id is not None: args['item_id']=item_id
    job=submit_job('routine_match',args,request_id)
    with store.connection() as conn,conn:
        conn.execute("UPDATE review_runs SET job_id=?,worker_pid=?,status=CASE WHEN status='ready' THEN 'queued' ELSE status END,updated_at=? WHERE run_id=?",(job['job_id'],os.getpid(),time.time(),run_id))
    return {'run_id':run_id,'job':job,'review_url':'/routine-review.html?run='+run_id}


class StrictRequest(BaseModel):
    class Config: extra='forbid'


class StartRequest(StrictRequest):
    request_id: str=Field(...,min_length=8,max_length=128)
    engine: Literal['deepseek','codex_luna']='deepseek'


class ControlRequest(StartRequest):
    action: str


class DecisionRequest(StrictRequest):
    action: str
    item_ids: List[StrictInt]=Field(default_factory=list,max_items=50000)
    all_filtered: StrictBool=False
    filters: dict=Field(default_factory=dict)
    expected_revision: StrictInt
    expected_count: Optional[StrictInt]=None
    primary_id: Optional[str]=None
    secondary_ids: List[str]=Field(default_factory=list,max_items=3)
    marks: Optional[List[str]]=Field(None,max_items=2)
    note: Optional[str]=Field(None,max_length=5000)


class CreateRequest(StrictRequest):
    expected_revision: StrictInt
    decision: dict


class WebPacketRequest(StrictRequest):
    limit: StrictInt = Field(5, ge=1, le=20)


class WebResponseRequest(StrictRequest):
    response: str = Field(..., min_length=2, max_length=200000)


router=APIRouter(prefix='/routine-review',tags=['套路审核'],dependencies=[Depends(require_owner)])
page_router=APIRouter(dependencies=[Depends(require_owner)])


@page_router.get('/routine-review.html',include_in_schema=False)
def review_page():
    return FileResponse(ROOT/'frontend/routine-review.html')


@router.get('/runs/latest')
def latest(store=Depends(get_store)):
    return {'run':store.run()}


@router.post('/runs',status_code=202)
def start(req:StartRequest,store=Depends(get_store)):
    from backend.question_pool import storage_path
    current=store.run()
    if current:
        with store.connection() as conn:
            request_id=conn.execute('SELECT request_id FROM review_runs WHERE run_id=?',(current['run_id'],)).fetchone()[0]
        if request_id==req.request_id:
            return {'run_id':current['run_id'],'run':current}
        raise HTTPException(409,'已有全量匹配任务，请暂停或继续原进度；不能重新匹配全部原题。')
    config=model_config(req.engine)
    ai_caller(config)  # Check configuration before freezing a new snapshot.
    run=store.create(req.request_id,reference_store().read()['catalog'],config,storage_path())
    if run['status'] not in ('ready','queued','running'):
        return {'run_id':run['run_id'],'run':run}
    return enqueue_run(store,run['run_id'],req.request_id)


@router.get('/runs/{run_id}')
def status(run_id:str,store=Depends(get_store)):
    return store.run(run_id)


@router.post('/runs/{run_id}/web-packet')
def web_packet(run_id:str, req:WebPacketRequest, store=Depends(get_store)):
    from backend.routine_web_review import export_packet
    try:
        packet=export_packet(store,run_id,req.limit)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from None
    return {'packet_id':packet['packet_id'],'prompt':packet['prompt'],
            'item_ids':[item['id'] for item in packet['metadata']['items']],
            'reused':packet['reused']}


@router.post('/web-packets/{packet_id}/response')
def web_response(packet_id:str, req:WebResponseRequest, store=Depends(get_store)):
    from backend.routine_web_review import import_packet, archive_response
    try:
        archive_response(store,packet_id,req.response)
        result=import_packet(store,packet_id,req.response)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from None
    return result


@router.post('/runs/{run_id}/control',status_code=202)
def control(run_id:str,req:ControlRequest,store=Depends(get_store)):
    store.run(run_id)  # Inactive legacy tasks cannot be resumed through old links.
    if req.action in ('optimize','use_luna'):
        config=model_config('codex_luna' if req.action=='use_luna' else 'deepseek')
        ai_caller(config)
        return {'run':store.configure(run_id,config)}
    if req.action not in ('pause','resume','retry_failed'):
        raise HTTPException(422,'控制动作无效。')
    if req.action!='pause' and store.run(run_id)['model_config'].get('prompt_profile')!=rc.CACHE_PROMPT_VERSION:
        raise HTTPException(409,'请先应用省费设置或切换 Codex Luna，再继续旧批次。')
    config=store.run(run_id)['model_config']
    if req.action!='pause':
        from backend.local_models import validate_routine_config
        validate_routine_config(config)
    run=store.control(run_id,req.action)
    if req.action=='pause': return {'run':run}
    return enqueue_run(store,run_id,req.request_id)


@router.get('/runs/{run_id}/groups')
def groups(run_id:str,store=Depends(get_store)):
    return store.groups(run_id)


@router.get('/runs/{run_id}/report')
def report(run_id:str,store=Depends(get_store)):
    path=store.write_report(run_id)
    return FileResponse(path,media_type='text/markdown',filename=path.name)


@router.get('/runs/{run_id}/items')
def items(run_id:str,routine_id:str='',category:str='',keyword:str='',confidence:str='',completeness:str='',review_status:str='',status:str='',kind:str='',needs_content:bool=False,
          page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100),store=Depends(get_store)):
    store.run(run_id)
    filters={k:v for k,v in locals().items() if k in {'routine_id','category','keyword','confidence','completeness','review_status','status','kind','needs_content'} and v}
    return store.rows(run_id,filters,page,page_size)


@router.get('/runs/{run_id}/items/{item_id}')
def item(run_id:str,item_id:int,store=Depends(get_store)):
    return store.item(run_id,item_id)


@router.get('/runs/{run_id}/items/{item_id}/assets/{index}')
def asset(run_id:str,item_id:int,index:int,store=Depends(get_store)):
    data=store.item(run_id,item_id); paths=asset_paths(data['occurrences'])
    if not 0<=index<len(paths): raise HTTPException(404,'附件不可用。')
    return FileResponse(paths[index])


@router.post('/runs/{run_id}/decisions')
def decide(run_id:str,req:DecisionRequest,store=Depends(get_store)):
    if req.action not in ('confirm','assign','defer','reject','mark') or not set(req.marks or [])<={'representative','variant'}:
        raise HTTPException(422,'审核动作或题目标记无效。')
    return store.decide(run_id,req)


@router.post('/runs/{run_id}/items/{item_id}/rematch',status_code=202)
def rematch(run_id:str,item_id:int,req:StartRequest,store=Depends(get_store)):
    original=store.run(run_id); data=store.item(run_id,item_id)
    if data['human']: raise HTTPException(409,'此题已有人工决定，不自动覆盖。')
    if original['status'] in ('running','queued'): raise HTTPException(409,'请等待批次结束或暂停后重匹配。')
    catalog=reference_store().read()['catalog']
    if data['source_stale']: raise HTTPException(409,'原题已改变，请建立新快照。')
    config=original['model_config']
    with store.connection() as conn,conn:
        conn.execute("UPDATE review_items SET status='pending',result_json=NULL,primary_id=NULL,secondary_json='[]',confidence='',kind='',catalog_json=?,cache_key=? WHERE run_id=? AND item_id=?",(rc_json(catalog),rc.cache_key(data['item'],catalog,config),run_id,item_id))
        conn.execute("UPDATE review_runs SET stop=0,status='ready' WHERE run_id=?",(run_id,))
    return enqueue_run(store,run_id,req.request_id,item_id)


@router.post('/runs/{run_id}/items/{item_id}/create-routine')
def create_routine(run_id:str,item_id:int,req:CreateRequest,store=Depends(get_store)):
    from backend.routine_matching_api import ReviewDecision
    from pydantic import ValidationError
    if req.expected_revision!=store.run(run_id)['revision']:
        raise HTTPException(409,'审核结果已变更，请刷新后重新提交。')
    try:
        decision=ReviewDecision(**req.decision)
    except ValidationError:
        raise HTTPException(422,'新套路审核字段无效。') from None
    if decision.action!='create': raise HTTPException(422,'此入口只确认新套路。')
    data=store.item(run_id,item_id); result=data['result']; entry=result.get('review')
    if data['source_stale']: raise HTTPException(409,'原题已经改变，请重新匹配。')
    if not entry or entry['kind']!='new_routine_candidate': raise HTTPException(409,'此题没有经过完整复查的新套路草案。')
    reference=reference_store()
    try:
        if entry['review_id'] not in reference.read()['decisions']:
            reference.enqueue(entry)
        saved=reference.decide(entry['review_id'],decision.dict(exclude_none=True))
    except ValueError as exc: raise HTTPException(409,str(exc)) from None
    approved=DecisionRequest(action='assign',item_ids=[item_id],expected_revision=req.expected_revision,primary_id=saved['routine_id'],note=decision.note)
    store.decide(run_id,approved)
    return {'decision':saved,'advisory_only':True,'formal_pattern_created':False}
