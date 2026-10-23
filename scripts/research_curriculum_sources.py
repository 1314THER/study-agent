"""Preserve public curriculum evidence; never treats a catalogue as read exercises."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import gzip
from pathlib import Path
import re
import urllib.request
from urllib.parse import quote,urljoin

URLS = {
    'tesoon-ebooks': 'https://www.tesoon.com/customize/ebook',
    'tesoon-methods': 'https://www.tesoon.com/articles/detail?id=180886',
    'quyixian-sync': 'https://www.quyixian.com/Book/WSGZTB/',
    'quyixian-manual': 'https://mobile.quyixian.com/ProductManual/',
    'textbook-mirror-index': 'https://api.github.com/repos/litongjava/china_high_school_math_people_teach_a_version_pdf/git/trees/main?recursive=1',
    'textbook-directory-index': 'https://www.renjiaoshe.com/renjiaoshuxue/',
}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='.runtime/curriculum-wiki/evidence')
    parser.add_argument('--textbooks', action='store_true')
    parser.add_argument('--previews', action='store_true')
    parser.add_argument('--readers', action='store_true')
    parser.add_argument('--samples', action='store_true')
    parser.add_argument('--sample-assets', action='store_true')
    args = parser.parse_args()
    root = Path(args.output); root.mkdir(parents=True, exist_ok=True)
    urls = dict(URLS)
    if args.textbooks:
        index = json.loads((root/'textbook-mirror-index.json').read_text())
        for entry in index.get('tree', []):
            path = entry['path']
            if '2019/' in path and path.endswith('.pdf'):
                key = path.split('）')[-1].removesuffix('.pdf')
                urls[key] = 'https://raw.githubusercontent.com/litongjava/china_high_school_math_people_teach_a_version_pdf/main/' + quote(path)
    if args.previews:
        html = (root/'tesoon-ebooks.html').read_text().replace('\\u002F', '/')
        for title in ('高中《教材帮》', '高中《一遍过》', '高中《解题觉醒》'):
            match = re.search('name:"'+re.escape(title)+'".*?link_url:"([^"]+)"', html)
            if match:
                urls[title] = match[1]
                urls[title+'-desktop'] = match[1].replace('://m.tesoon.com/', '://www.tesoon.com/')
    if args.readers:
        urls={}
        for title in ('高中《教材帮》','高中《一遍过》','高中《解题觉醒》'):
            html=(root/(title+'-desktop.html')).read_text().replace('\\u002F','/')
            links=re.findall('link_url:"(https://(?:mp\\.zhizhuma\\.com|mp\\.bookln\\.cn|book\\.yunzhan365\\.com)/[^"]+)"',html)
            for index,url in enumerate(links[:2]):urls[title+'-reader'+str(index)]=url
    if args.samples:
        urls={
            "ybg-2026-rja-b1-sample":"https://book.yunzhan365.com/pqks/jrhh/index.html",
            "ybg-2026-rja-b1-mobile":"https://book.yunzhan365.com/pqks/jrhh/mobile/index.html",
            "ybg-2026-rja-b1-basic":"https://book.yunzhan365.com/pqks/jrhh/files/basic-html/index.html",
        }
    if args.sample_assets:
        mobile=(root/'ybg-2026-rja-b1-mobile.html').read_text()
        match=re.search('src="(javascript/config\\.js[^"]*)"',mobile)
        if not match:raise SystemExit('No public sample configuration link found.')
        urls={"ybg-2026-rja-b1-config":urljoin("https://book.yunzhan365.com/pqks/jrhh/mobile/index.html",match[1])}
    def fetch(pair):
        key, url = pair
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'StudyAgent-CurriculumResearch/1.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read(180 * 1024 * 1024)
                final = response.url
            if data[:2] == b'\x1f\x8b':
                data = gzip.decompress(data)
            name = key + ('.pdf' if url.endswith('.pdf') else '.json' if key.startswith('textbook-mirror') else '.html')
            (root/name).write_bytes(data)
            return {'id': key, 'url': url, 'resolved_url': final, 'file': name,
                    'sha256': sha256(data).hexdigest(), 'bytes': len(data), 'status': 'retrieved',
                    'scope': '入口或目录；不代表逐题读取'}
        except Exception as exc:
            return {'id': key, 'url': url, 'status': 'failed', 'error': str(exc)[:300]}
    results = list(ThreadPoolExecutor(max_workers=4).map(fetch, urls.items()))
    manifest=root/'manifest.json'
    previous=json.loads(manifest.read_text()) if manifest.exists() else []
    by_id={r['id']:r for r in previous}
    by_id.update({r['id']:r for r in results})
    manifest.write_text(json.dumps(list(by_id.values()), ensure_ascii=False, indent=2))
    for row in results:
        print(row['id'], row['status'], row.get('bytes', row.get('error')))

if __name__ == '__main__':
    main()
