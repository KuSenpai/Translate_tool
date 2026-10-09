# Novel Translator

[🇻🇳 Tiếng Việt](README.md) · 🇬🇧 English

A local web tool for processing and publishing Korean → Vietnamese translated novel chapters:

```
Word (.docx) → find chapters → split Korean + Vietnamese text → edit (AI suggestions + glossary)
→ Preview → Save DOCX → Publish to Wattpad
```

## Installation (Windows)

```bash
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```

> If `pip` inside the venv fails with an SSL error (`CERTIFICATE_VERIFY_FAILED`), install with the system Python's pip:
> `py -3.11 -m pip --python "<absolute path>\.venv\Scripts\python.exe" install -r requirements.txt`

Playwright uses the Edge/Chrome already installed on the machine (`WATTPAD_BROWSER_CHANNEL=msedge`). To use a separate Chromium:
`.venv\Scripts\python -m playwright install chromium`, then set `WATTPAD_BROWSER_CHANNEL=` (empty).

## Running (first time and after updating the tool)

```bash
git pull                                                    # if you pull new versions from git
.venv\Scripts\python -m pip install -r requirements.txt     # only needed when requirements.txt changed
.venv\Scripts\python -m app.main
```

Open http://127.0.0.1:8765 (or double-click `run.bat`, which opens the browser and starts the server). Stop with `Ctrl+C`.

**Updating from an older version:** keep your `.env` and the `data/` folder (projects, termbases and unfinished translation jobs live there).
Compare `.env.example` with your `.env` and add any new variables you need (all optional): `TRANSLATE_PROVIDER`,
`ANTIGRAVITY_MODEL_PRO`, `ANTIGRAVITY_MODEL_FLASH`, `ANTIGRAVITY_CLI_PATH`, `CLAUDE_CODE_PATH`.
Restart the tool after editing `.env`. To try the UI without spending quota or money: `TRANSLATE_PROVIDER=mock`.

## Main features

| Home-screen entry | What it does |
| --- | --- |
| Open Word file → editor | Edit the Vietnamese text, AI suggestions, glossary, Preview, Save DOCX, publish to Wattpad |
| 🤖 AI Translate | Translate a whole novel Korean → Vietnamese with the Claude API, Claude Code (Pro/Max plan), Gemini (Antigravity), Grok (xAI API / Grok CLI) or OmniRoute |
| 📚 Terminology | Termbase + story notes, AI scan of old chapters, consistency check |
| 🧹 Raw data tools | Clean translations pasted from ChatGPT; split out untranslated Korean raw text |

## Usage

1. **Open a Word file**: drag and drop a `.docx`, or enter a path (opening by path always reads the latest version of the file; the original is never written to).
2. **Pick a chapter**: type a chapter number or click the list. Colours: green = Korean + Vietnamese present, yellow = has warnings, red = needs checking.
   Low-confidence chapters (missing heading, duplicate number, inferred boundaries) are locked until you confirm you have checked them.
3. **Edit the Vietnamese** on the right, comparing with the Korean on the left. `Ctrl+S` saves a draft, `Ctrl+Z/Ctrl+Y` undo/redo, `Reset` restores the original from Word.
4. **AI**: select a passage → `✨ Suggest correction` → review Original / Suggestion / Reason → `Apply` (or ignore). The AI never changes the translation on its own.
5. **Glossary**: `김수현 → Kim Soo-hyun`, `형 → anh`… (you can add spellings to avoid). It is sent to the AI and used for checks in the *Errors* tab.
6. **Preview** → `Mark as reviewed` → `Save DOCX` (saved to `output/<story-name>/Chapter_N.docx`).
7. **Wattpad**: `Log in to Wattpad…` opens a browser window for you to **log in yourself** (the tool never reads or stores your password; the session is kept in `data/wattpad_profile`).
   `Load story list` → pick a story → tick *I confirm this is the final version* → `Publish` (or save as a draft on Wattpad only).
   On success the DOCX is saved automatically and the status becomes `PUBLISHED`. On failure it stays `READY_TO_PUBLISH` and shows the error; click again to retry
   (parts already created on Wattpad are reused, never duplicated).

Chapter status: `LOADED → EDITING → REVIEWED → READY_TO_PUBLISH → PUBLISHED`. Editing after review goes back to `EDITING`.

## Translate a whole novel with AI (🤖 AI Translate)

1. Add `ANTHROPIC_API_KEY=sk-ant-...` to `.env` (create a key at console.anthropic.com) and restart the tool.
2. Click **🤖 AI Translate** → drag and drop a Korean novel file, `.txt` or `.docx` (many chapters).
3. Choose a model (Opus 5.5 = best quality; Sonnet 5.5 ≈ 2× cheaper; Haiku 4.5 = cheapest), the chapter range and the glossary,
   adjust the **Translation instructions** (style, forms of address) → **Start translating**. A cost estimate is shown before the run
   and the real cost while it runs.
4. Output: `output/translations/<name>_vi_<id>.docx` (+ `.txt` if the input was `.txt`): each chapter in Korean with the translation right below it —
   the exact format the editor reads (**Open in editor** to review and edit, then publish to Wattpad as usual).

- Runs in the background and saves after every chapter: pause / resume / retry failed chapters; you can close the tool and resume later.
- Chapters that already have a Vietnamese version (half-translated bilingual files) are skipped.
- New character names / terms found by the AI are recorded and reused in later chapters for consistency.
- If the AI refuses or a safety filter blocks a chapter, it is marked with the error `AI_REFUSED` and the Korean text is kept in the output file —
  re-translate that chapter with another model.

### Use a Claude plan (Pro/Max) instead of the API

Choose the model **Claude Code · Opus** or **Claude Code · Sonnet** (in 🤖 AI Translate and 📚 Terminology): the tool runs `claude -p`
locally — it counts against your Claude plan's usage, **no API billing**, and no `ANTHROPIC_API_KEY` is needed.

1. Install Claude Code (if you don't have it): `npm install -g @anthropic-ai/claude-code`
2. Sign in once with an account that has a plan: `claude auth login --claudeai`
3. When the plan's quota runs out the job **pauses itself** (the chapter in progress returns to the queue) → click **Resume** when the quota resets.

The tool removes `ANTHROPIC_API_KEY` from the environment when calling `claude`, so this mode never bills your API account.
For a different executable path, set `CLAUDE_CODE_PATH` in `.env`.

### Translate with Gemini through Antigravity

Choose the model **Antigravity · Gemini Pro** or **Antigravity · Gemini Flash** (in 🤖 AI Translate and 📚 Terminology): the tool calls the
Antigravity CLI (`agy`) in headless mode — it uses the quota of the Google account signed in to Antigravity, **no API billing**.

1. Install the Antigravity CLI (PowerShell): `irm https://antigravity.google/cli/install.ps1 | iex`
2. Run `agy` once in a terminal to sign in with Google, then exit (Ctrl+D twice).
3. Pick an Antigravity model in the tool → it runs `agy models` to check you are signed in and picks the newest Gemini version
   (override with `ANTIGRAVITY_MODEL_PRO` / `ANTIGRAVITY_MODEL_FLASH` in `.env`).

**Translation rules for Gemini** live in `app/ai/gemini_rules.md` (role, mandatory rules in priority order, Korean honorifics/forms of address,
no tool use, self-check). To change them: copy the file to `data/gemini_rules.md` and edit it — the tool prefers the copy in `data/`.
`{style}` in the file is replaced by the job's *style instructions*. If Gemini returns the wrong number of paragraphs or leaves Korean text behind,
the tool automatically asks for that chapter again once, with an error reminder.

`agy` runs in an empty folder outside the project (with a `GEMINI.md` forbidding tool use) and with auto-approval off, so the agent
cannot read or write your files. When the quota is exhausted the job pauses, like Claude Code. Gemini has its own safety filter: some passages may be blocked
(`AI_REFUSED`) — re-translate those chapters with another model.

### Translate with Grok (xAI)

Choose the model **Grok (xAI) · best** or **Grok (xAI) · cheap** (in 🤖 AI Translate and 📚 Terminology). Useful as a fallback model
for re-translating chapters marked `AI_REFUSED`. Billed per token on your xAI account.

1. Get an API key at console.x.ai and add credit.
2. Add to `.env`: `XAI_API_KEY=xai-...` and restart the tool.
3. Pick a Grok model in the tool → it calls `GET /v1/models` to check the key and warns if the model slug is unavailable.
   Defaults are `grok-4.7` (best) / `grok-4.3` (cheap); change with `XAI_MODEL` / `XAI_MODEL_FAST`.

The tool shares the translation prompt with Claude (`SYSTEM_PROMPT` + *style instructions*) and calls an OpenAI-compatible API
(`https://api.x.ai/v1`, change with `XAI_BASE_URL`). A wrong paragraph count or leftover Korean triggers one automatic re-translation of the chapter. When credit runs out the job pauses;
add credit and click **Resume**.

### Translate with Grok CLI (grok.com login, no API key)

Choose the model **Grok CLI** (in 🤖 AI Translate and 📚 Terminology): the tool runs the `grok` command headless with the grok.com account you are signed in to.

1. Install (PowerShell, not cmd): `irm https://x.ai/cli/install.ps1 | iex`
2. Run `grok` once to sign in (a browser opens). The tool finds `grok.exe` on PATH or in `~/.grok/bin`
   (override with `GROK_CLI_PATH`). It uses the account's default model; force one with `GROK_CLI_MODEL` (see `grok models`).
3. Pick **Grok CLI** in the tool → it runs `grok models` to check you are signed in.

**Multiple grok.com accounts:** each account is its own `GROK_HOME` folder (with its own `auth.json`). Sign in a second account (PowerShell):

```powershell
New-Item -ItemType Directory -Force D:\Tool\Translate_tool\data\grok_accounts\acc2
$env:GROK_HOME = "D:\Tool\Translate_tool\data\grok_accounts\acc2"
& "$env:USERPROFILE\.grok\bin\grok.exe" login      # sign in with the second account, then close the window
```

Then list them in `.env`: `GROK_CLI_HOMES=default;D:/Tool/Translate_tool/data/grok_accounts/acc2` (`default` = the account `grok` is already signed in with). The tool rotates calls
across accounts (parallel pieces of one chapter run on different accounts, so a single account's 2-requests/second limit no longer applies) and
switches to another account as soon as one is rate-limited or out of quota (cooldown 45 seconds / 30 minutes). To simply switch to a different account: `grok logout`, then `grok login`.

`grok` runs in an empty folder outside the project with all tools (`--tools ""`) and web search disabled, so the agent cannot read or write your files.
Each call carries ~14k tokens of fixed agent overhead (mostly cached). When the quota runs out the job pauses; click **Resume** once it resets.

## Re-translate a chapter with AI (chapter editor)

In the chapter editor, click **🔁 Re-translate chapter** (or open *Re-translate whole chapter with AI* in the ✨ AI tab): choose a model (Claude, Claude Code,
Gemini, Grok…), a reasoning level and optional extra instructions → the tool re-translates the whole chapter from the **Korean text**, together with the glossary, story notes and
the end of the previous chapter. The result is only shown for review; click **Apply** to replace the text you are editing (you can Undo, then Save Draft). Handy for
trying another model on a chapter marked `AI_REFUSED`.

### Translate through OmniRoute (local AI gateway)

[OmniRoute](https://github.com/diegosouzapw/OmniRoute) is an AI gateway running on your machine (default `http://localhost:20128`) that combines many providers / accounts / combos
behind one OpenAI-compatible endpoint. Choose the **OmniRoute** model in 🤖 AI Translate, 📚 Terminology and chapter re-translation. Set in `.env`:

```
OMNIROUTE_API_KEY=...      # create it in the OmniRoute dashboard
OMNIROUTE_MODEL=...        # exact model or combo name as OmniRoute lists it (dashboard or GET /v1/models)
OMNIROUTE_BASE_URL=        # optional, default http://localhost:20128/v1
```

When you pick the OmniRoute model, the tool queries `GET /v1/models` to check the key and model name, and lists the available models if `OMNIROUTE_MODEL` is wrong. If the model behind it
does not support strict JSON schema, the tool falls back to `json_object`, then plain text (schema in the prompt, parsing the result itself). Cost / quota are decided by OmniRoute and the providers
you connected to it; the tool cannot estimate money.

## Automatic arc titles (🏷)

The novel is split into several long, interleaved arcs; chapter titles look like **`Chapter number. Arc name (n)`** (e.g. `2761. Atlantis of the Gods (107)`),
where `n` is the chapter's index within that arc. In the chapter editor click **🏷 Auto title**:

- The arc is recognised from the chapter's **Korean title** (`다크 문` → *Dark Moon*). A chapter without a Korean title (a new raw file only has `2760화`)
  **follows the previous chapter's arc** — change it with the arc dropdown. An unknown Korean title creates a **new minor arc** (with a 🤖 Translate name button); the minor arc's `(n)` counts automatically.
- 6 major arcs are built in (Atlantis of the Gods, Quang Minh Thăng Thiên Đồ, Eternal Eden, Dark Moon, Savior Academy, Plum Blossom Swordsman…) and are remembered permanently
  along with their counters: **Manage arcs…** lets you edit names, Korean names, title templates, and the **Counted up to** column (set it to the real number on Wattpad and later chapters continue from there).
- **↻ Build from Word files** scans the story's files to assign an arc to every existing chapter (minor arcs are created automatically, named from the old Vietnamese titles).
- `n` is computed from chapter order (the chapters already assigned to the arc below it), so clicking Apply again does not double-count and out-of-order assignments still come out right.
  Data is in `data/stories/<story>/arcs.json` (or in the project folder if it doesn't belong to a story yet). Newly loaded chapters pick up this title automatically if an arc is assigned.

## Reconcile terminology with old Wattpad chapters (📚 → section 3b)

Chapters you already published are treated as **more correct** than the current glossary. Section **3b** scrapes them, compares them with the termbase and puts the differences into section 4
(source “old Wattpad chapters”, with a *current* column; accepting a proposal uses the old translation and keeps the current one in the “avoid” list).

1. Reload the extension (`edge://extensions` → Reload; it must be **v1.3.0**), turn on your VPN, and open a `wattpad.com` tab in Edge.
2. In 📚 Terminology: tick the Wattpad stories (taken from My Works), enter the **original Korean file** (`.txt`/`.docx` containing those chapters, e.g.
   `data/Data raw/into-the-creative-work/[610] 창작물 속으로.txt` — it must be the Korean version, not the English `book.txt`), the chapter range, pick a model and click **Scrape & compare**.
3. The extension reads the chapter list + content through Wattpad's own endpoints (it changes nothing on Wattpad) and sends them to the tool; the tool matches them with the Korean by chapter number,
   drops the chapter's leading note lines (`Note: …`, `-`), then has the AI compare each group of chapters against the glossary. **Scraped data is not stored** (kept in RAM only until done).
4. Published titles (`2201. Dark Moon (165)`) also update the **arc counters** (🏷): each chapter is assigned the right arc and the counter is set from the latest published chapter.
   Arcs with slightly different names (ignoring linking words like “of/in/into”) count as the same arc; clearly different names create a new minor arc.

## Termbase (📚 Terminology) — keep character names, skills… consistent

Each story (project = bilingual Word file of old chapters) has a termbase:

1. **Your data**: import a .txt/.csv/.json/.docx file or paste. Lines like `김수현 = Kim Soo-hyun (note)` (or `→`, Tab, `:`)
   become terms; other descriptive lines become **Story notes** (characters, relationships, forms of address, setting).
2. **Scan old chapters with AI**: Claude reads the translated chapters (Korean + Vietnamese) and extracts character names, skills, places, items,
   titles… along with *how you translated them*, and reports different translations of the same term → a list of proposals to review
   (edit the translation, choose the type, accept/discard). Scans the 30 most recent chapters by default; a cost estimate is shown.
3. **Consistency check** (free): how many chapters each term appears in, what % use the correct translation, which chapters deviate.
   Words in brackets `[ ]「」『』` that repeat across chapters but are not in the termbase are suggested for adding.
4. When **🤖 AI Translate** has “Use glossary of” this story selected: each chapter is sent with the terms that appear in it
   + the story notes; new terms the AI meets while translating can be added to the termbase with the **📚 Add … new terms to the termbase** button.
   The editor (Errors tab) and AI correction suggestions use this termbase too; “Avoid” = an old translation that is flagged when it still appears.

## Raw data tools (🧹)

The **🧹 Raw data tools** card on the home screen (enter a file path, optionally a story name to share its termbase):

- **🧹 Clean rough translation (.docx)**: a bilingual file copied out of a ChatGPT chat (Korean chapter → “translate to Vietnamese” prompt
  → ChatGPT's preamble → Vietnamese text → closing remark, `2 / 2` counters, ads, base64 strings…) is cleaned into the standard layout
  `[Korean heading] Korean text [Vietnamese heading] Vietnamese text` for each chapter. The result is saved in `data/library/<story name>/`, opened as a
  project and attached to the story. The original file is never written to.
- **📄 Prepare Korean raw (.txt)**: a raw file exported from an epub (table of contents at the top, every chapter heading repeated 2–3 times) → one
  heading per chapter. The tool drops chapters that **already have a Vietnamese version** in the story and keeps only those still to translate (you can limit the From/To chapter range),
  and registers them in 🤖 AI Translate — open it, pick a model and translate.

A story groups several files/projects that share one termbase; set it in the *Belongs to story* box or via the API `PUT /api/projects/{id}/story`.

## Chapter detection

A heading must be **an entire short paragraph** matching one of these patterns: `제 12 화`, `제12화`, `12화`, `제 12 장`, `Chương 12`, `CHƯƠNG 12: Title`,
`Tập 12. Title`, `Chapter 12`, `Ch. 12`, `EP.12 12. Title`, `1920. Title`… Numbers inside sentences (“12 years old”,
“chapter 12 of his life”) are not treated as headings. The `1920. Title` form and number-only lines (`2151`) are accepted only when the chapter number
fits the order of the surrounding headings; rejected lines are listed in the warnings. Junk glued before a heading (`Ads by Pubfuture`,
`Interrupted`) is ignored (see `NOISE_PREFIX`).

Large files (tens of thousands of paragraphs) take about 20 seconds on first read; the result is cached in `data/projects/<id>/parsed.pkl`
so later opens are almost instant (the cache refreshes automatically when the Word file changes).
The language of each part is determined from its content (Hangul ratio), not only from the heading.
Add new patterns in `HEADING_PATTERNS` in `app/document/chapter_parser.py`.

## Structure

```
app/
  document/    docx_reader, chapter_parser, cleaner, docx_writer, models   (independent of UI/Wattpad)
  editor/      chapter_editor (workflow), chapter_state, glossary, validation
  ai/          llm_service (Anthropic | OpenAI | local | mock), correction_service,
               novel_translator + translation_jobs (whole-novel translation, background jobs), termbase,
               claude_code (claude -p), antigravity (agy / Gemini) + gemini_rules.md
  tools/       data_import (clean raw data, prepare raw)
  publishing/  wattpad_publisher (Playwright), wattpad_worker (subprocess), jobs, publish_service,
               wattpad_selectors.json
  storage/     project_state (JSON in data/projects/)
  static/      UI (plain HTML/CSS/JS): app.js, translate.js, termbase.js, data.js
tests/         pytest + fake_wattpad (simulated site to test the publisher) + make_sample (creates a sample book.docx)
```

## Publish to Wattpad with the extension (default)

The tool cannot drive the Edge you use every day (Edge blocks automation of the main profile), so publishing is done by a small
extension running inside that Edge — reusing your Wattpad login (Google/Facebook) and your VPN.

**One-time setup:**

1. Open `edge://extensions` and turn on **Developer mode** (bottom-left).
2. Click **Load unpacked** → choose the `extension` folder inside the tool folder (`<tool folder>\extension`).
3. Open the tool at `http://127.0.0.1:8765` **in that same Edge**.

> After updating the tool (the `extension` folder changed), go to `edge://extensions` and click **Reload (⟳)** on the extension, then
> press F5 on any open Wattpad tabs. If you forget, the tool warns “Extension is running an old version” on the Preview screen and the multi-chapter publish card
> (the old version cannot publish correctly: it may get stuck at “Opening the new part page”).

**Usage:**

- Preview → **Open Wattpad (your Edge)** / **↻ Load list from My Works**: opens My Works in a new tab; the extension sends the story
  list back to the tool. Or paste a story link (including an editor link `…/myworks/<story>/write/<part>`) into the
  “Add story by link” box.
- Pick a story, tick the confirmation, **Publish** → the tool opens a Wattpad tab and the extension does exactly what you would do by hand:
  1. On the story page (`/myworks/<story>`) it **opens the newest chapter** in the list (it does not click the `+ New Part` button on this
     page — that only adds an empty draft to the list without opening it).
  2. If the newest chapter is **already published** → open the part-list menu at the top-left of the editor → **New Part** → an empty chapter.
     If the newest chapter is an **empty draft** (e.g. “Untitled Part 78”) → use it directly. If the newest chapter is a draft that **already
     has text** → stop and report `WATTPAD_LATEST_DRAFT_NOT_EMPTY` (it never overwrites your work).
  3. Fill in the title + content → save → 5-second countdown (click **Cancel** on the notification box to stop) → **Publish**.
  4. The **browser's** confirmation popup (`confirm()`) is clicked OK by the extension — only right when it has just clicked Publish; at other times
     the page's popups show normally (`extension/page_hook.js`). In-page popups (if any, including two-step ones) are handled too. The result is then reported back to the tool.
- The extension only fills in a part **it just created itself**, the newest empty chapter, or the part created on a previous attempt of the same
  chapter — it never overwrites an existing chapter. If the tab is open on an old chapter's editor, it first switches to the newest chapter.
- Clicking **Cancel** in the tool (or on the notification box on the Wattpad page) stops the extension, even during the countdown before
  Publish. With several Wattpad tabs open only one tab takes the job, so chapters are not duplicated.
- The extension toolbar button: see connection status, change the tool address, **Send page diagnostics** (saves the structure of the
  Wattpad page into `data/logs/wattpad/` so it can be fixed when Wattpad changes its UI).
- In-page popups are found by how they cover the page (no `role="dialog"` needed); only labels listed in `confirm_texts` are
  clicked. If Wattpad changes button/popup labels, the tool reports `WATTPAD_CONFIRM_NOT_FOUND` together with the **popup text**; click **Send page
  diagnostics** (while the popup is open) or add the label to `confirm_texts` / `confirm_selectors`.
- Button labels / selectors are in the `"ext"` section of `app/publishing/wattpad_selectors.json`; the extension reads it directly from the tool, so
  editing this file does not require reinstalling the extension.

### Publish several chapters at once

After opening a Word file, the chapter-selection screen has a **📤 Publish many chapters to Wattpad** card:

1. Choose a **story** (list taken from My Works, or added by link on the Preview screen) and enter the chapters, e.g. `12-20, 25`
   (the **Select unpublished chapters** button pre-fills them). Choose *Publish* or *Save as draft only*.
2. Tick **I confirm these chapters are final** → **Publish N chapters** → confirm. The tool opens a Wattpad tab.
3. The tool publishes **one chapter at a time, in chapter-number order**, a few seconds apart (`BATCH_DELAY` in
   `app/publishing/publish_service.py`, default 8 seconds). Per-chapter progress shows right below the button; **Cancel batch** stops
   immediately, and chapters already published are not removed.

Notes:

- **Keep that Wattpad tab open and visible** (don't minimise the window, don't leave the tab in the background for long) — the extension runs in this tab;
  the browser throttles hidden tabs and freezes Wattpad's UI effects (menus, popups). The extension has a fallback for this
  but a foreground tab is still the safest.
- Chapters not yet opened in the editor are read from the Word file automatically; confirming the whole batch counts as having reviewed them. **Already published** chapters are
  skipped; chapters where the parser is unsure of the boundaries (low confidence, not yet viewed) are blocked — open them in the editor to check first.
- The title on Wattpad = the chapter title in the editor.
- **An error on a chapter stops right there** (later chapters are untouched) so the order is never broken. Fix the error and publish
  the same range again: the failed chapter updates the part already created (no duplicate), and the later chapters continue.

The extension only talks to the tool on your machine (`127.0.0.1`) and does not read passwords or cookies. Its API (`/api/ext/*`) only
accepts requests carrying the extension's own header; other web pages cannot call it.

To go back to the old method (a separate automated Edge window): set `WATTPAD_MODE=playwright` in `.env`.

## Tests

```bash
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m tests.make_sample      # creates samples/book.docx
.venv\Scripts\python -m tests.demo_server      # app + simulated Wattpad at http://127.0.0.1:8766
```

Logs: `data/logs/app.log` (no passwords, API keys or cookies). Screenshots when Wattpad fails: `data/logs/wattpad/`.
