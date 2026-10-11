"""Compile bounded geometry data, validate declared relations, and prebuild hints.

No generated code is evaluated. Parametric scenes are compiled to numeric frames
on the server; clients only draw those frames. Validation checks declared source
conditions, not the completeness or correctness of a mathematical proof.
"""
import ast
from copy import deepcopy
from hashlib import sha256
import json
import logging
import math
from pathlib import Path
import re

logger = logging.getLogger(__name__)
VERSION = 1
MAX_OBJECTS = 160
MAX_FRAMES = 61
KINDS = {"point", "segment", "line", "vector", "polygon", "plane", "solid", "circle", "conic", "curve", "sphere", "cone", "cylinder", "angle", "label"}
FUNCTIONS = {name: getattr(math, name) for name in ("sin", "cos", "tan", "sqrt", "acos", "asin", "atan", "exp", "log")}
FUNCTIONS["abs"] = abs


def number(value, variables=None):
    """Small arithmetic AST, with explicit nodes/functions and size limits."""
    if isinstance(value, bool):
        raise ValueError("坐标必须为数值")
    if isinstance(value, str):
        if len(value) > 160:
            raise ValueError("表达式过长")
        tree = ast.parse(value, mode="eval")
        if len(list(ast.walk(tree))) > 64:
            raise ValueError("表达式过于复杂")
        def visit(n):
            if isinstance(n, ast.Expression):
                return visit(n.body)
            if isinstance(n, ast.Constant) and type(n.value) in (int, float):
                return float(n.value)
            if isinstance(n, ast.Name) and n.id in {"pi", *(variables or {})}:
                return {"pi": math.pi, **(variables or {})}[n.id]
            if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
                return visit(n.operand) * (-1 if isinstance(n.op, ast.USub) else 1)
            if isinstance(n, ast.BinOp):
                a, b = visit(n.left), visit(n.right)
                if isinstance(n.op, ast.Add): return a + b
                if isinstance(n.op, ast.Sub): return a - b
                if isinstance(n.op, ast.Mult): return a * b
                if isinstance(n.op, ast.Div): return a / b
                if isinstance(n.op, ast.Pow) and abs(b) <= 8: return a ** b
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCTIONS and len(n.args) == 1 and not n.keywords:
                return FUNCTIONS[n.func.id](visit(n.args[0]))
            raise ValueError("不允许的几何表达式")
        value = visit(tree)
    if type(value) not in (float, int) or not math.isfinite(value) or abs(value) > 1e6:
        raise ValueError("坐标或参数超出有限数值范围")
    return float(value)


def coords(value, dimension, variables=None):
    if not isinstance(value, list) or len(value) != dimension:
        raise ValueError("坐标维数不符")
    return [number(x, variables) for x in value]


def sub(a, b): return [x-y for x, y in zip(a, b)]
def add(a, b): return [x+y for x, y in zip(a, b)]
def mul(a, t): return [x*t for x in a]
def dot(a, b): return sum(x*y for x, y in zip(a, b))
def norm(a): return math.sqrt(dot(a, a))
def cross(a, b):
    if len(a) == 2: return [a[0]*b[1]-a[1]*b[0]]
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def unit(a):
    if norm(a) < 1e-9: raise ValueError("退化的方向向量")
    return mul(a, 1/norm(a))
def near(a, b=0): return abs(a-b) <= 1e-6 * max(1, abs(a), abs(b))


def step_keys(answer):
    result = []
    for i, chunk in enumerate(answer.get("chunk_results") or []):
        for j, step in enumerate(chunk.get("steps") or []):
            key = f"{chunk.get('chunk_id', i+1)}-{step.get('step_number', j+1)}"
            if key in result: raise ValueError("解析步骤编号重复")
            result.append(key)
    return result


def fingerprint(question, answer, asset_refs=None):
    # Difficulty updates do not invalidate a geometric construction.
    chunks = [{"chunk_id": c.get("chunk_id", i+1), "steps": [
        {k: s.get(k) for k in ("step_number", "title", "standard_writing", "detailed_writing")}
        for s in c.get("steps") or []]} for i, c in enumerate(answer.get("chunk_results") or [])]
    return sha256(json.dumps([question.strip(), chunks, asset_refs or []], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def is_geometry(question, answer):
    categories = [str(c.get("category") or "") for c in answer.get("chunk_results") or []]
    return any(x in " ".join(categories) for x in ("立体几何", "解析几何")) or bool(
        re.search(r"棱锥|棱柱|正方体|长方体|二面角|异面直线|椭圆|双曲线|抛物线|圆锥曲线|球面", question))


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[\w-]{1,48}", value):
        raise ValueError("几何对象编号不合法")
    return value


def _construct(spec, objects, d, variables):
    if not isinstance(spec, dict): raise ValueError("构造必须为对象")
    def p(name):
        obj = objects.get(name)
        if not obj or obj["kind"] != "point": raise ValueError(f"点引用不存在：{name}")
        return obj["coords"]
    kind = spec.get("kind")
    if kind in ("midpoint", "ratio"):
        t = 0.5 if kind == "midpoint" else number(spec.get("t"), variables)
        return add(p(spec["a"]), mul(sub(p(spec["b"]), p(spec["a"])), t))
    if kind == "projection":
        a, b, q = p(spec["a"]), p(spec["b"]), p(spec["point"])
        v = sub(b, a); unit(v)
        return add(a, mul(v, dot(sub(q, a), v)/dot(v, v)))
    if kind == "intersection" and d == 2:
        a, b, c, e = [p(spec[k]) for k in ("a", "b", "c", "d")]
        v, w = sub(b, a), sub(e, c)
        den = cross(v, w)[0]
        if abs(den) < 1e-9: raise ValueError("直线没有唯一交点")
        return add(a, mul(v, cross(sub(c, a), w)[0]/den))
    if kind == "rotate" and d == 3:
        origin, end, q = [p(spec[k]) for k in ("a", "b", "point")]
        u, v, t = unit(sub(end, origin)), sub(q, origin), number(spec["angle"], variables)
        return add(origin, add(add(mul(v, math.cos(t)), mul(cross(u, v), math.sin(t))), mul(u, dot(u, v)*(1-math.cos(t)))))
    if kind == "plane_projection" and d == 3:
        a, b, c, q = [p(spec[k]) for k in ("a", "b", "c", "point")]
        n = unit(cross(sub(b, a), sub(c, a)))
        return sub(q, mul(n, dot(sub(q, a), n)))
    raise ValueError("未支持的点构造")


def _compile_objects(raw, d, variables):
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_OBJECTS: raise ValueError("场景对象数量不合法")
    objects = {}
    def point(name):
        if name not in objects or objects[name]["kind"] != "point": raise ValueError(f"引用点不存在：{name}")
        return objects[name]["coords"]
    for item in raw:
        if not isinstance(item, dict): raise ValueError("对象不是 JSON 对象")
        key, kind = _name(item.get("id")), item.get("kind")
        if key in objects or kind not in KINDS: raise ValueError("对象重复或类型未支持")
        obj = {"id": key, "kind": kind, "label": str(item.get("label") or "")[:80],
               "base": item.get("base") is True, "dashed": item.get("dashed") is True}
        if item.get("introduced_at") is not None:
            obj["introduced_at"] = _name(item["introduced_at"])
        if kind == "point":
            obj["coords"] = coords(_construct(item["construct"], objects, d, variables), d) if item.get("construct") else coords(item.get("coords"), d, variables)
        elif kind in ("segment", "line", "vector"):
            obj.update(a=item.get("a"), b=item.get("b"))
            unit(sub(point(obj["a"]), point(obj["b"])))
        elif kind in ("polygon", "plane", "solid", "angle"):
            if kind == "solid" and d != 3: raise ValueError("几何体需要三维场景")
            faces = item.get("faces") if kind == "solid" else [item.get("points")]
            if not isinstance(faces, list) or not 1 <= len(faces) <= 40: raise ValueError("面数量不合法")
            for face in faces:
                if not isinstance(face, list) or not 3 <= len(face) <= 30: raise ValueError("面顶点数量不合法")
                pts = [point(x) for x in face]
                n = cross(sub(pts[1], pts[0]), sub(pts[2], pts[0])); unit(n)
                if d == 3 and any(not near(dot(sub(q, pts[0]), unit(n))) for q in pts[3:]): raise ValueError("面顶点不共面")
            if kind == "angle" and len(faces[0]) != 3: raise ValueError("角需要三个点")
            obj["faces" if kind == "solid" else "points"] = faces if kind == "solid" else faces[0]
        elif kind in ("circle", "sphere", "cone", "cylinder"):
            if kind == "sphere" and d != 3: raise ValueError("球需要三维场景")
            obj["center"] = item.get("center"); point(obj["center"])
            obj["radius"] = number(item.get("radius"), variables)
            if obj["radius"] <= 1e-9: raise ValueError("半径必须为正")
            if kind in ("cone", "cylinder"):
                if d != 3: raise ValueError("旋转体必须为三维")
                obj["end"] = item.get("end"); unit(sub(point(obj["end"]), point(obj["center"])))
            if kind == "circle" and d == 3: obj["normal"] = unit(coords(item.get("normal", [0,0,1]), d, variables))
        elif kind == "conic":
            if d != 2: raise ValueError("圆锥曲线需要二维场景")
            c = coords(item.get("coefficients"), 6, variables)
            a,b,c2,e,f,g = c
            det = a*(c2*g-f*f/4)-b/2*(b*g/2-f*e/4)+e/2*(b*f/4-c2*e/2)
            if max(abs(a),abs(b),abs(c2)) < 1e-9 or abs(det) < 1e-10: raise ValueError("退化的圆锥曲线")
            obj["coefficients"] = c
        elif kind == "curve":
            points = item.get("samples")
            if not isinstance(points, list) or not 2 <= len(points) <= 500: raise ValueError("曲线采样数量不合法")
            obj["samples"] = [coords(p, d, variables) for p in points]
        elif kind == "label": obj["coords"] = coords(item.get("coords"), d, variables)
        objects[key] = obj
    return objects


def _check_constraints(constraints, objects, source, variables):
    if not isinstance(constraints, list) or not 1 <= len(constraints) <= 80: raise ValueError("场景必须声明来源条件及校验关系")
    def p(name):
        if name not in objects or objects[name]["kind"] != "point": raise ValueError("校验点引用错误")
        return objects[name]["coords"]
    for c in constraints:
        if not isinstance(c, dict): raise ValueError("校验关系必须为对象")
        evidence = c.get("source")
        if not isinstance(evidence, str) or not evidence.strip() or evidence not in source: raise ValueError("几何条件缺少原题或解析的原文依据")
        kind = c.get("kind")
        if kind == "distance":
            ok = near(norm(sub(p(c["a"]), p(c["b"]))), number(c["value"], variables))
        elif kind in ("parallel", "perpendicular", "angle"):
            u, v = sub(p(c["b"]),p(c["a"])), sub(p(c["d"]),p(c["c"]))
            u, v = unit(u), unit(v)
            ok = (near(norm(cross(u,v))) if kind == "parallel" else near(dot(u,v)) if kind == "perpendicular" else near(dot(u,v),math.cos(number(c["value"],variables))))
        elif kind in ("coplanar", "on_plane"):
            a,b,e,q = [p(c[k]) for k in ("a","b","c","point")]
            if len(a) != 3: raise ValueError("平面关系需要三维点")
            ok = near(dot(sub(q,a),unit(cross(sub(b,a),sub(e,a)))))
        elif kind == "on_line":
            ok = near(norm(cross(unit(sub(p(c["b"]),p(c["a"]))),sub(p(c["point"]),p(c["a"])))))
        elif kind == "on_conic":
            x,y = p(c["point"]); a,b,e,f,g,h = objects[c["conic"]]["coefficients"]
            ok = near(a*x*x+b*x*y+e*y*y+f*x+g*y+h)
        elif kind in ("on_circle", "on_sphere"):
            obj = objects[c["object"]]
            if obj["kind"] != ("circle" if kind == "on_circle" else "sphere"): raise ValueError("圆或球引用错误")
            q, center = p(c["point"]), p(obj["center"])
            ok = near(norm(sub(q,center)),obj["radius"])
            if kind == "on_circle" and len(q) == 3:
                ok = ok and near(dot(sub(q,center),obj["normal"]))
        elif kind == "tangent":
            x,y = p(c["point"])
            a,b,e,f,g,h = objects[c["conic"]]["coefficients"]
            direction = unit(sub(p(c["b"]),p(c["a"])))
            gradient = unit([2*a*x+b*y+f,b*x+2*e*y+g])
            ok = near(a*x*x+b*x*y+e*y*y+f*x+g*y+h) and near(dot(direction,gradient))
            ok = ok and near(norm(cross(direction,sub(p(c["point"]),p(c["a"])))))
        elif kind == "curve_on_conic":
            a,b,e,f,g,h = objects[c["conic"]]["coefficients"]
            samples = objects[c["curve"]]["samples"]
            ok = all(near(a*x*x+b*x*y+e*y*y+f*x+g*y+h) for x,y in samples)
        elif kind == "length_sum":
            pairs = c.get("pairs")
            if not isinstance(pairs,list) or not 1 <= len(pairs) <= 16: raise ValueError("长度和引用错误")
            ok = near(sum(norm(sub(p(pair[0]),p(pair[1]))) for pair in pairs),number(c["value"],variables))
        elif kind == "point_fixed":
            q = p(c["point"]); value = coords(c["coords"],len(q))
            ok = near(norm(sub(q,value)))
        else: raise ValueError("未支持的几何校验关系")
        if not ok: raise ValueError(f"几何模型不满足条件：{evidence[:100]}")


def compile_geometry(raw, question, answer):
    """Return validated numeric scenes; keep independently valid scenes on failure."""
    if not isinstance(raw, dict): raise ValueError("演示不是对象")
    if raw.get("status") == "unavailable":
        return {"version": VERSION, "status": "unavailable", "reason": str(raw.get("reason") or "无法确定几何构型")[:300], "scenes": [], "steps": [], "issues": []}
    source = question + "\n" + "\n".join(str(s.get(k) or "") for c in answer.get("chunk_results") or [] for s in c.get("steps") or [] for k in ("standard_writing","detailed_writing"))
    scene_list = raw.get("scenes")
    if not isinstance(scene_list, list) or not 1 <= len(scene_list) <= 6: raise ValueError("场景数量不合法")
    scenes, issues = {}, []
    for scene in scene_list:
        try:
            if not isinstance(scene,dict): raise ValueError("场景必须为对象")
            sid = _name(scene.get("id"))
            if sid in scenes: raise ValueError("场景编号重复")
            d = scene.get("dimension")
            if d not in (2,3): raise ValueError("场景维数不支持")
            param = scene.get("parameter")
            values = [None]
            if param:
                if not isinstance(param,dict): raise ValueError("参数必须为对象")
                name = _name(param.get("name")); lo,hi = number(param.get("min")), number(param.get("max"))
                if name == "pi" or name in FUNCTIONS: raise ValueError("参数名称不能覆盖数学常量或函数")
                initial = number(param.get("value",lo))
                if not lo < hi or not lo <= initial <= hi: raise ValueError("参数范围或初值错误")
                values = sorted(set([lo+(hi-lo)*i/(MAX_FRAMES-1) for i in range(MAX_FRAMES)] + [initial]))
            frames = []
            for t in values:
                variables = {name: t} if param else {}
                objects = _compile_objects(scene.get("objects"), d, variables)
                _check_constraints(scene.get("constraints"), objects, source, variables)
                frames.append({"value":t,"objects":list(objects.values())})
                samples = sum(len(o.get("samples",[])) for o in objects.values())
                if samples * len(values) > 100000: raise ValueError("参数场景采样过多")
            bounds = scene.get("bounds",[-6,6,6,-6])
            bounds = coords(bounds,4)
            if not bounds[0]<bounds[2] or not bounds[3]<bounds[1]: raise ValueError("画板范围错误")
            compiled = {"id":sid,"dimension":d,"title":str(scene.get("title") or "几何演示")[:100],"bounds":bounds,"objects":frames[0]["objects"]}
            if param: compiled.update(parameter={"name":name,"min":lo,"max":hi,"value":initial},frames=frames)
            scenes[sid] = compiled
        except (ValueError, KeyError, TypeError, ArithmeticError, SyntaxError) as exc:
            issues.append(str(exc)[:250])
    keys = step_keys(answer)
    raw_steps = raw.get("steps") or []
    if not isinstance(raw_steps,list) or len(raw_steps)>120: raise ValueError("演示步骤数量错误")
    steps, seen = [], set()
    for st in raw_steps:
        try:
            if not isinstance(st,dict): raise ValueError("步骤演示必须为对象")
            key = st.get("step_key")
            if key not in keys or key in seen: raise ValueError("演示步骤编号错误或重复")
            scene = scenes.get(st.get("scene_id"))
            if not scene: raise ValueError(f"步骤 {key} 的场景不可用")
            allowed = {o["id"] for o in scene["objects"]}
            base = {o["id"] for o in scene["objects"] if o["base"]}
            def ids(value):
                if not isinstance(value,list) or any(x not in allowed for x in value): raise ValueError("演示对象引用不存在")
                return list(dict.fromkeys(value))
            full = ids(st.get("full_visible")); groups = st.get("hint_groups") or []
            if not isinstance(groups,list) or len(groups)>16: raise ValueError("提示分组数量错误")
            compiled_groups = []
            for group in groups:
                if not isinstance(group,dict): raise ValueError("提示组必须为对象")
                text = group.get("text")
                if not isinstance(text,str) or not text.strip() or len(text)>1500: raise ValueError("绘图提示文字错误")
                visible = ids(group.get("visible",[])); highlight = ids(group.get("highlight",visible))
                if not set(visible)<=set(full) or not set(highlight)<=set(full)|base: raise ValueError("提示越过本步完整构造")
                compiled_groups.append({"text":text,"visible":visible,"highlight":highlight})
            steps.append({"step_key":key,"scene_id":scene["id"],"full_visible":full,"hint_groups":compiled_groups})
            seen.add(key)
        except (ValueError,KeyError,TypeError) as exc: issues.append(str(exc)[:250])
    steps.sort(key=lambda s:keys.index(s["step_key"]))
    # Explicit construction ownership prevents inconsistent AI plans from
    # exposing later auxiliaries. Missing ownership is inferred from first use.
    valid_steps = []
    for st in steps:
        objects = {o["id"]:o for o in scenes[st["scene_id"]]["objects"]}
        invalid = any(objects[oid].get("introduced_at") and
                      (objects[oid]["introduced_at"] not in keys or keys.index(objects[oid]["introduced_at"])>keys.index(st["step_key"]))
                      for oid in st["full_visible"] if not objects[oid]["base"])
        if invalid:
            issues.append(f"步骤 {st['step_key']} 引用后续步骤构造")
            seen.discard(st["step_key"])
        else:
            valid_steps.append(st)
    steps = valid_steps
    status = "ready" if scenes and steps and not issues and set(keys)==seen else "partial" if scenes and steps else "unavailable"
    return {"version":VERSION,"status":status,"reason":"；".join(issues)[:500] or ("部分步骤仅提供文字说明" if status=="partial" else ""),"scenes":list(scenes.values()),"steps":steps,"issues":issues}


def prepare_geometry(question, answer, teacher=None, asset_refs=None):
    refs = asset_refs if asset_refs is not None else answer.get("asset_refs",[])
    if refs: answer["asset_refs"] = list(refs)
    if not is_geometry(question,answer): return answer
    digest = fingerprint(question,answer,refs)
    old = answer.get("geometry")
    if isinstance(old,dict) and old.get("version")==VERSION and old.get("source_hash")==digest: return answer
    result = {"version":VERSION,"status":"unavailable","reason":"几何演示尚未完成","scenes":[],"steps":[],"issues":[]}
    try:
        from backend.solver import call_deepseek, _extract_json
        from backend.settings import get_teacher_config
        cfg = get_teacher_config(teacher)["solver"]
        prompt = Path(__file__).with_name("prompts").joinpath("geometry.md").read_text(encoding="utf-8")
        payload = {"question":question,"chunk_results":answer.get("chunk_results"),"step_keys":step_keys(answer)}
        feedback = None
        for attempt in range(2):
            message = json.dumps(payload,ensure_ascii=False) + ("\n上次校验失败，请修复完整 JSON："+feedback if feedback else "")
            if refs:
                from backend.question_assets import image_messages
                content, usage = call_deepseek(prompt,message,model="deepseek-flash",image_content=image_messages(refs))
            else:
                content, usage = call_deepseek(prompt,message,model=cfg["model"],reasoning_effort=cfg.get("reasoning_effort"),temperature=0.1)
            totals = answer.setdefault("token_usage",{})
            for key in ("prompt_tokens","completion_tokens","total_tokens"): totals[key] = totals.get(key,0)+usage.get(key,0)
            try:
                raw = json.loads(_extract_json(content))
                candidate = compile_geometry(raw,question,answer)
                if len(candidate["steps"]) >= len(result["steps"]):
                    result = candidate
                if candidate["status"]=="ready" or raw.get("status")=="unavailable": break
                feedback = json.dumps(candidate.get("issues") or [candidate["reason"]],ensure_ascii=False)
            except (ValueError,KeyError,TypeError,ArithmeticError,SyntaxError) as exc:
                feedback = str(exc)
                if result["status"] == "unavailable":
                    result["reason"] = "几何校验失败：" + feedback[:300]
    except Exception as exc:
        logger.warning("geometry preparation unavailable: %s",type(exc).__name__)
        if result["status"]=="unavailable": result["reason"] = "几何演示生成未完成，请保留文字解析并核对题图。"
    result["source_hash"] = digest
    answer["geometry"] = result
    return answer


def release_hint(session, step, full=False):
    geometry = session.get("geometry") or {}
    key = f"{step.get('chunk_id',1)}-{step.get('step_number',0)}"
    view = next((s for s in geometry.get("steps",[]) if s["step_key"]==key),None)
    if not view: return None
    state = session.setdefault("geometry_state",{"released":{},"completed":[]})
    count = state["released"].get(key,0)
    groups = view["hint_groups"]
    if full:
        state["released"][key] = len(groups)
        if key not in state["completed"]: state["completed"].append(key)
        return None
    if count >= len(groups): return {"text":"本步的辅助构造已经全部展示，可以继续思考或查看本步答案。"}
    state["released"][key] = count+1
    return deepcopy(groups[count])
