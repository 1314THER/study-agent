# -*- coding: utf-8 -*-
"""汇总三份页面数据，重排页码，写出 slides/NN.slide"""
import os, re, sys, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
SLIDES = os.path.join(BASE, "slides")
sys.path.insert(0, HERE)

import gen  # noqa
import pages_p1, pages_p2, pages_p3  # noqa

ALL = pages_p1.PAGES + pages_p2.PAGES + pages_p3.PAGES
TOTAL = len(ALL)
gen.TOTAL = TOTAL

out = []
for i, html in enumerate(ALL, start=1):
    # 统一重排页脚页码
    html = re.sub(r">\s*\d+\s*/\s*115\s*<", "> %d / %d <" % (i, TOTAL), html)
    out.append(html)

if not os.path.isdir(SLIDES):
    os.makedirs(SLIDES)

for i, html in enumerate(out, start=1):
    with open(os.path.join(SLIDES, "%03d.slide" % i), "w", encoding="utf-8") as fh:
        fh.write(html)

print("TOTAL_PAGES=%d" % TOTAL)
