---
name: substack-publisher
description: Use when 把 Markdown/英文文章推成 Substack 草稿（内部 API 半自动，人工点发布）. MD→ProseMirror doc→POST /api/v1/drafts，含 schema 校验与渲染自检.
version: 2.0.0
author: kael
license: MIT
metadata:
  hermes:
    tags: [substack, newsletter, publishing, prose-mirror, draft]
    related_skills: []
---

# Substack 草稿发布（内部 API 半自动）

Substack **没有官方发布 API**（官方 API 只读合作伙伴数据；PyPI `substack-api` 只读；Zapier 只有触发器无发布动作）。可行路线是逆向自家编辑器的内部接口 `POST /api/v1/drafts` + 会话 cookie，半自动：**脚本建草稿 → 人工在网页点 Publish**。不建议全自动直发：接口无文档随时会改，静默失败无兜底。

生产脚本：[scripts/push-draft.py](scripts/push-draft.py)

## 用法

```bash
pip install markdown
export SUBSTACK_PUB=yourname.substack.com
export SUBSTACK_USER_ID=123456789   # 字符串形态的你的 user_id
# scripts/ 同目录放 cookies.txt（chmod 600，勿入 git）：
#   substack.sid=<浏览器 devtools 复制的值>
python3 scripts/push-draft.py article1.md article2.md
# 每个文件输出草稿编辑 URL: https://<pub>/publish/post/<id>
```

国内访问需代理：`export HTTPS_PROXY=http://127.0.0.1:7890`

## 内部 API schema（2026-09 逆向实测，接口漂移时重测）

- 认证：`Cookie: substack.sid=...`（老的 `connect.sid` 已淘汰）。抓法：浏览器 F12 → Application → Cookies → `substack.com`。时效数周，失效重抓覆盖即可。用户粘贴整段 cookie dump 时通常只需 `substack.sid`（+可选 `substack.li`）；`_ga`/`AWSALB`/`cf_*` 均可丢弃
- 端点：`POST /api/v1/drafts` 建草稿；`PUT /api/v1/drafts/<id>` 更新；`DELETE /api/v1/drafts/<id>` 删除；`GET /api/v1/drafts?limit=N` 列表（返回键是 **`posts`** 不是 drafts）；`GET /api/v1/drafts/<id>` 拉单篇
- 必填 payload：
  - `type`: `"newsletter"`（⚠️ 枚举会漂移：社区旧文档的 `newsletter_post`、`post` 在 2026-09 均 400——报错时 GET 一篇现有草稿抄它的 `type`）
  - `draft_body`: **字符串化的 ProseMirror doc JSON**（`json.dumps(doc)`），不是 `{html:...}` 对象也不是裸 HTML
  - `draft_bylines`: `[{"id": "<user_id 字符串>"}]`（纯数字报 Invalid value；自己的 user_id 从现有草稿的 `postBylines[0].user_id` 拿）
  - `draft_title` / `draft_subtitle`
- PUT 比 POST 严：**显式 null 字段直接 400**（`post_date`/`email_subject` 传 null 都被拒）——更新时干脆不传这些键
- API 层只做宽松校验：**payload 非法也能 200 返回 id**，但编辑器打开即崩（"Something has gone wrong" / "this page croaked"）——所以推送后必须渲染自检（见下）

## ProseMirror doc 规则（脚本已内置校验，每条都曾造成真实崩溃）

编辑器是 TipTap v2，schema 节点白名单 38 种（paragraph/heading/blockquote/bulletList/orderedList/listItem/hardBreak/horizontalRule/codeBlock/image/pullquote/calloutBlock/highlighted_code_block/inline_latex/latexBlock/paywall/footnote/caption/cashtag/mention/subscribeWidget…），marks 仅 bold/italic/strike/code/link。

1. **节点名驼峰式**：`codeBlock`/`bulletList`/`orderedList`/`listItem`/`hardBreak`/`horizontalRule`。蛇形式（旧版约定）编辑器直接崩
2. **块容器下禁止裸 text 节点**：markdown→HTML 后 blockquote/li 标签内的换行缩进会变成游离 text，必须清洗；listItem 下的非空裸文本要包一层 paragraph
3. **codeBlock 内文本不得带任何 inline mark**
4. attrs 约定：`paragraph`/`heading` 带 `{"textAlign": null}`（heading 另有 `level`），`codeBlock` 带 `{"language": null}`；列表不带 attrs（旧版 `{"tight": true}` 已废）
5. 链接是 **mark**（`{"type":"link","attrs":{"href":...}}`）不是节点；`<br>` → `hardBreak`
6. doc 顶层只能是块级节点；空段落删除；副标题按 140 字符在单词边界截断

## 渲染自检（不靠肉眼，推送后自动验证）

编辑器崩溃是客户端 React 错误边界，API 无法预知。用无头浏览器带 cookie 实测：

```python
from playwright.sync_api import sync_playwright
cookies = [{'name': 'substack.sid', 'value': '<sid>', 'domain': '.substack.com', 'path': '/'}]
with sync_playwright() as pw:
    b = pw.chromium.launch(channel='chrome', headless=True)   # 用本机 Chrome
    ctx = b.new_context(); ctx.add_cookies(cookies)
    page = ctx.new_page()
    page.goto(f'https://<pub>/publish/post/{draft_id}', wait_until='domcontentloaded')
    page.wait_for_timeout(10000)
    text = page.inner_text('body')
    ok = ('croaked' not in text and 'gone wrong' not in text
          and 'Description' in text and '<正文特征词>' in text)
```

- 判定：出现 `croaked`/`gone wrong` = 文档非法；`Description`（设置面板）= 编辑器加载成功；正文特征词 = 内容真的渲染了
- **频率限制**：连续打开 publish 页会 429（Too Many Requests），间隔 ≥10-15 秒，429 后退避 20 秒重试（最多 3 次）
- 定位坏节点的方法：构造 11 种单元素文档（段落/标题/引用/两种列表/代码块/分割线/加粗斜体/行内 code/链接/硬换行）各建一个草稿逐个打开；若单元素全过而全文崩，则对正文节点**二分法**建半篇草稿逐级缩小

## 坑与边界

| 症状 | 处置 |
|---|---|
| 400 `param "type" Invalid value` | 枚举漂移，GET 现有草稿抄当前合法值 |
| 400 `draft_bylines[0].id Invalid value` | byline 要 `{"id": "字符串"}` 形态 |
| 400 `param "post_date" Invalid value`（PUT） | 去掉显式 null 字段 |
| 草稿列表空但网页有草稿 | 列表接口不可靠，用 `GET /api/v1/drafts/<id>` 按 id 直拉 |
| 国内直连超时 | 走代理；cookie 抓取也要在已登录浏览器里 |
| 推送后网页崩但 API 返回 200 | doc 结构非法，按上面「渲染自检」二分定位，别指望 API 报错 |
| 想全自动直发 | 不建议，保留人工点发布这一道兜底 |

## 凭证管理

- 存 `scripts/cookies.txt`，每行一个 `key=value`，chmod 600，**绝不进 git**（仓库 .gitignore 已排除）
- 发布前 grep 一遍仓库确认无 sid/user_id 泄漏：`grep -rE 'substack.sid|substack.li' .` 应只命中 .gitignore 和文档说明

## Verification Checklist

- [ ] `python3 scripts/push-draft.py` 输出每个文件的 publish/post/<id> URL
- [ ] 脚本内置 schema 校验零违规（有违规会直接 stderr 拒绝推送）
- [ ] 无头浏览器自检：无 croaked/gone wrong、编辑器加载、正文特征词出现
- [ ] 测试用草稿用 `DELETE /api/v1/drafts/<id>` 清理
