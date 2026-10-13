"""Owner's editable method map, sharing the reference catalogue and review ledger."""
from copy import deepcopy
import math
import re
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StrictStr

from backend import routine_classification as rc, routine_review as rr
from backend.routine_matching import CATEGORY_PREFIXES, _name_key
from backend.routine_matching_api import RoutineDraft, _dump

router = APIRouter(prefix='/routine-graph', tags=['套路图谱'], dependencies=[Depends(rr.require_owner)])
page_router = APIRouter(dependencies=[Depends(rr.require_owner)])


def graph_path(reference):
    return reference.directory / 'graph.json'


def read_layout(reference):
    path = graph_path(reference)
    return rc.read_json(path) if path.exists() else {'revision':0, 'positions':{}}


def build_graph(catalog, groups=()):
    counts = {g['id']:g for g in groups}
    nodes = [{'id':'root','kind':'root','name':'数学解题套路','description':'按现有知识板块浏览套路，直接回到题目审核。'}]
    edges = []
    for category, prefix in CATEGORY_PREFIXES.items():
        cid = 'category:'+prefix
        nodes.append({'id':cid,'kind':'category','name':category,'category':category})
        edges.append({'source':'root','target':cid,'kind':'contains'})
        for r in [r for r in catalog['routines'] if r['category']==category]:
            count = counts.get(r['id'],{})
            nodes.append({**r,'kind':'routine','parent':cid,'total':count.get('total',0),
                          'pending':count.get('pending',0),'confirmed':count.get('confirmed',0)})
            edges.append({'source':cid,'target':r['id'],'kind':'contains'})
    seen = set()
    for r in catalog['routines']:
        for other in r['confusable_ids']:
            pair = tuple(sorted((r['id'],other)))
            if pair not in seen:
                seen.add(pair)
                edges.append({'source':pair[0],'target':pair[1],'kind':'confusable'})
    return nodes, edges


class Position(BaseModel):
    x: float = Field(...,ge=-50000,le=50000)
    y: float = Field(...,ge=-50000,le=50000)

    class Config:
        extra = 'forbid'


class LayoutRequest(BaseModel):
    expected_revision: int = Field(...,ge=0)
    positions: Dict[str,Position] = Field(default_factory=dict)

    class Config:
        extra = 'forbid'


class ManualDraft(RoutineDraft):
    # A new human-authored method need not have an actually confusable method.
    confusable_ids: List[StrictStr] = Field(default_factory=list,max_items=3)


class CreateRequest(BaseModel):
    request_id: StrictStr = Field(...,min_length=8,max_length=100)
    expected_catalog_hash: StrictStr = Field(...,min_length=64,max_length=64)
    draft: ManualDraft

    class Config:
        extra = 'forbid'


@page_router.get('/routine-graph.html',include_in_schema=False)
def graph_page():
    return FileResponse(rc.ROOT/'frontend/routine-graph.html')


@router.get('')
def get_graph(run_id:str='',store=Depends(rr.get_store),reference=Depends(rr.reference_store)):
    run = store.run(run_id or None)
    grouped = store.groups(run['run_id'])['groups'] if run else []
    if run:
        with store.connection() as conn:
            pending = dict(conn.execute("SELECT primary_id,count(*) FROM review_items WHERE run_id=? AND review_status='pending' GROUP BY primary_id",(run['run_id'],)).fetchall())
        grouped = [{**g,'pending':pending.get(g['id'],0)} for g in grouped]
    catalog = reference.read()['catalog']
    nodes,edges = build_graph(catalog,grouped)
    return {'nodes':nodes,'edges':edges,'layout':read_layout(reference),'catalog_hash':rc.digest(catalog),
            'run':{k:run[k] for k in ('run_id','status','total','revision')} if run else None,
            'categories':list(CATEGORY_PREFIXES)}


@router.put('/layout')
def save_layout(req:LayoutRequest,reference=Depends(rr.reference_store)):
    with reference.locked():
        current = read_layout(reference)
        if req.expected_revision!=current['revision']:
            raise HTTPException(409,'图谱已在其他页面修改；请刷新后再调整，当前修改尚未保存。')
        nodes,_ = build_graph(reference.read()['catalog'])
        ids = {n['id'] for n in nodes}
        if len(req.positions)>len(ids) or not set(req.positions)<=ids:
            raise HTTPException(422,'含无效节点。')
        for pos in req.positions.values():
            if not math.isfinite(pos.x) or not math.isfinite(pos.y):
                raise HTTPException(422,'坐标必须是有限数字。')
        saved = {'revision':current['revision']+1,'positions':{**current['positions'],**{k:_dump(v) for k,v in req.positions.items()}}}
        rc.write_json(graph_path(reference),saved)
    return saved


@router.post('/routines',status_code=201)
def add_routine(req:CreateRequest,reference=Depends(rr.reference_store)):
    with reference.locked():
        state = reference.read()
        draft = _dump(req.draft)
        # A lost response can safely be retried without creating a second node.
        previous = next((h for h in state['history'] if h.get('graph_request_id')==req.request_id),None)
        if previous:
            if previous['draft_hash']!=rc.digest(draft):
                raise HTTPException(409,'请求编号已用于另一个套路。')
            return {'routine_id':previous['routine_id'],'catalog_hash':rc.digest(state['catalog'])}
        catalog = state['catalog']
        if rc.digest(catalog)!=req.expected_catalog_hash:
            raise HTTPException(409,'套路目录已变更；请刷新图谱后再添加。')
        if _name_key(draft['name']) in {_name_key(r['name']) for r in catalog['routines']}:
            raise HTTPException(409,'已有同名套路，请先查看已有节点。')
        if draft['category'] not in CATEGORY_PREFIXES:
            raise HTTPException(422,'请选择已有数学板块。')
        prefix = CATEGORY_PREFIXES[draft['category']]
        number = 1+max(int(r['id'].split('-')[1]) for r in catalog['routines'] if r['id'].startswith(prefix+'-'))
        rid = f'{prefix}-{number:03d}'
        updated = deepcopy(catalog)
        updated['routines'].append({'id':rid,**draft})
        version = re.fullmatch(r'(.*)\.r(\d+)',catalog['version'])
        updated['version'] = version[1]+f'.r{int(version[2])+1}' if version else catalog['version']+'.r1'
        try:
            rc.validate_catalog(updated)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from None
        state['catalog'] = updated
        state['history'].append({'graph_request_id':req.request_id,'routine_id':rid,'draft_hash':rc.digest(draft),
                                 'catalog_before':rc.digest(catalog),'catalog_after':rc.digest(updated),'action':'manual_create'})
        rc.write_json(reference.path,state)
    return {'routine_id':rid,'catalog_hash':rc.digest(updated)}
