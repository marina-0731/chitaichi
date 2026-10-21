#!/usr/bin/env python3
"""日本語の index.html から、各言語のページ（en/index.html など）を作る。

使い方（リポジトリのルートで）:
  python3 i18n/build.py extract   # 訳す文章を i18n/ja.json に書き出す
  python3 i18n/build.py build     # i18n/<言語>.json の訳文から各言語のページを作る
  python3 i18n/build.py check     # 訳が足りない文章・古くなった訳を一覧にする
  python3 i18n/build.py sitemap   # sitemap.xml だけを書き出す（build でも書き出される）

日本語のページを直したら extract → 各言語の JSON に訳を足す → build の順で更新する。
訳は「日本語の原文 → 訳文」の対応で持つので、原文が少しでも変わると、その文は訳し直しが必要になる
（build は訳がない文があると止まる）。
"""
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'index.html'
I18N = ROOT / 'i18n'
SITE = 'https://chitaichi.co.jp'

# (lang属性, フォルダ, メニューに出す名前, og:locale)
LANGS = [
    ('ja', '', '日本語', 'ja_JP'),
    ('en', 'en', 'English', 'en_GB'),
    ('zh-Hant', 'zh-hant', '繁體中文', 'zh_TW'),
    ('zh-Hans', 'zh-hans', '简体中文', 'zh_CN'),
    ('ko', 'ko', '한국어', 'ko_KR'),
    ('pt-BR', 'pt', 'Português', 'pt_BR'),
    ('vi', 'vi', 'Tiếng Việt', 'vi_VN'),
    ('fil', 'fil', 'Filipino', 'fil_PH'),
    ('fr', 'fr', 'Français', 'fr_FR'),
    ('it', 'it', 'Italiano', 'it_IT'),
    ('es', 'es', 'Español', 'es_ES'),
]
CJK = {'ja', 'zh-Hant', 'zh-Hans'}  # 地図の湾名を縦書きのままにする言語

# 言語ごとの本文フォント（Google Fonts）。None は日本語ページと同じ BIZ UDP明朝。
FONTS = {
    'zh-Hant': ("Noto+Serif+TC:wght@400;700", "'Noto Serif TC'"),
    'zh-Hans': ("Noto+Serif+SC:wght@400;700", "'Noto Serif SC'"),
    'ko': ("Noto+Serif+KR:wght@400;700", "'Noto Serif KR'"),
    'vi': ("Noto+Serif:wght@400;700&subset=vietnamese", "'Noto Serif'"),
}

JA = re.compile(r'[぀-ヿ㐀-鿿豈-﫿！-｠]')
INLINE = {'br', 'span', 'a', 'small', 'strong', 'em', 'b', 'i', 'time', 'wbr'}
VOID = {'br', 'img', 'meta', 'link', 'input', 'hr', 'wbr', 'source', 'area', 'base', 'col', 'embed', 'param', 'track'}
SKIP = {'script', 'style'}
ATTRS = ('alt', 'aria-label', 'title', 'content')


class Extractor(HTMLParser):
    """日本語を含む「文章のかたまり」と属性の位置（元のHTML上の文字位置）を集める。"""

    def __init__(self, src):
        super().__init__(convert_charrefs=False)
        self.src = src
        self.line_starts = [0]
        for m in re.finditer('\n', src):
            self.line_starts.append(m.end())
        self.stack = []      # [tag, 中身の開始位置, 子に塊タグがあるか, 翻訳しないか]
        self.blocks = []     # (開始, 終了, 原文)
        self.attrs = []      # (開始, 終了, 原文)
        self.skip_depth = 0

    def pos(self):
        line, col = self.getpos()
        return self.line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        start = self.pos()
        text = self.get_starttag_text()
        end = start + len(text)
        noi18n = any(k == 'data-noi18n' for k, _ in attrs) or (self.stack and self.stack[-1][3])
        if not noi18n and tag not in SKIP:
            for name in ATTRS:
                for m in re.finditer(r'\s%s="([^"]*)"' % re.escape(name), text):
                    if JA.search(m.group(1)):
                        self.attrs.append((start + m.start(1), start + m.end(1), m.group(1)))
        if self.stack and tag not in INLINE:
            self.stack[-1][2] = True
        if tag in VOID:
            return
        self.stack.append([tag, end, False, noi18n or tag in SKIP])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        start = self.pos()
        while self.stack:
            t, cstart, has_block, noi18n = self.stack.pop()
            if t == tag:
                inner = self.src[cstart:start]
                if not noi18n and not has_block and JA.search(re.sub(r'<[^>]+>', '', inner)):
                    self.blocks.append((cstart, start, inner))
                break


def segments(src):
    ex = Extractor(src)
    ex.feed(src)
    blocks = sorted(ex.blocks)
    # 外側の塊の中にある小さな塊（<span> だけの行など）は外側にまとめる
    keep = []
    for b in blocks:
        if keep and b[0] >= keep[-1][0] and b[1] <= keep[-1][1]:
            continue
        keep.append(b)
    # 文章の塊の中にある属性は塊ごと訳すので、外側の属性だけを残す
    attrs = [a for a in ex.attrs if not any(b[0] <= a[0] < b[1] for b in keep)]
    segs = [(s, e, t.strip(), t, 'block') for s, e, t in keep] + [(s, e, html.unescape(t), t, 'attr') for s, e, t in attrs]
    return sorted(segs)


def extract():
    src = SRC.read_text(encoding='utf-8')
    out = {}
    for _, _, key, _, _ in segments(src):
        out[key] = key
    (I18N / 'ja.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'{len(out)} 件の文章を i18n/ja.json に書き出しました')


def load(lang):
    p = I18N / f'{lang}.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}


def check():
    src = SRC.read_text(encoding='utf-8')
    keys = {k for _, _, k, _, _ in segments(src)}
    ok = True
    for lang, *_ in LANGS[1:]:
        tr = load(lang)
        missing = sorted(keys - tr.keys())
        stale = sorted(tr.keys() - keys)
        if missing or stale:
            ok = False
        print(f'{lang}: 訳なし {len(missing)} 件 / 使われていない訳 {len(stale)} 件')
        for k in missing:
            print('   - 訳なし:', k[:60].replace('\n', ' '))
    return ok


def lang_menu(cur):
    items = []
    for lang, folder, name, _ in LANGS:
        href = f'/{folder}/' if folder else '/'
        current = ' aria-current="page"' if lang == cur else ''
        items.append((lang, href, name, current))
    menu = '\n'.join(f'        <li><a href="{h}" lang="{l}" hreflang="{l}"{c}>{n}</a></li>' for l, h, n, c in items)
    nav = '\n'.join(f'          <a href="{h}" lang="{l}" hreflang="{l}"{c}>{n}</a>' for l, h, n, c in items)
    name = next(n for l, _, n, _ in LANGS if l == cur)
    return menu, nav, name


def build():
    src = SRC.read_text(encoding='utf-8')
    segs = segments(src)
    failed = False
    for lang, folder, _, locale in LANGS[1:]:
        tr = load(lang)
        missing = [k for _, _, k, _, _ in segs if k not in tr]
        if missing:
            print(f'{lang}: 訳がない文章が {len(missing)} 件あります（python3 i18n/build.py check で一覧）')
            failed = True
            continue
        out = src
        for s, e, key, raw, kind in reversed(segs):
            if kind == 'attr':
                val = html.escape(tr[key], quote=True)
            else:  # 前後の改行や字下げは原文のまま残す
                lead = raw[:len(raw) - len(raw.lstrip())]
                trail = raw[len(raw.rstrip()):]
                val = lead + tr[key] + trail
            out = out[:s] + val + out[e:]

        menu, nav, name = lang_menu(lang)
        out = re.sub(r'(<details class="lang-menu"[^>]*>.*?<ul>\n).*?(\n      </ul>)', lambda m: m.group(1) + menu + m.group(2), out, count=1, flags=re.S)
        out = re.sub(r'<span class="lang-current">[^<]*</span>', f'<span class="lang-current">{name}</span>', out, count=1)
        out = re.sub(r'(<div class="nav-langs-list">\n).*?(\n      </div>)', lambda m: m.group(1) + nav + m.group(2), out, count=1, flags=re.S)

        out = out.replace('<html lang="ja">', f'<html lang="{lang}">', 1)
        url = f'{SITE}/{folder}/'
        out = out.replace(f'<link rel="canonical" href="{SITE}/">', f'<link rel="canonical" href="{url}">', 1)
        out = out.replace(f'<meta property="og:url" content="{SITE}/">', f'<meta property="og:url" content="{url}">', 1)
        out = out.replace('<meta property="og:locale" content="ja_JP">', f'<meta property="og:locale" content="{locale}">', 1)
        out = re.sub(r'(src|href)="assets/', r'\1="../assets/', out)
        out = out.replace('url(assets/', 'url(../assets/')

        extra = []
        if lang in FONTS:
            family, name_css = FONTS[lang]
            extra.append(f"  @import url('https://fonts.googleapis.com/css2?family={family}&display=swap');")
            extra.append(f"  body{{font-family:{name_css},'BIZ UDPMincho',serif;}}")
        if lang not in CJK:
            extra.append('  .chita-map .m-sea{writing-mode:horizontal-tb;letter-spacing:0.08em;font-size:13px;}')
        if extra:
            # @import は style の先頭にしか書けないので、別の style を足す
            out = out.replace('</head>', '<style>\n' + '\n'.join(extra) + '\n</style>\n</head>', 1)

        if lang not in CJK:  # 漢字を使う言語は、漢字が残っていて当然なので調べない
            body = re.sub(r'(?s)<script.*?</script>|<style.*?</style>|<details class="lang-menu".*?</details>|<div class="nav-langs".*?</div>\s*</div>|<div class="member-name"[^>]*>.*?</div>', '', out)
            leftover = sorted(set(JA.findall(body)))
            if leftover:
                print(f'{lang}: 注意 日本語の文字が残っています: {"".join(leftover)[:40]}')
        d = ROOT / folder
        d.mkdir(exist_ok=True)
        (d / 'index.html').write_text(out, encoding='utf-8')
        print(f'{lang}: {folder}/index.html を作りました')
    if failed:
        sys.exit(1)


def sitemap():
    """全言語のページと、言語どうしの対応（hreflang）を sitemap.xml に書き出す。"""
    import datetime
    today = datetime.date.today().isoformat()
    urls = [(lang, f'{SITE}/{folder}/' if folder else f'{SITE}/') for lang, folder, _, _ in LANGS]
    alts = ''.join(f'    <xhtml:link rel="alternate" hreflang="{l}" href="{u}"/>\n' for l, u in urls)
    alts += f'    <xhtml:link rel="alternate" hreflang="x-default" href="{SITE}/"/>\n'
    body = ''.join(f'  <url>\n    <loc>{u}</loc>\n    <lastmod>{today}</lastmod>\n{alts}  </url>\n' for _, u in urls)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
           + body + '</urlset>\n')
    (ROOT / 'sitemap.xml').write_text(xml, encoding='utf-8')
    print(f'sitemap.xml に {len(urls)} ページを書き出しました')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'build'
    if cmd == 'extract':
        extract()
    elif cmd == 'check':
        sys.exit(0 if check() else 1)
    elif cmd == 'sitemap':
        sitemap()
    else:
        build()
        sitemap()
