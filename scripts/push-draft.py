#!/usr/bin/env python3
"""Markdown (.md/.mdx) -> Substack draft via the internal drafts API.

Semi-automatic by design: this script creates a DRAFT; a human opens the
returned URL in a browser, checks the rendering, and clicks Publish.

Setup (once):
    pip install markdown
    export SUBSTACK_PUB=yourname.substack.com
    export SUBSTACK_USER_ID=123456789          # numeric user id, as a string
    # cookies.txt next to this script (chmod 600, NEVER commit):
    #     substack.sid=<value from browser devtools>

Usage:
    python3 push-draft.py path/to/article.md [more.md ...]

Notes:
- Network: if substack.com is unreachable directly, set HTTPS_PROXY
  (e.g. export HTTPS_PROXY=http://127.0.0.1:7890).
- Only `substack.sid` (+ optional `substack.li`) is required in cookies.txt.
  Cloudflare tokens (__cf_bm / cf_clearance) and analytics cookies are not needed.
"""
import os
import sys
import json
import re
import urllib.request
import pathlib

import markdown

BASE = f"https://{os.environ['SUBSTACK_PUB']}"
USER_ID = os.environ['SUBSTACK_USER_ID']  # draft_bylines wants a string id
HERE = pathlib.Path(__file__).parent

# Substack editor (TipTap v2) schema whitelists — verified 2026-09.
# Anything outside these sets makes the editor fail to boot ("Something has
# gone wrong" / "this page croaked"), even though the API accepts the payload.
NODES = {
    'paragraph', 'heading', 'blockquote', 'bulletList', 'orderedList',
    'listItem', 'hardBreak', 'horizontalRule', 'codeBlock', 'text',
    'image', 'image2', 'image3', 'captionedImage', 'image_gallery',
    'pullquote', 'calloutBlock', 'collapsedContent', 'button',
    'captionedButton', 'highlighted_code_block', 'inline_latex',
    'latexBlock', 'preformatted_text_block', 'install_substack_app',
    'sponsorshipCampaign', 'dynamicContent', 'dynamicContentMatch',
    'dynamicContentElse', 'paywall', 'footnote', 'footnoteAnchor',
    'caption', 'ctaCaption', 'captionedShareButton', 'cashtag', 'mention',
    'subscribeWidget',
}
MARKS = {'bold', 'italic', 'strike', 'code', 'link'}
BLOCK_CONTAINERS = ('blockquote', 'bulletList', 'orderedList', 'listItem')


def load_cookie():
    return '; '.join(
        l.strip() for l in (HERE / 'cookies.txt').read_text().splitlines()
        if l.strip() and not l.strip().startswith('#'))


def api(method, path, cookie, payload=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        headers={'Cookie': cookie, 'User-Agent': 'Mozilla/5.0',
                 'Content-Type': 'application/json'},
        data=json.dumps(payload).encode() if payload is not None else None)
    opener = urllib.request.build_opener()
    try:
        with opener.open(req, timeout=60) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:500]


def parse_mdx(path):
    """Extract title/description from YAML frontmatter, return raw markdown body."""
    t = pathlib.Path(path).read_text(encoding='utf-8')
    fm = {}
    if t.startswith('---'):
        end = t.find('\n---', 3)
        if end != -1:
            for line in t[3:end].strip().splitlines():
                if ':' in line:
                    k, v = line.split(':', 1)
                    fm[k.strip()] = v.strip().strip('"').strip("'")
            t = t[end + 4:]
    return fm.get('title', pathlib.Path(path).stem), fm.get('description', ''), t


def smart_cut(s, n=140):
    """Substack subtitle limit; cut at a word boundary."""
    if len(s) <= n:
        return s
    cut = s[:n]
    return cut[:cut.rfind(' ')] if ' ' in cut else cut


def md_to_doc(md_text):
    """markdown -> ProseMirror doc dict matching Substack's TipTap v2 schema.

    Hard-won rules (each one was a real 'page croaked' crash):
    - node names are camelCase (codeBlock/bulletList/hardBreak/horizontalRule)
    - bare `text` nodes are NOT allowed as direct children of block containers
      (markdown -> HTML leaves newline/indent text between block tags)
    - `codeBlock` text must not carry any inline marks
    """
    html = markdown.markdown(md_text, extensions=['fenced_code', 'tables', 'nl2br'])

    from html.parser import HTMLParser

    class P(HTMLParser):
        INLINE_MARKS = {'strong': 'bold', 'b': 'bold', 'em': 'italic',
                        'i': 'italic', 'code': 'code'}

        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.doc = {'type': 'doc', 'content': []}
            self.stack = [self.doc]
            self.marks = []

        def cur(self):
            return self.stack[-1]

        def _push_text(self, data):
            if not data:
                return
            node = {'type': 'text', 'text': data}
            if self.marks:
                node['marks'] = [{'type': m} if isinstance(m, str)
                                 else {'type': m[0], 'attrs': {'href': m[1]}}
                                 for m in self.marks]
            self.cur().setdefault('content', []).append(node)

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == 'p':
                n = {'type': 'paragraph', 'attrs': {'textAlign': None}}
                self.cur().setdefault('content', []).append(n)
                self.stack.append(n)
            elif tag in ('h1', 'h2', 'h3', 'h4'):
                n = {'type': 'heading', 'attrs': {'level': int(tag[1]), 'textAlign': None}}
                self.cur().setdefault('content', []).append(n)
                self.stack.append(n)
            elif tag == 'blockquote':
                n = {'type': 'blockquote'}
                self.cur().setdefault('content', []).append(n)
                self.stack.append(n)
            elif tag in ('ul', 'ol'):
                n = {'type': 'bulletList' if tag == 'ul' else 'orderedList'}
                self.cur().setdefault('content', []).append(n)
                self.stack.append(n)
            elif tag == 'li':
                n = {'type': 'listItem'}
                self.cur().setdefault('content', []).append(n)
                self.stack.append(n)
            elif tag == 'pre':
                n = {'type': 'codeBlock', 'attrs': {'language': None}}
                self.cur().setdefault('content', []).append(n)
                self.stack.append(n)
            elif tag == 'hr':
                self.cur().setdefault('content', []).append({'type': 'horizontalRule'})
            elif tag == 'br':
                self.cur().setdefault('content', []).append({'type': 'hardBreak'})
            elif tag in self.INLINE_MARKS:
                self.marks.append(self.INLINE_MARKS[tag])
            elif tag == 'a':
                self.marks.append(('link', a.get('href')))

        def handle_endtag(self, tag):
            if tag in ('p', 'h1', 'h2', 'h3', 'h4', 'blockquote', 'ul', 'ol', 'li', 'pre'):
                if len(self.stack) > 1:
                    self.stack.pop()
            elif tag in self.INLINE_MARKS or tag == 'a':
                if self.marks:
                    self.marks.pop()

        def handle_data(self, data):
            if self.marks and isinstance(self.marks[-1], tuple):
                m, href = self.marks[-1]
                node = {'type': 'text', 'text': data,
                        'marks': [{'type': 'link', 'attrs': {'href': href}}]}
                self.cur().setdefault('content', []).append(node)
            else:
                self._push_text(data)

    p = P()
    p.feed(html)

    def clean(n, top=False):
        if isinstance(n, dict):
            for c in (n.get('content') or [])[:]:
                if c.get('type') == 'text':
                    in_block = n.get('type') in BLOCK_CONTAINERS
                    if (top or in_block) and not c.get('text', '').strip():
                        n['content'].remove(c)
                        continue
                    if not c.get('text'):
                        n['content'].remove(c)
                        continue
                    if in_block and n.get('type') == 'listItem' and c['text'].strip():
                        # bare text under listItem -> wrap in a paragraph
                        idx = n['content'].index(c)
                        n['content'][idx] = {'type': 'paragraph',
                                             'attrs': {'textAlign': None},
                                             'content': [c]}
                        continue
                clean(c)
                if c.get('type') == 'paragraph' and not c.get('content'):
                    n['content'].remove(c)
            if not n.get('content') and n.get('type') == 'listItem':
                n['content'] = []
    clean(p.doc, top=True)

    # codeBlock content must be mark-free
    def strip_cb(n, in_cb=False):
        if isinstance(n, dict):
            in_cb = in_cb or n.get('type') == 'codeBlock'
            if in_cb and n.get('type') == 'text':
                n.pop('marks', None)
            for c in n.get('content', []) or []:
                strip_cb(c, in_cb)
    strip_cb(p.doc)
    return p.doc


def validate(doc):
    """Return a list of schema violations (should be empty)."""
    bad = []

    def walk(n, parent=None):
        if isinstance(n, dict):
            t = n.get('type')
            if t and t != 'doc' and t not in NODES:
                bad.append(('node', t))
            if t == 'text' and parent in BLOCK_CONTAINERS + ('doc',):
                bad.append(('bare-text', parent))
            for m in n.get('marks', []) or []:
                if m['type'] not in MARKS:
                    bad.append(('mark', m['type']))
            for c in n.get('content', []) or []:
                walk(c, t)
    walk(doc)
    return bad


def push(path, cookie):
    title, desc, body = parse_mdx(path)
    doc = md_to_doc(body)
    bad = validate(doc)
    if bad:
        print(f'[schema] {path}: violations {bad}', file=sys.stderr)
        return None
    status, resp = api('POST', '/api/v1/drafts', cookie, {
        'draft_title': title,
        'draft_subtitle': smart_cut(desc),
        'draft_body': json.dumps(doc, ensure_ascii=False),
        'type': 'newsletter',
        'draft_bylines': [{'id': USER_ID}],
    })
    if status != 200:
        print(f'[api] {path}: HTTP {status}: {resp}', file=sys.stderr)
        return None
    url = f'{BASE}/publish/post/{resp["id"]}'
    print(f'[ok] {path}\n     -> {url}')
    return resp['id']


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cookie = load_cookie()
    for path in sys.argv[1:]:
        push(path, cookie)


if __name__ == '__main__':
    main()
