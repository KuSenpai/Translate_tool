// Novel Translator – Wattpad Helper: runs on wattpad.com pages in the user's own browser.
//  • On My Works: sends the list of the user's stories to the local tool.
//  • When the tool has a publish task: opens the story → New part → fills title + content → saves
//    → (publish mode) 5-second countdown with a Cancel button → Publish → reports the result.
// Progress is stored on the tool side (task.stage), so page navigations do not lose the flow.
(() => {
  if (window.__ntHelper) return;
  window.__ntHelper = true;

  const send = (msg) => new Promise((res) => {
    try { chrome.runtime.sendMessage(msg, (r) => res(r || { ok: false, error: chrome.runtime.lastError?.message })); }
    catch (e) { res({ ok: false, error: String(e) }); }
  });
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
  const low = (s) => norm(s).toLowerCase();

  let cfg = null;
  let busy = false;
  let lastStoriesKey = "";
  const handledCancel = new Set();
  const loginNoticeSent = new Set();

  // ------------------------------------------------------------------ page helpers
  function visible(el) {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== "hidden" && st.display !== "none";
  }
  function byText(texts, root = document) {
    const want = (texts || []).map((t) => t.toLowerCase());
    return [...root.querySelectorAll("button, a, [role='button'], input[type='button'], input[type='submit']")]
      .filter(visible)
      .find((el) => want.includes(low(el.innerText || el.value || el.getAttribute("aria-label"))));
  }
  function first(selectors) {
    for (const s of selectors || []) {
      try {
        const el = [...document.querySelectorAll(s)].find(visible);
        if (el) return el;
      } catch { /* invalid selector */ }
    }
    return null;
  }
  function findBody(title) {
    const el = first(cfg.selectors.body_selectors);
    if (el) return el;
    // Fallback: the largest visible contenteditable that is not the title field.
    return [...document.querySelectorAll("[contenteditable='true']")]
      .filter((e) => visible(e) && e !== title && !e.contains(title))
      .sort((a, b) => b.getBoundingClientRect().height * b.getBoundingClientRect().width
        - a.getBoundingClientRect().height * a.getBoundingClientRect().width)[0] || null;
  }
  async function waitFor(fn, ms = 20000) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const v = fn();
      if (v) return v;
      await sleep(400);
    }
    return null;
  }
  function dialog() { return first(cfg.selectors.dialog_selectors); }

  function setTitle(el, value) {
    el.focus();
    if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
      const proto = el.tagName === "INPUT" ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value); // works with React-controlled inputs
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } else {
      document.execCommand("selectAll", false);
      document.execCommand("insertText", false, value);
    }
    el.blur();
  }
  function bodyMatches(el, text) {
    const got = norm(el.innerText), want = norm(text);
    return !!want && got.slice(0, 40) === want.slice(0, 40) && got.slice(-40) === want.slice(-40)
      && Math.abs(got.length - want.length) <= Math.max(20, want.length / 50);
  }
  function insertBody(el, html, text) {
    el.focus();
    document.execCommand("selectAll", false);
    document.execCommand("delete", false);
    const dt = new DataTransfer();
    dt.setData("text/html", html);
    dt.setData("text/plain", text);
    const ev = new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true });
    if (el.dispatchEvent(ev)) document.execCommand("insertHTML", false, html); // editor ignored the paste
  }

  // ------------------------------------------------------------------ banner (visible status + Cancel)
  let bannerEl = null;
  function banner(text, withCancel = false, onCancel = null) {
    if (!bannerEl) {
      bannerEl = document.createElement("div");
      bannerEl.style.cssText = "position:fixed;z-index:2147483647;right:16px;bottom:16px;max-width:380px;padding:12px 14px;" +
        "background:#1f2330;color:#fff;border-radius:10px;font:14px/1.4 Segoe UI,Arial,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.35)";
      document.documentElement.appendChild(bannerEl);
    }
    bannerEl.innerHTML = "";
    const t = document.createElement("div");
    t.textContent = "📖 Novel Translator: " + text;
    bannerEl.appendChild(t);
    if (withCancel) {
      const b = document.createElement("button");
      b.textContent = "Huỷ";
      b.style.cssText = "margin-top:8px;padding:4px 14px;border:0;border-radius:6px;background:#e5484d;color:#fff;cursor:pointer";
      b.onclick = onCancel;
      bannerEl.appendChild(b);
    }
  }
  function hideBanner() { if (bannerEl) { bannerEl.remove(); bannerEl = null; } }

  // ------------------------------------------------------------------ diagnostics (page structure, no personal data)
  function collectDiag() {
    const pick = (els, f) => [...els].filter(visible).slice(0, 150).map(f);
    return {
      url: location.href,
      title: document.title,
      links: pick(document.querySelectorAll("a[href]"), (a) => [a.getAttribute("href"), low(a.innerText).slice(0, 60)]),
      buttons: pick(document.querySelectorAll("button, [role='button']"), (b) => [low(b.innerText || b.getAttribute("aria-label")).slice(0, 60),
        b.id, (b.className || "").toString().slice(0, 80), b.getAttribute("data-testid")]),
      inputs: pick(document.querySelectorAll("input, textarea, [contenteditable='true']"), (i) => [i.tagName, i.id,
        i.getAttribute("placeholder") || i.getAttribute("data-placeholder") || "", (i.className || "").toString().slice(0, 80),
        i.getAttribute("data-testid")]),
      dialogs: pick(document.querySelectorAll("[role='dialog'], [role='alertdialog']"), (d) => low(d.innerText).slice(0, 200)),
    };
  }
  chrome.runtime.onMessage.addListener((msg, _s, reply) => {
    if (msg.type !== "diag") return;
    send({ type: "diag", data: collectDiag() }).then((r) => reply(r.ok ? { ok: true, path: r.data.path } : r));
    return true;
  });

  // ------------------------------------------------------------------ talking to the tool
  async function event(task, data) {
    const r = await send({ type: "event", id: task.id, data });
    return r.ok;
  }
  async function finish(task, data) {
    await event(task, { ...data, final: true });
    banner(data.ok ? (data.published ? "✔ Đã đăng xong." : "✔ Đã điền và lưu nháp.") : "✖ " + (data.message || "Thất bại."));
    setTimeout(hideBanner, 8000);
  }
  async function fail(task, code, message) {
    await finish(task, { ok: false, error_code: code, message, diag: collectDiag() });
  }

  // ------------------------------------------------------------------ My Works → story list
  function scrapeStories() {
    const re = new RegExp(cfg.story_link_regex);
    const ignore = new Set((cfg.story_title_ignore || []).map((s) => s.toLowerCase()));
    const stories = new Map();
    for (const a of document.querySelectorAll("a[href]")) {
      const m = (a.getAttribute("href") || "").match(re);
      if (!m) continue;
      const card = a.closest("li, article, [class*='story' i], [class*='work' i]");
      const heading = card && card.querySelector("h1, h2, h3, h4, [class*='title' i]");
      for (const cand of [norm(heading && heading.innerText), norm(a.innerText || a.getAttribute("title"))]) {
        if (cand && cand.length < 200 && !ignore.has(cand.toLowerCase()) && cand.length > (stories.get(m[1]) || "").length) {
          stories.set(m[1], cand);
        }
      }
      if (!stories.has(m[1])) stories.set(m[1], "");
    }
    return [...stories].map(([id, title]) => ({ id, title }));
  }
  async function maybeSendStories() {
    if (!/^\/myworks\/?$/.test(location.pathname)) return;
    const stories = scrapeStories();
    const key = JSON.stringify(stories);
    if (!stories.length || key === lastStoriesKey) return;
    lastStoriesKey = key;
    const r = await send({ type: "stories", data: { stories, page_url: location.href } });
    if (r.ok) { banner(`Đã gửi ${stories.length} truyện về tool.`); setTimeout(hideBanner, 4000); }
  }

  // ------------------------------------------------------------------ publish task steps
  function onStoryPage(task) {
    const m = location.pathname.match(/\/myworks\/(\d+)/);
    return m && m[1] === task.story_id && !/\/write\//.test(location.pathname);
  }
  function writePartId() {
    const m = location.pathname.match(new RegExp(cfg.part_url_regex));
    return m ? m[1] : null;
  }

  async function openNewPart(task) {
    banner("Đang tạo phần mới…", true, () => cancel(task));
    const link = await waitFor(() => {
      for (const h of cfg.selectors.new_part_hrefs || []) {
        const a = [...document.querySelectorAll(`a[href*='${h}']`)].find(visible);
        if (a) return a;
      }
      return byText(cfg.selectors.new_part_texts);
    }, 20000);
    if (!link) return fail(task, "WATTPAD_UI_CHANGED", "Không tìm thấy nút “New Part / Phần mới” trên trang truyện.");
    await event(task, { stage: "opening", message: "Đang mở trang soạn phần mới…" });
    link.click();
  }

  async function fill(task, partId) {
    await event(task, { stage: "filling", part_id: partId, message: "Đang điền tiêu đề và nội dung…" });
    banner("Đang điền tiêu đề và nội dung…", true, () => cancel(task));
    const title = await waitFor(() => first(cfg.selectors.title_selectors));
    if (!title) return fail(task, "WATTPAD_UI_CHANGED", "Không tìm thấy ô tiêu đề chương trên trang soạn thảo.");
    const body = await waitFor(() => findBody(title));
    if (!body) return fail(task, "WATTPAD_UI_CHANGED", "Không tìm thấy vùng soạn nội dung.");
    setTitle(title, task.title);
    await sleep(300);
    insertBody(body, task.html, task.text);
    await sleep(800);
    if (!bodyMatches(body, task.text)) { // plain-text fallback
      body.focus();
      document.execCommand("selectAll", false);
      document.execCommand("insertText", false, task.text);
      await sleep(800);
      if (!bodyMatches(body, task.text)) return fail(task, "WATTPAD_PUBLISH_FAILED", "Không chèn được nội dung vào editor Wattpad.");
    }
    const save = byText(cfg.selectors.save_texts);
    if (save && !save.disabled) { save.click(); await sleep(2500); } else await sleep(3000); // autosave
    task.stage = "filled";
    await event(task, { stage: "filled", message: "Đã điền và lưu." });
    return true;
  }

  async function countdown(task, seconds) {
    for (let s = seconds; s > 0; s--) {
      if (handledCancel.has(task.id)) return false;
      banner(`Sẽ bấm Publish sau ${s} giây…`, true, () => cancel(task));
      await sleep(1000);
    }
    return !handledCancel.has(task.id);
  }

  async function publish(task) {
    if (!(await countdown(task, 5))) return;
    const btn = await waitFor(() => byText(cfg.selectors.publish_texts), 10000);
    if (!btn) return fail(task, "WATTPAD_UI_CHANGED", "Không tìm thấy nút Publish / Xuất bản.");
    await event(task, { stage: "publishing", message: "Đang bấm Publish…" });
    banner("Đang đăng…");
    btn.click();
    const dlg = await waitFor(() => dialog(), 4000);
    if (dlg) {
      const ok = byText(cfg.selectors.confirm_texts, dlg);
      if (ok) ok.click();
    }
    await checkPublished(task, 30000); // if the page navigates, the next page load finishes the check
  }

  async function checkPublished(task, ms) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      await sleep(800);
      if (!/\/write\//.test(location.pathname)) return finish(task, { ok: true, published: true, message: "Đã đăng lên Wattpad." });
      if (byText(cfg.selectors.unpublish_texts)) return finish(task, { ok: true, published: true, message: "Đã đăng lên Wattpad." });
      if (!byText(cfg.selectors.publish_texts) && !dialog()) return finish(task, { ok: true, published: true, message: "Đã đăng lên Wattpad." });
    }
    return fail(task, "WATTPAD_PUBLISH_FAILED",
      "Đã bấm Publish nhưng không xác nhận được kết quả. Hãy kiểm tra trên Wattpad trước khi thử lại.");
  }

  async function cancel(task) {
    handledCancel.add(task.id);
    await finish(task, { ok: false, error_code: "CANCELLED", message: "Bạn đã huỷ trên Wattpad." });
  }

  async function runTask(task) {
    const path = location.pathname;
    const partId = writePartId();

    if (task.stage === "publishing") { // we navigated after clicking Publish
      if (partId) return checkPublished(task, 15000);
      return finish(task, { ok: true, published: true, message: "Đã đăng lên Wattpad." });
    }
    if (partId && (!task.part_id || task.part_id === partId)) {
      if (["pending", "opening", "filling"].includes(task.stage)) {
        if (!(await fill(task, partId))) return;
      }
      if (task.mode !== "publish") return finish(task, { ok: true, published: false, message: "Đã điền và lưu nháp trên Wattpad (chưa publish)." });
      return publish(task);
    }
    if (task.part_id && task.stage === "pending") { // retry: reopen the part created last time
      location.href = cfg.base + cfg.part_edit_path.replace("{story_id}", task.story_id).replace("{part_id}", task.part_id);
      return;
    }
    if (onStoryPage(task) && task.stage === "pending") return openNewPart(task);
    if (/^\/myworks\/?$/.test(path) && task.stage === "pending") {
      const a = [...document.querySelectorAll(`a[href*='/myworks/${task.story_id}']`)].find(visible);
      location.href = a ? a.href : cfg.base + cfg.story_path.replace("{story_id}", task.story_id);
      return;
    }
    if (path === "/" || /\/(login|signup)/.test(path)) {
      banner("Hãy đăng nhập Wattpad trong tab này (bật VPN nếu cần). Sau đó mở lại trang truyện — tool sẽ tiếp tục.");
      if (!loginNoticeSent.has(task.id)) {
        loginNoticeSent.add(task.id);
        await event(task, { message: "Wattpad chưa đăng nhập trong trình duyệt này — hãy đăng nhập trong tab Wattpad." });
      }
    }
  }

  async function tick() {
    if (busy) return;
    busy = true;
    try {
      if (!cfg) {
        const r = await send({ type: "config" });
        if (!r.ok) return; // tool not running
        cfg = r.data;
      }
      if (location.origin !== new URL(cfg.base).origin) return;
      await maybeSendStories();
      const r = await send({ type: "task" });
      const task = r.ok ? r.data.task : null;
      if (!task || handledCancel.has(task.id)) return;
      await runTask(task);
    } catch (e) {
      console.warn("[Novel Translator]", e);
    } finally {
      busy = false;
    }
  }

  tick();
  setInterval(tick, 2000);
})();
