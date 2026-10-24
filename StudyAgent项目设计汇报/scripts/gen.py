# -*- coding: utf-8 -*-
"""StudyAgent 项目设计汇报 — 页面生成器
母版：A 标题块 0-120px / B 内容区 120-660px / C 页脚条 660-720px
"""
import os, json, sys, importlib

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLIDES = os.path.join(BASE, "slides")

# ---------- 设计常量 ----------
NAVY   = "#0E2340"
BLUE   = "#1E7BE0"
TEAL   = "#00A9B5"
SURF   = "#F5F7FA"
TEXT   = "#333A45"
MUTE   = "#7A8699"
LINE   = "#E3E8EF"

STATUS = {
    "已实现":   "#1E9E62",
    "部分实现": "#E8A33D",
    "设计中":   "#1E7BE0",
    "待研究":   "#98A2B3",
}

TOTAL = 115


def esc(s):
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "＜").replace(">", "＞"))


def t(s, size=19, color=TEXT, weight=400, lh=1.6, align=None, extra=""):
    st = "fontSize: %d, color: '%s', fontWeight: %d, lineHeight: %.1f" % (size, color, weight, lh)
    if align:
        st += ", textAlign: '%s'" % align
    if extra:
        st += ", " + extra
    return "<Text style={{ %s }}>%s</Text>" % (st, esc(s))


# =========================================================
# 母版骨架
# =========================================================
def header(ch, chn, title, status=None):
    pill = ""
    if status and status in STATUS:
        c = STATUS[status]
        pill = (
            "<Box style={{ flexDirection: 'row', alignItems: 'center', padding: '7px 16px', "
            "borderRadius: 20, background: '%s' }}>"
            "<Text style={{ fontSize: 14, color: '#FFFFFF', fontWeight: 600 }}>%s</Text></Box>"
            % (c, status)
        )
    return (
        "<Box style={{ height: 100, flexDirection: 'row', justifyContent: 'space-between', "
        "alignItems: 'flex-end' }}>"
        "<Box style={{ flexDirection: 'column', gap: 6 }}>"
        + t("%s / %s" % (ch, chn), 14, MUTE, 400, 1.4, extra="letterSpacing: 1")
        + t(title, 32, NAVY, 700, 1.3)
        + "</Box>" + pill + "</Box>"
    )


def footer(src, num):
    return (
        "<Box style={{ height: 40, flexDirection: 'row', justifyContent: 'space-between', "
        "alignItems: 'center', borderTop: '1px solid %s', marginTop: 8 }}>" % LINE
        + t(src, 13, MUTE, 400, 1.4)
        + t("%02d / %d" % (num, TOTAL), 14, MUTE, 400, 1.4)
        + "</Box>"
    )


def page(ch, chn, title, status, src, num, body, bg="#FFFFFF"):
    return (
        "<Slide style={{ width: '1280px', height: '720px', background: '%s', "
        "padding: '20px 70px', display: 'flex', flexDirection: 'column' }}>" % bg
        + header(ch, chn, title, status)
        + "<Box style={{ height: 532, paddingTop: 8, flexDirection: 'column' }}>" + body + "</Box>"
        + footer(src, num)
        + "</Slide>"
    )


# =========================================================
# 通用容器
# =========================================================
def card(w, children, top_bar=True, bg="#FFFFFF", pad=20):
    bar = ("<Box style={{ height: 4, background: 'linear-gradient(90deg, %s 0%%, %s 100%%)' }} />"
           % (BLUE, TEAL)) if top_bar else ""
    return (
        "<Box style={{ width: %s, background: '%s', border: '1px solid %s', borderRadius: 8, "
        "overflow: 'hidden', flexDirection: 'column' }}>" % (w, bg, LINE)
        + bar
        + "<Box style={{ flexDirection: 'column', gap: 10, padding: %d, flex: 1 }}>%s</Box>" % (pad, children)
        + "</Box>"
    )


def cards_row(items, gap=20):
    """items: list of card html strings"""
    return "<Box style={{ flexDirection: 'row', gap: %d, flex: 1 }}>%s</Box>" % (gap, "".join(items))


def kv_cards(rows, gap=20, title_size=24, body_size=19):
    """rows: [(标题, 正文), ...] 自动等宽横排"""
    n = len(rows)
    gap_total = gap * (n - 1)
    w = (1140 - gap_total) // n
    out = []
    for h, b in rows:
        out.append(card(w, t(h, title_size, NAVY, 600, 1.4) + t(b, body_size, TEXT, 400, 1.65)))
    return cards_row(out, gap)


def bullets(items, size=20, color=TEXT, gap=14, marker=BLUE):
    out = []
    for it in items:
        if isinstance(it, tuple):
            head, desc = it
            inner = ("<Box style={{ width: 8, height: 8, borderRadius: 4, background: '%s', "
                     "marginTop: 9 }} />" % marker
                     + "<Box style={{ flex: 1 }}>"
                     + t(head, size, NAVY, 600, 1.5)
                     + t(desc, size - 1, color, 400, 1.6)
                     + "</Box>")
        else:
            inner = ("<Box style={{ width: 8, height: 8, borderRadius: 4, background: '%s', "
                     "marginTop: 9 }} />" % marker
                     + "<Box style={{ flex: 1 }}>" + t(it, size, color, 400, 1.6) + "</Box>")
        out.append("<Box style={{ flexDirection: 'row', gap: 12, alignItems: 'flex-start' }}>%s</Box>" % inner)
    return "<Box style={{ flexDirection: 'column', gap: %d }}>%s</Box>" % (gap, "".join(out))


def callout(text, color=NAVY, bg=SURF, size=20):
    return (
        "<Box style={{ flexDirection: 'row', alignItems: 'center', background: '%s', "
        "borderLeft: '4px solid %s', borderRadius: 6, padding: '14px 20px' }}>" % (bg, color)
        + t(text, size, NAVY, 600, 1.5) + "</Box>"
    )


def big_number(num, unit, desc, size=88):
    return (
        "<Box style={{ flexDirection: 'row', alignItems: 'baseline', gap: 10 }}>"
        + t(num, size, BLUE, 700, 1.0)
        + t(unit, 26, MUTE, 600, 1.2) + "</Box>"
        + t(desc, 20, TEXT, 400, 1.6)
    )


# =========================================================
# 表格
# =========================================================
def table(cells, widths=None, font=17, head_bg=NAVY, zebra=True, pad=10):
    js = []
    for r_i, row in enumerate(cells):
        rr = []
        for c_i, c in enumerate(row):
            if r_i == 0:
                rr.append("{ text: '%s', textStyle: { color: '#FFFFFF', fontWeight: 600, fontSize: %d }, "
                          "cellStyle: { background: { color: '%s' } } }" % (esc(c).replace("'", "’"), font, head_bg))
            else:
                bg = ""
                if zebra and r_i % 2 == 0:
                    bg = ", cellStyle: { background: { color: '%s' } }" % SURF
                bold = "fontWeight: 600, " if c_i == 0 else ""
                rr.append("{ text: '%s', textStyle: { %sfontSize: %d }%s }"
                          % (esc(c).replace("'", "’"), bold, font, bg))
        js.append("[" + ", ".join(rr) + "]")
    return (
        "<Table style={{ width: '100%%', height: '100%%' }} "
        "defaultTextStyle={{ fontSize: %d, textAlign: 'left', color: '%s' }} "
        "defaultCellStyle={{ padding: %d, border: { left: { width: 1, color: '%s' }, "
        "right: { width: 1, color: '%s' }, top: { width: 1, color: '%s' }, "
        "bottom: { width: 1, color: '%s' } } }} cells={[%s]} />"
        % (font, TEXT, pad, LINE, LINE, LINE, LINE, ",\n        ".join(js))
    )


# =========================================================
# SVG 结构图组件
# =========================================================
def svg(w, h, inner, vb=None):
    vb = vb or ("0 0 %d %d" % (w, h))
    return "<svg width={%d} height={%d} viewBox='%s'>%s</svg>" % (w, h, vb, inner)


def _txt(x, y, s, size=16, fill=TEXT, anchor="middle", weight=400):
    return ("<text x='%s' y='%s' font-size='%d' fill='%s' text-anchor='%s' font-weight='%d'>%s</text>"
            % (x, y, size, fill, anchor, weight, esc(s)))


def svg_chain(items, w=1140, h=300, box_w=None, box_h=88, accent=None):
    """横向链式流程，带箭头"""
    n = len(items)
    gap = 46
    bw = box_w or int((w - gap * (n - 1)) / n)
    out = []
    x = 0
    for i, it in enumerate(items):
        label = it[0] if isinstance(it, tuple) else it
        sub = it[1] if isinstance(it, tuple) else ""
        fill = "#FFFFFF"
        stroke = accent or BLUE
        if i == 0:
            fill = NAVY
            tc = "#FFFFFF"
            stc = MUTE
        elif i == n - 1:
            fill = SURF
            tc = NAVY
            stc = TEXT
        else:
            tc = NAVY
            stc = TEXT
        out.append("<rect x='%d' y='%d' width='%d' height='%d' rx='8' fill='%s' stroke='%s' stroke-width='1.5'/>"
                   % (x, 40, bw, box_h, fill, stroke))
        out.append(_txt(x + bw / 2, 40 + box_h / 2 - (6 if sub else 0), label, 20, tc if i == 0 else tc, "middle", 600))
        if sub:
            out.append(_txt(x + bw / 2, 40 + box_h / 2 + 20, sub, 15, "#FFFFFF" if i == 0 else MUTE))
        if i < n - 1:
            ax = x + bw + 6
            out.append("<line x1='%d' y1='%d' x2='%d' y2='%d' stroke='%s' stroke-width='2'/>"
                       % (ax, 40 + box_h / 2, ax + gap - 20, 40 + box_h / 2, BLUE))
            out.append("<path d='M%d %d l10 -6 l0 12 z' fill='%s'/>"
                       % (ax + gap - 20, 40 + box_h / 2 - 6, BLUE))
        x += bw + gap
    return svg(w, h, "".join(out))


def svg_stack(layers, w=1140, h=340, colors=None):
    """纵向分层塔"""
    n = len(layers)
    colors = colors or [NAVY, "#1B4E8C", BLUE, "#4FA3E3", "#9FD0F5"]
    gap = 12
    lh = int((h - gap * (n - 1)) / n)
    out = []
    for i, it in enumerate(layers):
        label = it[0] if isinstance(it, tuple) else it
        sub = it[1] if isinstance(it, tuple) else ""
        y = i * (lh + gap)
        c = colors[i % len(colors)]
        out.append("<rect x='0' y='%d' width='%d' height='%d' rx='8' fill='%s'/>" % (y, w, lh, c))
        lum = i >= 3
        tc = NAVY if lum else "#FFFFFF"
        sc = TEXT if lum else "#C8DCF2"
        if sub:
            out.append(_txt(w / 2, y + lh / 2 - 6, label, 22, tc, "middle", 600))
            out.append(_txt(w / 2, y + lh / 2 + 20, sub, 15, sc))
        else:
            out.append(_txt(w / 2, y + lh / 2 + 7, label, 22, tc, "middle", 600))
        if i < n - 1:
            out.append("<path d='M%d %d l8 8 l-8 8' fill='none' stroke='%s' stroke-width='2'/>"
                       % (w / 2 - 8, y + lh + 1, TEAL))
    return svg(w, h, "".join(out))


def svg_loop(steps, w=760, h=430, center=""):
    """环形闭环，steps 为 6-8 个节点"""
    import math
    n = len(steps)
    cx, cy, r = w / 2, h / 2, min(w, h) / 2 - 78
    out = ["<circle cx='%d' cy='%d' r='%d' fill='none' stroke='%s' stroke-width='2' stroke-dasharray='6 6'/>"
           % (cx, cy, r, LINE)]
    for i in range(n):
        a = -math.pi / 2 + 2 * math.pi * i / n
        x = cx + r * math.cos(a)
        y = cy + r * math.sin(a)
        a2 = -math.pi / 2 + 2 * math.pi * (i + 1) / n
        x2 = cx + r * math.cos(a2)
        y2 = cy + r * math.sin(a2)
        mx, my = (x + x2) / 2, (y + y2) / 2
        out.append("<path d='M%0.1f %0.1f Q%0.1f %0.1f %0.1f %0.1f' fill='none' stroke='%s' stroke-width='2'/>"
                   % (x, y, (mx - cx) * 1.16 + cx, (my - cy) * 1.16 + cy, x2, y2, BLUE))
    for i, s in enumerate(steps):
        a = -math.pi / 2 + 2 * math.pi * i / n
        x = cx + r * math.cos(a)
        y = cy + r * math.sin(a)
        bw2, bh2 = 132, 56
        out.append("<rect x='%0.1f' y='%0.1f' width='%d' height='%d' rx='8' fill='#FFFFFF' stroke='%s' stroke-width='1.5'/>"
                   % (x - bw2 / 2, y - bh2 / 2, bw2, bh2, BLUE))
        out.append("<circle cx='%0.1f' cy='%0.1f' r='14' fill='%s'/>" % (x - bw2 / 2, y - bh2 / 2, NAVY))
        out.append(_txt(x - bw2 / 2, y - bh2 / 2 + 5, str(i + 1), 15, "#FFFFFF", "middle", 700))
        out.append(_txt(x + 6, y + 5, s, 16, NAVY, "middle", 600))
    if center:
        out.append("<circle cx='%d' cy='%d' r='72' fill='%s'/>" % (cx, cy, NAVY))
        out.append(_txt(cx, cy + 6, center, 17, "#FFFFFF", "middle", 600))
    return svg(w, h, "".join(out))


def svg_pipe(steps, w=1140, h=300, cols=None):
    """纵向多列步骤管（横向排列的编号步骤，带底部回退箭头）"""
    n = len(steps)
    gap = 18
    bw = int((w - gap * (n - 1)) / n)
    out = []
    for i, it in enumerate(steps):
        label = it[0] if isinstance(it, tuple) else it
        sub = it[1] if isinstance(it, tuple) else ""
        x = i * (bw + gap)
        out.append("<rect x='%d' y='30' width='%d' height='150' rx='8' fill='#FFFFFF' stroke='%s' stroke-width='1.5'/>"
                   % (x, bw, BLUE))
        out.append("<rect x='%d' y='30' width='%d' height='6' rx='3' fill='%s'/>" % (x, bw, NAVY))
        out.append("<circle cx='%d' cy='%d' r='16' fill='%s'/>" % (x + 26, 66, BLUE))
        out.append(_txt(x + 26, 72, str(i + 1), 16, "#FFFFFF", "middle", 700))
        out.append(_txt(x + bw / 2, 116, label, 18, NAVY, "middle", 600))
        if sub:
            out.append(_txt(x + bw / 2, 146, sub, 14, MUTE))
        if i < n - 1:
            out.append("<path d='M%d 105 l14 0' stroke='%s' stroke-width='2'/>" % (x + bw + 1, BLUE))
            out.append("<path d='M%d 105 l-7 -5 l0 10 z' fill='%s'/>" % (x + bw + 15, BLUE))
    # 回退箭头
    out.append("<path d='M40 200 L%d 200' stroke='%s' stroke-width='2' stroke-dasharray='5 5'/>"
               % (w - 40, TEAL))
    out.append("<path d='M40 200 l10 -6 l0 12 z' fill='%s'/>" % TEAL)
    out.append(_txt(w / 2, 226, "阶段之间可回退：变式暴露某步不会 → 返回该步训练", 15, TEAL, "middle", 600))
    return svg(w, h, "".join(out))


def svg_compare(left, right, w=1140, h=300, ltitle="", rtitle=""):
    """左右双栏对比"""
    gap = 30
    bw = int((w - gap) / 2)
    out = []
    out.append("<rect x='0' y='0' width='%d' height='%d' rx='8' fill='%s'/>" % (bw, h, SURF))
    out.append("<rect x='%d' y='0' width='%d' height='%d' rx='8' fill='%s'/>"
               % (bw + gap, bw, h, "#EAF3FD"))
    if ltitle:
        out.append(_txt(bw / 2, 34, ltitle, 20, NAVY, "middle", 700))
    if rtitle:
        out.append(_txt(bw + gap + bw / 2, 34, rtitle, 20, BLUE, "middle", 700))
    y0 = 62
    for i, s in enumerate(left):
        out.append("<circle cx='28' cy='%d' r='4' fill='%s'/>" % (y0 + 6 + i * 34, NAVY))
        out.append(_txt(44, y0 + 12 + i * 34, s, 16, TEXT, "start"))
    for i, s in enumerate(right):
        out.append("<circle cx='%d' cy='%d' r='4' fill='%s'/>" % (bw + gap + 28, y0 + 6 + i * 34, BLUE))
        out.append(_txt(bw + gap + 44, y0 + 12 + i * 34, s, 16, TEXT, "start"))
    return svg(w, h, "".join(out))


def svg_mock(rows, label, w=620, h=400):
    """界面线框示意图：rows = [ (kind, text) ] kind: bar|box|line|area|btn"""
    out = ["<rect x='0' y='0' width='%d' height='%d' rx='8' fill='#FFFFFF' stroke='%s' stroke-width='1.5'/>" % (w, h, LINE),
           "<rect x='0' y='0' width='%d' height='40' rx='8' fill='%s'/>" % (w, NAVY),
           "<rect x='0' y='26' width='%d' height='14' fill='%s'/>" % (w, NAVY),
           _txt(16, 26, "StudyAgent", 15, "#FFFFFF", "start", 600)]
    y = 58
    for kind, txt in rows:
        if kind == "bar":
            out.append("<rect x='18' y='%d' width='%d' height='26' rx='4' fill='%s'/>" % (y, w - 36, SURF))
            out.append(_txt(30, y + 18, txt, 14, NAVY, "start", 600))
            y += 34
        elif kind == "box":
            out.append("<rect x='18' y='%d' width='%d' height='52' rx='6' fill='#FFFFFF' stroke='%s' stroke-width='1' stroke-dasharray='4 4'/>"
                       % (y, w - 36, MUTE))
            out.append(_txt(30, y + 32, txt, 14, TEXT, "start"))
            y += 60
        elif kind == "area":
            hgt = txt[1]
            out.append("<rect x='18' y='%d' width='%d' height='%d' rx='6' fill='%s' stroke='%s' stroke-width='1' stroke-dasharray='5 4'/>"
                       % (y, w - 36, hgt, SURF, MUTE))
            out.append(_txt(w / 2, y + 22, txt[0], 15, MUTE, "middle", 600))
            n_lines = max(1, (hgt - 46) // 30)
            for k in range(n_lines):
                ly = y + 44 + k * 30
                lw = (w - 36) - 56 - (k % 3) * 70
                out.append("<rect x='40' y='%d' width='%d' height='9' rx='4' fill='%s'/>"
                           % (ly, lw, "#DFE6EF" if k % 2 == 0 else "#E9EFF6"))
                out.append("<rect x='%d' y='%d' width='46' height='9' rx='4' fill='%s'/>"
                           % (w - 78, ly, "#CBD8E8"))
            y += hgt + 12
        elif kind == "line":
            out.append("<rect x='18' y='%d' width='%d' height='10' rx='5' fill='%s'/>" % (y, w - 120, LINE))
            out.append("<rect x='%d' y='%d' width='60' height='10' rx='5' fill='%s'/>" % (w - 96, y, "#D8E6F7"))
            y += 20
        elif kind == "btn":
            out.append("<rect x='18' y='%d' width='%d' height='34' rx='17' fill='%s'/>" % (y, w - 36, BLUE))
            out.append(_txt(w / 2, y + 23, txt, 15, "#FFFFFF", "middle", 600))
            y += 44
        elif kind == "tag":
            out.append("<rect x='18' y='%d' width='%d' height='28' rx='14' fill='%s'/>" % (y, w - 36, "#EAF3FD"))
            out.append(_txt(30, y + 19, txt, 14, BLUE, "start", 600))
            y += 36
    out.append(_txt(w - 12, h - 10, label, 12, MUTE, "end"))
    return svg(w, h, "".join(out), vb="0 0 %d %d" % (w, h))


def svg_matrix(cols, cells, w=1140, h=320):
    """网格矩阵，cells 为 n*m 文本，cols 为表头"""
    rows = list(range(len(cells)))
    cw = int((w - 10) / len(cols))
    ch = int((h - 40) / len(rows))
    out = []
    for j, c in enumerate(cols):
        out.append("<rect x='%d' y='0' width='%d' height='36' fill='%s'/>" % (j * cw, cw, NAVY))
        out.append(_txt(j * cw + cw / 2, 24, c, 16, "#FFFFFF", "middle", 600))
    for i in range(len(rows)):
        for j in range(len(cols)):
            v = cells[i][j]
            x = j * cw
            y = 36 + i * ch
            bg = "#FFFFFF" if i % 2 == 0 else SURF
            out.append("<rect x='%d' y='%d' width='%d' height='%d' fill='%s' stroke='%s' stroke-width='1'/>"
                       % (x, y, cw, ch, bg, LINE))
            fs = 15 if len(v) > 20 else 17
            out.append(_txt(x + cw / 2, y + ch / 2 + 5, v, fs, NAVY if j == 0 else TEXT, "middle", 600 if j == 0 else 400))
    return svg(w, h, "".join(out))


def svg_bars(items, w=1140, h=300, unit="", color=BLUE):
    """横向条形图 items=[(label, value, max)]"""
    n = len(items)
    lh = int(h / n)
    bw = w - 300
    out = []
    for i, (lab, val, mx) in enumerate(items):
        y = i * lh + 12
        out.append(_txt(0, y + 22, lab, 16, NAVY, "start", 600))
        wpx = int(bw * val / mx)
        out.append("<rect x='230' y='%d' width='%d' height='%d' rx='4' fill='%s'/>"
                   % (y, wpx, lh - 34, color))
        out.append("<rect x='230' y='%d' width='%d' height='%d' rx='4' fill='%s' opacity='0.25'/>"
                   % (y, bw, lh - 34, LINE))
        out.append("<rect x='230' y='%d' width='%d' height='%d' rx='4' fill='%s'/>"
                   % (y, wpx, lh - 34, color))
        out.append(_txt(230 + bw + 16, y + 22, "%s%s" % (val, unit), 17, NAVY, "start", 700))
    return svg(w, h, "".join(out))


def svg_donut(parts, w=420, h=340, center_top="", center_sub=""):
    """环形占比图 parts=[(label, pct, color)]"""
    import math
    cx, cy, r = w / 2, h / 2 - 6, 108
    out = []
    start = -90.0
    for lab, pct, col in parts:
        ang = pct * 3.6
        end = start + ang
        a1 = math.radians(start)
        a2 = math.radians(end)
        x1 = cx + r * math.cos(a1); y1 = cy + r * math.sin(a1)
        x2 = cx + r * math.cos(a2); y2 = cy + r * math.sin(a2)
        large = 1 if ang > 180 else 0
        out.append("<path d='M%0.1f %0.1f A%d %d 0 %d 1 %0.1f %0.1f' fill='none' stroke='%s' stroke-width='34'/>"
                   % (x1, y1, r, r, large, x2, y2, col))
        ml = math.radians(start + ang / 2)
        lx = cx + (r + 44) * math.cos(ml); ly = cy + (r + 44) * math.sin(ml)
        out.append(_txt(lx, ly + 4, "%s %d%%" % (lab, pct), 15, TEXT, "middle", 600))
        start = end
    if center_top:
        out.append(_txt(cx, cy - 2, center_top, 30, NAVY, "middle", 700))
    if center_sub:
        out.append(_txt(cx, cy + 26, center_sub, 15, MUTE, "middle"))
    return svg(w, h, "".join(out))


def svg_funnel(steps, w=1140, h=320):
    n = len(steps)
    lh = int((h - 20) / n)
    out = []
    for i, s in enumerate(steps):
        inset = i * 62
        y = i * lh + 6
        out.append("<rect x='%d' y='%d' width='%d' height='%d' rx='6' fill='%s' opacity='%0.2f'/>"
                   % (inset, y, w - inset * 2, lh - 10, BLUE, 1 - i * 0.13))
        out.append("<rect x='%d' y='%d' width='%d' height='3' fill='%s'/>" % (inset, y, w - inset * 2, BLUE))
        out.append(_txt(w / 2, y + (lh - 10) / 2 + 6, s, 18, NAVY, "middle", 600))
        if i < n - 1:
            out.append("<path d='M%d %d l0 8' stroke='%s' stroke-width='2'/>" % (w / 2, y + lh - 8, TEAL))
    return svg(w, h, "".join(out))


def svg_timeline(items, w=1140, h=260):
    n = len(items)
    seg = int(w / n)
    out = ["<line x1='20' y1='110' x2='%d' y2='110' stroke='%s' stroke-width='3'/>" % (w - 20, LINE)]
    for i, it in enumerate(items):
        lab = it[0] if isinstance(it, tuple) else it
        sub = it[1] if isinstance(it, tuple) else ""
        x = 20 + seg * i + seg / 2
        out.append("<circle cx='%d' cy='110' r='12' fill='%s'/>" % (x, BLUE))
        out.append(_txt(x, 112, str(i + 1), 13, "#FFFFFF", "middle", 700))
        up = i % 2 == 0
        ty = 74 if up else 160
        out.append("<line x1='%d' y1='%d' x2='%d' y2='%d' stroke='%s' stroke-width='1'/>"
                   % (x, 110 + (-22 if up else 22), x, ty + (16 if up else -26), LINE))
        out.append(_txt(x, ty - 12, lab, 17, NAVY, "middle", 600))
        if sub:
            out.append(_txt(x, ty + 12, sub, 14, MUTE, "middle"))
    return svg(w, h, "".join(out))


def svg_tree(nodes, w=1140, h=320, links=None):
    """nodes: [(x_center_ratio, y, label, kind)] kind: root|node|leaf
    links: [(xr1, y1, xr2, y2)] 连线，坐标为比例与像素"""
    out = []
    for xr1, y1, xr2, y2 in (links or []):
        out.append("<line x1='%0.1f' y1='%d' x2='%0.1f' y2='%d' stroke='%s' stroke-width='2'/>"
                   % (w * xr1, y1, w * xr2, y2, BLUE))
    for xr, y, lab, kind in nodes:
        x = w * xr
        if kind == "root":
            out.append("<rect x='%0.1f' y='%d' width='220' height='56' rx='8' fill='%s'/>" % (x - 110, y, NAVY))
            out.append(_txt(x, y + 35, lab, 18, "#FFFFFF", "middle", 700))
        elif kind == "node":
            out.append("<rect x='%0.1f' y='%d' width='200' height='52' rx='8' fill='#FFFFFF' stroke='%s' stroke-width='1.5'/>"
                       % (x - 100, y, BLUE))
            out.append(_txt(x, y + 32, lab, 16, NAVY, "middle", 600))
        else:
            out.append("<rect x='%0.1f' y='%d' width='186' height='48' rx='8' fill='%s'/>" % (x - 93, y, SURF))
            out.append(_txt(x, y + 30, lab, 15, TEXT, "middle", 400))
    return svg(w, h, "".join(out))


def svg_arrow_link(x1, y1, x2, y2, w=1140, h=320, color=LINE):
    return svg(w, h, "<path d='M%d %d L%d %d' stroke='%s' stroke-width='2' fill='none'/>" % (x1, y1, x2, y2, color))


# =========================================================
# 版式组合
# =========================================================
def layout_figure(svg_html, insights, fig_w=700, gap=28, insight_title="要点"):
    """左图右要点"""
    return (
        "<Box style={{ flexDirection: 'row', gap: %d, flex: 1 }}>" % gap
        + "<Box style={{ width: %d, justifyContent: 'center' }}>%s</Box>" % (fig_w, svg_html)
        + "<Box style={{ flex: 1, flexDirection: 'column', gap: 11, justifyContent: 'center' }}>"
        + t(insight_title, 21, NAVY, 700, 1.4)
        + bullets(insights, 17, gap=10)
        + "</Box></Box>"
    )


def layout_figure_full(svg_html, notes=None, gap=16):
    n = ""
    if notes:
        n = callout(notes, BLUE)
    return ("<Box style={{ flexDirection: 'column', gap: %d, flex: 1, justifyContent: 'center' }}>"
            % gap + svg_html + n + "</Box>")


def layout_table(cells, lead=None, font=17, note=None, pad=10):
    lead_html = ""
    if lead:
        lead_html = "<Box style={{ marginBottom: 14 }}>" + callout(lead, NAVY) + "</Box>"
    note_html = ""
    if note:
        note_html = "<Box style={{ marginTop: 14 }}>" + callout(note, TEAL, SURF, 17) + "</Box>"
    return ("<Box style={{ flexDirection: 'column', flex: 1, paddingTop: 4 }}>"
            + lead_html
            + "<Box style={{ flex: 1 }}>" + table(cells, font=font, pad=pad) + "</Box>" + note_html + "</Box>")


def layout_cards(rows, lead=None, title_size=24, body_size=19):
    lead_html = ""
    if lead:
        lead_html = "<Box style={{ marginBottom: 16 }}>" + callout(lead, NAVY) + "</Box>"
    return ("<Box style={{ flexDirection: 'column', flex: 1 }}>"
            + lead_html + kv_cards(rows, title_size=title_size, body_size=body_size) + "</Box>")


def layout_mock(svg_html, points, note="示意占位 · 待替换为实际截图"):
    return (
        "<Box style={{ flexDirection: 'row', gap: 28, flex: 1 }}>"
        "<Box style={{ width: 620, justifyContent: 'center' }}>%s</Box>" % svg_html
        + "<Box style={{ flex: 1, flexDirection: 'column', gap: 10, justifyContent: 'center' }}>"
        + t("界面要点", 21, NAVY, 700, 1.4)
        + bullets(points, 16, gap=9)
        + "<Box style={{ marginTop: 6, padding: '9px 14px', background: '%s', borderRadius: 6, "
          "alignSelf: 'flex-start' }}>" % SURF
        + t(note, 14, MUTE, 600, 1.4) + "</Box>"
        + "</Box></Box>"
    )


def kv_grid(rows, per_row=3, gap=18, title_size=24, body_size=19):
    """多行卡片网格"""
    chunks = [rows[i:i + per_row] for i in range(0, len(rows), per_row)]
    return ("<Box style={{ flexDirection: 'column', gap: %d, flex: 1 }}>" % gap
            + "".join([kv_cards(c, 20, title_size, body_size) for c in chunks]) + "</Box>")


def layout_stat(numbers, note=None):
    """numbers: [(num, unit, desc)] 巨型数字横排"""
    n = len(numbers)
    w = (1140 - 20 * (n - 1)) // n
    items = []
    for num, unit, desc in numbers:
        items.append(
            card(w, "<Box style={{ flexDirection: 'row', alignItems: 'baseline', gap: 8 }}>"
                 + t(num, 64, BLUE, 700, 1.0, extra="fontFamily: 'JetBrains Mono, Inter'")
                 + t(unit, 22, MUTE, 600, 1.2) + "</Box>"
                 + t(desc, 18, TEXT, 400, 1.55), top_bar=True))
    out = cards_row(items, 20)
    if note:
        return "<Box style={{ flexDirection: 'column', gap: 18, justifyContent: 'center', flex: 1 }}>" + out + callout(note) + "</Box>"
    return "<Box style={{ justifyContent: 'center', flex: 1 }}>" + out + "</Box>"


# =========================================================
# 特殊页：封面 / 目录 / 章节 / 结束
# =========================================================
def cover(title, subtitle, meta, kicker):
    grid = []
    for i in range(9):
        grid.append("<line x1='%d' y1='0' x2='%d' y2='720' stroke='%s' stroke-width='1' opacity='0.5'/>"
                    % (i * 90, i * 90, LINE))
    for i in range(9):
        grid.append("<line x1='0' y1='%d' x2='1280' y2='%d' stroke='%s' stroke-width='1' opacity='0.5'/>"
                    % (i * 90, i * 90, LINE))
    grid.append("<circle cx='1140' cy='150' r='150' fill='none' stroke='%s' stroke-width='2' opacity='0.5'/>" % BLUE)
    grid.append("<circle cx='1140' cy='150' r='96' fill='none' stroke='%s' stroke-width='2' opacity='0.5'/>" % TEAL)
    grid.append("<circle cx='1140' cy='150' r='46' fill='%s' opacity='0.10'/>" % BLUE)
    grid.append("<line x1='700' y1='470' x2='1280' y2='470' stroke='%s' stroke-width='1' opacity='0.6'/>" % LINE)
    grid.append("<line x1='700' y1='560' x2='1280' y2='560' stroke='%s' stroke-width='1' opacity='0.6'/>" % LINE)
    chips = "".join([
        "<Box style={{ flex: 1, background: '%s', borderTop: '3px solid %s', borderRadius: 6, padding: '14px 18px' }}>"
        % (SURF, BLUE) + t(c[0], 30, NAVY, 700, 1.1) + t(c[1], 15, MUTE, 400, 1.4) + "</Box>"
        for c in [("329", "课时"), ("541", "三级知识点"), ("359", "二级步骤"), ("1019", "套路目录")]])
    return (
        "<Slide style={{ width: '1280px', height: '720px', background: '#FFFFFF', padding: 0 }}>"
        "<Box style={{ position: 'absolute', top: 0, left: 0 }}>"
        + svg(1280, 720, "".join(grid)) + "</Box>"
        "<Box style={{ position: 'relative', padding: '74px 80px 60px', flexDirection: 'column', gap: 16, zIndex: 2, flex: 1 }}>"
        "<Box style={{ width: 92, height: 5, background: 'linear-gradient(90deg, %s 0%%, %s 100%%)' }} />" % (BLUE, TEAL)
        + t(kicker, 18, BLUE, 600, 1.4, extra="letterSpacing: 2")
        + t(title, 62, NAVY, 700, 1.15)
        + t(subtitle, 25, TEXT, 400, 1.5)
        + "<Box style={{ marginTop: 18, flexDirection: 'column', gap: 6 }}>"
        + "".join([t(m, 16, MUTE, 400, 1.6) for m in meta])
        + "</Box>"
        + "<Box style={{ marginTop: 'auto', flexDirection: 'row', gap: 18 }}>" + chips + "</Box>"
        + "</Box>"
        + "<Box style={{ position: 'absolute', left: 700, top: 292, width: 420, zIndex: 3, "
          "background: '#FFFFFF', border: '1px solid %s', borderRadius: 8, padding: '16px 18px', "
          "flexDirection: 'column', gap: 10 }}>" % LINE
        + t("本次汇报的六幕结构", 18, NAVY, 700, 1.4)
        + "".join([
            "<Box style={{ flexDirection: 'row', gap: 10 }}>"
            + "".join(["<Box style={{ width: 182, background: '%s', borderRadius: 6, padding: '9px 10px' }}>" % SURF
                       + t(c, 14, NAVY, 600, 1.4) + "</Box>" for c in pair])
            + "</Box>"
            for pair in [["一 · 概念地基", "二 · 现状与引擎"],
                         ["三 · 三端与场景", "四 · 协同与接入"],
                         ["五 · 边界与演进", "六 · 自进化与收尾"]]])
        + "<Box style={{ borderTop: '1px solid %s', paddingTop: 9 }}>" % LINE
        + t("每页标注实现状态与来源文档，可逐页回溯", 13, MUTE, 400, 1.5) + "</Box>"
        + "</Box></Slide>"
    )


def chapter(num, name, keywords, src_note):
    grid = []
    for i in range(9):
        grid.append("<line x1='0' y1='%d' x2='1280' y2='%d' stroke='%s' stroke-width='1' opacity='0.55'/>"
                    % (i * 90, i * 90, LINE))
    all_ch = [("01", "概念地基"), ("02", "现状盘点"), ("03", "单题引擎"), ("04", "套路层面"),
              ("05", "教师端"), ("06", "学校端"), ("07", "试卷与生涯"), ("08", "协同 Agent"),
              ("09", "MCP 接入"), ("10", "待深化研究"), ("11", "落地与边界"),
              ("12", "自进化与扩展"), ("13", "收尾")]
    def _cell(code, cname, w=172):
        on = (code == num)
        return ("<Box style={{ width: %d, height: 64, borderRadius: 6, padding: '9px 12px', "
                "background: '%s', flexDirection: 'column', justifyContent: 'center' }}>" % (w, NAVY if on else SURF)
                + t(code, 18, "#FFFFFF" if on else NAVY, 700, 1.2)
                + t(cname, 13, "#C8DCF2" if on else MUTE, 400, 1.3) + "</Box>")

    rows_html = []
    for r in range(0, len(all_ch), 3):
        items = all_ch[r:r + 3]
        rows_html.append("<Box style={{ flexDirection: 'row', gap: 10 }}>"
                         + "".join([_cell(c, n) for c, n in items]) + "</Box>")
    right_extra = ("<Box style={{ flexDirection: 'row', alignItems: 'center', gap: 12, "
                   "borderTop: '1px solid %s', paddingTop: 14 }}>" % LINE
                   + "<Box style={{ width: 46, height: 5, background: '%s' }} />" % TEAL
                   + t("StudyAgent 项目设计汇报 · 技术评审版 · 共 124 页", 15, MUTE, 600, 1.4) + "</Box>")
    return (
        "<Slide style={{ width: '1280px', height: '720px', background: '#FFFFFF', padding: 0 }}>"
        "<Box style={{ position: 'absolute', top: 0, left: 0 }}>" + svg(1280, 720, "".join(grid)) + "</Box>"
        "<Box style={{ position: 'relative', zIndex: 2, flexDirection: 'row', flex: 1, padding: '48px 80px 52px', gap: 44 }}>"
        "<Box style={{ width: 520, flexDirection: 'column', justifyContent: 'space-between' }}>"
        "<Box style={{ flexDirection: 'column' }}>"
        + t("STUDYAGENT · DESIGN REVIEW", 15, BLUE, 600, 1.4, extra="letterSpacing: 2")
        + "</Box>"
        "<Box style={{ flexDirection: 'column' }}>"
        + t(num, 100, NAVY, 700, 1.0, extra="fontFamily: 'JetBrains Mono, Inter'")
        + "<Box style={{ width: 78, height: 5, background: '%s', marginTop: 10 }} />" % BLUE
        + t(name, 44, NAVY, 700, 1.25)
        + "</Box>"
        "<Box style={{ flexDirection: 'column', gap: 12 }}>"
        + "".join([callout(k, BLUE, SURF, 19) for k in keywords])
        + "</Box>"
        "<Box style={{ flexDirection: 'column' }}>" + t(src_note, 13, MUTE, 400, 1.5) + "</Box>"
        + "</Box>"
        + "<Box style={{ flex: 1, flexDirection: 'column', justifyContent: 'space-between', gap: 12 }}>"
        + t("汇报结构 · 13 章", 20, NAVY, 700, 1.4)
        + "<Box style={{ flexDirection: 'column', gap: 10 }}>" + "".join(rows_html) + "</Box>"
        + "<Box style={{ flexDirection: 'row', alignItems: 'center', gap: 10, background: '%s', "
          "borderRadius: 6, padding: '10px 14px' }}>" % SURF
        + "<Box style={{ width: 6, height: 22, background: '%s' }} />" % TEAL
        + t("当前位置：第 %s 章 · %s" % (num, name), 15, NAVY, 600, 1.4) + "</Box>"
        + "<Box style={{ flexDirection: 'row', gap: 10 }}>"
        + "".join(["<Box style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8, "
                   "borderRadius: 6, padding: '9px 10px', background: '%s' }}>" % SURF
                   + "<Box style={{ width: 10, height: 10, borderRadius: 5, background: '%s' }} />" % col
                   + t(lb, 14, TEXT, 600, 1.3) + "</Box>"
                   for lb, col in [("已实现", "#1E9E62"), ("部分实现", "#E8A33D"),
                                   ("设计中", "#1E7BE0"), ("待研究", "#98A2B3")]])
        + "</Box>"
        + right_extra
        + "</Box></Box></Slide>"
    )


def closing(title, lines, footnote, chips=None):
    chips = chips or [("12", "份设计文档"), ("124", "页汇报"), ("4", "类实现状态"), ("3", "条贯穿金句")]
    chip_html = "".join([
        "<Box style={{ flex: 1, background: 'rgba(255,255,255,0.06)', borderTop: '3px solid %s', "
        "borderRadius: 6, padding: '16px 18px' }}>" % TEAL
        + t(c[0], 34, "#FFFFFF", 700, 1.1)
        + t(c[1], 14, "#9CC2E8", 400, 1.4) + "</Box>" for c in chips])
    return (
        "<Slide style={{ width: '1280px', height: '720px', background: '%s', padding: '70px 80px 60px' }}>" % NAVY
        + "<Box style={{ flexDirection: 'column', gap: 20, flex: 1 }}>"
        + "<Box style={{ width: 92, height: 5, background: '%s' }} />" % TEAL
        + t(title, 48, "#FFFFFF", 700, 1.25)
        + "".join([t(x, 21, "#C8DCF2", 400, 1.7) for x in lines])
        + "<Box style={{ marginTop: 'auto', flexDirection: 'column', gap: 18 }}>"
        + "<Box style={{ flexDirection: 'row', gap: 18 }}>" + chip_html + "</Box>"
        + "<Box style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', "
          "borderTop: '1px solid rgba(255,255,255,0.15)', paddingTop: 14 }}>"
        + t(footnote, 15, "#7FA8D8", 400, 1.4)
        + t("Q & A", 16, "#FFFFFF", 700, 1.4) + "</Box>"
        + "</Box></Box></Slide>"
    )

# 允许 from gen import * 带出下划线工具函数
__all__ = [k for k in list(globals().keys()) if not k.startswith("__")]
