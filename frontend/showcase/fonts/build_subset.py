"""Build the local handwriting webfont from an explicitly supplied OFL font.

This optional asset-build tool needs fonttools[woff]; production only serves the
resulting WOFF2. It does not download software or inspect system fonts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import string

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parent
FAMILY = 'StudyAgent Handwriting'
OPENING = '由 A+B=3C 和 A+B+C=π，得 C=π/3。'
# These reserve the punctuation and ordinary mathematics used by the original
# responses. The renderer does not rewrite model/student text into other glyphs.
EXTRAS = '，。；：、？！“”‘’（）【】《》—…·×÷±−＝＋﹣√∑ΣπΠαβγΔθφλμω∈∉⊂⊆∪∩∞≈≠≤≥⇒⇔→←↔∴∵⊥∥°′″²³ⁿ₀₁₂₃₄₅₆₇₈₉ₙ'
SOURCE_URL = 'https://fonts.gstatic.com/s/lxgwwenkaitc/v11/w8gDH20td8wNsI3f40DmtXZb48uK.ttf'
LICENSE_URL = 'https://github.com/google/fonts/blob/main/ofl/lxgwwenkaitc/OFL.txt'


def requested_characters(recordings):
    inputs = [OPENING]
    inputs.extend(c['student_answer'] for c in recordings.get('cases', []))
    inputs.extend((f.get('input') or '') for f in recordings.get('teaching', {}).get('frames', []))
    chars = set(''.join(inputs) + string.ascii_letters + string.digits + string.punctuation + ' ' + EXTRAS)
    return {c for c in chars if not c.isspace() or c == ' '}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--license', type=Path, required=True)
    args = parser.parse_args()
    from fontTools import __version__
    from fontTools.subset import Options, Subsetter
    from fontTools.ttLib import TTFont

    records_path = ROOT/'frontend/showcase/recordings.json'
    recordings = json.loads(records_path.read_text())
    chars = requested_characters(recordings)
    font = TTFont(args.source, recalcTimestamp=False)
    available = set(font.getBestCmap())
    required = {ord(c) for c in chars}
    missing = sorted(required - available)
    if missing:
        raise SystemExit('Original font lacks requested characters: ' + ', '.join(f'U+{c:04X} {chr(c)}' for c in missing))
    options = Options()
    options.flavor = 'woff2'
    options.layout_features = ['*']
    options.name_IDs = ['*']
    options.name_legacy = True
    options.name_languages = ['*']
    options.recalc_timestamp = False
    subsetter = Subsetter(options=options)
    subsetter.populate(unicodes=required)
    subsetter.subset(font)
    # A modified subset has its own primary name. Original copyright, license
    # and attribution entries remain untouched (OFL Reserved Font Names).
    replacements = {1:FAMILY, 2:'Regular', 3:'StudyAgentHandwriting-Regular-v1',
                    4:FAMILY+' Regular', 6:'StudyAgentHandwriting-Regular',
                    16:FAMILY, 17:'Regular', 18:FAMILY+' Regular'}
    table = font['name']
    for record in table.names:
        if record.nameID in replacements:
            table.setName(replacements[record.nameID], record.nameID, record.platformID,
                          record.platEncID, record.langID)
    for identifier, value in replacements.items():
        table.setName(value, identifier, 3, 1, 0x409)
    font.flavor = 'woff2'
    destination = OUTPUT/'studyagent-handwriting.woff2'
    font.save(destination)
    check = TTFont(destination)
    covered = sorted(check.getBestCmap())
    assert required <= set(covered), 'Serialized WOFF2 dropped requested characters'
    assert check['name'].getDebugName(1) == FAMILY
    license_source = args.license.read_bytes()
    license_bytes = ('\n'.join(line.rstrip() for line in license_source.decode('utf-8').splitlines()) + '\n').encode('utf-8')
    if b'SIL OPEN FONT LICENSE Version 1.1' not in license_bytes:
        raise SystemExit('Supplied source license is not the expected OFL 1.1 text')
    (OUTPUT/'OFL.txt').write_bytes(license_bytes)
    data = {'family': FAMILY, 'weight': 400, 'style': 'normal', 'format': 'woff2',
            'upstream': {'name':'LXGW WenKai TC Regular', 'version':'1.330 / Google Fonts v11',
                         'font_url':SOURCE_URL, 'license_url':LICENSE_URL,
                         'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
                         'license_source_sha256': hashlib.sha256(license_source).hexdigest()},
            'license': 'OFL-1.1', 'license_sha256':hashlib.sha256(license_bytes).hexdigest(), 'fonttools_version': __version__,
            'file': destination.name, 'bytes':destination.stat().st_size,
            'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
            'covered_codepoints':covered, 'requested_count':len(required), 'missing_codepoints':[],
            'inputs': {'cases':len(recordings.get('cases',[])),
                       'teaching_frames':len(recordings.get('teaching',{}).get('frames',[])),
                       'opening': OPENING,
                       'recordings_sha256':hashlib.sha256(records_path.read_bytes()).hexdigest()},
            'notes':'Subset includes actual six student responses, every recorded teaching input, opening text, ASCII and listed mathematical punctuation. No system fonts are redistributed.'}
    (OUTPUT/'coverage.json').write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'family':FAMILY,'bytes':data['bytes'],'characters':len(covered),'missing':missing},ensure_ascii=False))


if __name__ == '__main__':
    main()
