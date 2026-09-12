# substack-draft-publisher

Push Markdown articles to Substack **drafts** via the internal drafts API — semi-automatic by design: the script creates a draft, a human opens it in the browser and clicks Publish.

Substack has no official publish API. This project reverse-engineers the endpoint their own editor uses (`POST /api/v1/drafts`), converts Markdown to the ProseMirror document format the editor expects (TipTap v2 schema), and validates the document against the schema before pushing.

Can be used standalone, or as a [Hermes Agent](https://hermes-agent.nousresearch.com/docs) skill (this repo IS the skill: `SKILL.md` + `scripts/`).

## Quick start

```bash
pip install markdown

export SUBSTACK_PUB=yourname.substack.com
export SUBSTACK_USER_ID=123456789   # your numeric user id, as a string

# scripts/cookies.txt (chmod 600, gitignored):
#   substack.sid=<value copied from browser devtools>

python3 scripts/push-draft.py article.md
# -> https://yourname.substack.com/publish/post/<id>  (open, check, Publish)
```

If substack.com is not directly reachable, set `HTTPS_PROXY`.

## What the script guarantees

- converts Markdown (frontmatter title/description, headings, lists, blockquotes, fenced code, tables→paragraphs, links, inline code) into a ProseMirror doc that matches Substack's editor schema — verified against the editor's actual JS bundle
- rejects documents containing node types, marks, or structures known to crash the editor (it fails loudly at push time instead of creating a broken draft)
- cuts the subtitle at a word boundary to fit Substack's 140-char limit

## Known failure modes & fixes

See [SKILL.md](SKILL.md) — including how to self-verify drafts with headless Chrome + Playwright, how to bisect a crashing document, and the API's quirks (enum drift on `type`, PUT rejecting explicit nulls, list endpoint key being `posts`, rate limits on the publish page).

## Security & privacy

- Your session cookie lives only in `scripts/cookies.txt`, which is `.gitignore`d and expected to be chmod 600
- No cookie values, user ids, or publication names are hardcoded; everything comes from env vars
- Never commit `cookies.txt`

## License

MIT

---

## Support

If this saved you some time, consider supporting the project:

**国内用户（微信/支付宝）** — [爱发电 afdian](https://afdian.com/a/YOUR_AFDIAN_NAME)
<!-- TODO: 把 YOUR_AFDIAN_NAME 换成你的 afdian 用户名；或替换为一行微信/支付宝收款码图片 <img src="docs/wechat-qr.png" width="150"/> -->

**International** — [Ko-fi](https://ko-fi.com/YOUR_KOFI_NAME) / [PayPal.me](https://paypal.me/YOUR_PAYPAL)
<!-- TODO: replace YOUR_KOFI_NAME / YOUR_PAYPAL with your real links (both withdraw via PayPal, no US info needed) -->

Before the placeholders above are replaced, starring the repo and reporting issues also help a lot.
