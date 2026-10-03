// Novel Translator — front-end (vanilla JS, no build step).
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const S = {
  project: null, index: null, chapter: null, dirty: false,
  lastRange: null, suggestion: null, glossary: [], job: null,
};

// ---------------------------------------------------------------- utils
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
};

async function api(method, url, body, isForm = false) {
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: body && !isForm ? { "Content-Type": "application/json" } : {},
      body: isForm ? body : body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw Object.assign(new Error("Không kết nối được tới server local. Server còn chạy không?"), { code: "NETWORK" });
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const err = new Error(data?.error?.message || `HTTP ${res.status}`);
    err.code = data?.error?.code; err.details = data?.error?.details;
    throw err;
  }
  return data;
}

let toastTimer;
function toast(msg, kind = "", sticky = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = `toast ${kind}`;
  clearTimeout(toastTimer);
  if (!sticky) toastTimer = setTimeout(() => t.classList.add("hidden"), kind === "error" ? 9000 : 3500);
}
// Reading a big novel can take ~20s the first time: keep a visible, ticking indicator.
async function withBusy(label, fn) {
  const started = Date.now();
  const tick = () => toast(`⏳ ${label} (${Math.round((Date.now() - started) / 1000)}s)
File lớn có thể mất 20–40 giây ở lần đọc đầu tiên.`, "", true);
  tick();
  const timer = setInterval(tick, 1000);
  document.body.classList.add("busy");
  try { return await fn(); } finally { clearInterval(timer); document.body.classList.remove("busy"); $("#toast").classList.add("hidden"); }
}
const fail = (e) => toast(`${e.code ? `[${e.code}] ` : ""}${e.message}`, "error");

function show(view) {
  for (const v of ["Home", "Editor", "Preview", "Translate", "Terms"]) $(`#view${v}`).classList.toggle("hidden", v !== view);
}

const STATUS_LABEL = { LOADED: "LOADED", EDITING: "EDITING", REVIEWED: "REVIEWED", READY_TO_PUBLISH: "READY TO PUBLISH", PUBLISHED: "PUBLISHED" };
function setBadge(el, status) { el.textContent = STATUS_LABEL[status] || status || ""; el.className = `badge st-${status}`; }

function alertBox(items, kind = "", title = "") {
  if (!items?.length) return "";
  return `<div class="alert ${kind}">${title ? `<b>${esc(title)}</b>` : ""}<ul>${items.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>`;
}

// ---------------------------------------------------------------- blocks <-> HTML
function runsHtml(runs) {
  return (runs || []).map((r) => {
    let t = esc(r.text).replace(/\n/g, "<br>");
    if (r.u) t = `<u>${t}</u>`;
    if (r.i) t = `<i>${t}</i>`;
    if (r.b) t = `<b>${t}</b>`;
    return t;
  }).join("");
}
function blocksHtml(blocks) {
  return (blocks || []).map((b, i) => {
    const tag = b.type === "heading" ? `h${Math.min(4, (b.level || 1) + 1)}` : "p";
    const style = b.align && b.align !== "left" ? ` style="text-align:${b.align}"` : "";
    return `<${tag} class="blk" data-n="${i + 1}"${style}>${runsHtml(b.runs) || "<br>"}</${tag}>`;
  }).join("");
}

const BLOCK_TAGS = new Set(["P", "DIV", "H1", "H2", "H3", "H4", "H5", "H6", "LI", "BLOCKQUOTE"]);
function collectRuns(node, fmt, runs) {
  for (const c of node.childNodes) {
    if (c.nodeType === Node.TEXT_NODE) {
      const text = c.textContent.replace(/ /g, " ").replace(/​/g, "");
      if (text) runs.push({ text, ...fmt });
    } else if (c.nodeType === Node.ELEMENT_NODE) {
      if (c.tagName === "BR") { runs.push({ text: "\n", ...fmt }); continue; }
      const f = { ...fmt };
      const st = c.style || {};
      if (/^(B|STRONG)$/.test(c.tagName) || /bold|[6-9]00/.test(st.fontWeight)) f.b = true;
      if (/^(I|EM)$/.test(c.tagName) || st.fontStyle === "italic") f.i = true;
      if (c.tagName === "U" || /underline/.test(st.textDecoration || "")) f.u = true;
      if (BLOCK_TAGS.has(c.tagName) && runs.length && !runs[runs.length - 1].text.endsWith("\n")) runs.push({ text: "\n", ...fmt });
      collectRuns(c, f, runs);
    }
  }
}
function normalizeRuns(runs) {
  const out = [];
  for (const r of runs) {
    const prev = out[out.length - 1];
    if (prev && prev.b === r.b && prev.i === r.i && prev.u === r.u) prev.text += r.text;
    else out.push({ text: r.text, b: !!r.b, i: !!r.i, u: !!r.u });
  }
  const last = out[out.length - 1];
  if (last && last.text.endsWith("\n")) { // browser placeholder <br> at the end of a paragraph
    last.text = last.text.slice(0, -1);
    if (!last.text) out.pop();
  }
  return out;
}
function editorToBlocks(root) {
  const blocks = [];
  let loose = [];
  const flushLoose = () => {
    const runs = normalizeRuns(loose);
    if (runs.length) blocks.push({ type: "paragraph", level: null, align: null, runs });
    loose = [];
  };
  for (const node of root.childNodes) {
    if (node.nodeType === Node.ELEMENT_NODE && BLOCK_TAGS.has(node.tagName)) {
      flushLoose();
      const runs = []; collectRuns(node, { b: false, i: false, u: false }, runs);
      const heading = /^H[1-6]$/.test(node.tagName);
      const align = ["center", "right", "justify"].includes(node.style.textAlign) ? node.style.textAlign : null;
      blocks.push({ type: heading ? "heading" : "paragraph", level: heading ? Math.max(1, +node.tagName[1] - 1) : null, align, runs: normalizeRuns(runs) });
    } else {
      const tmp = document.createElement("span"); tmp.appendChild(node.cloneNode(true));
      collectRuns(tmp, { b: false, i: false, u: false }, loose);
    }
  }
  flushLoose();
  return blocks;
}

// ---------------------------------------------------------------- home / projects
const STAT_LABEL = { PUBLISHED: "đã đăng", READY_TO_PUBLISH: "sẵn sàng", REVIEWED: "đã review", EDITING: "đang sửa", LOADED: "đã mở" };
const fmtTime = (iso) => { try { return new Date(iso).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" }); } catch { return iso || ""; } };

async function loadRecent() {
  let list = [];
  try { list = await api("GET", "/api/projects"); } catch { return; }
  $("#recentProjects").innerHTML = `<option value="">Project gần đây…</option>` +
    list.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
  $("#libraryCard").classList.toggle("hidden", !list.length);
  $("#libraryList").innerHTML = list.map((p) => {
    const range = p.chapter_range ? `chương ${p.chapter_range[0]}–${p.chapter_range[1]}` : "";
    const stats = Object.entries(STAT_LABEL).filter(([k]) => p.status_counts?.[k])
      .map(([k, label]) => `<span class="stat"><span class="dot st-${k}"></span>${p.status_counts[k]} ${label}</span>`).join("");
    const missing = p.source_exists ? "" : ` · <span style="color:#c0392b">file gốc không còn ở ${esc(p.source?.path || "")}</span>`;
    return `<div class="lib-item ${S.project?.id === p.id ? "active" : ""}">
      <div class="name">📄 ${esc(p.name)}${p.story ? ` <span class="badge">📚 ${esc(p.story)}</span>` : ""}</div>
      <div class="actions">
        ${p.last_chapter != null ? `<button class="primary small" data-open="${esc(p.id)}" data-ch="${p.last_chapter}">Tiếp tục chương ${p.last_chapter}</button>` : ""}
        <button class="small" data-open="${esc(p.id)}">Mở</button>
      </div>
      <div class="meta">${p.chapter_count ? `${p.chapter_count} ${range}` : ""} ${p.last_opened_at ? `· mở lần cuối ${esc(fmtTime(p.last_opened_at))}` : ""}${missing}<br>${stats}</div>
    </div>`;
  }).join("");
  $("#libraryList").querySelectorAll("button[data-open]").forEach((b) => b.addEventListener("click", async () => {
    await openProject(b.dataset.open);
    if (b.dataset.ch) loadChapter(+b.dataset.ch);
  }));
}

function setIndex(idx) {
  S.index = idx; S.project = idx.project;
  store.set("lastProject", S.project.id);
  $("#fileInfo").textContent = `File: ${S.project.name}` + (S.project.source?.kind === "path" ? ` (${S.project.source.path})` : "");
  $("#chapterCard").classList.remove("hidden");
  $("#docWarnings").innerHTML = alertBox(idx.warnings, "", "Cảnh báo khi đọc file:");
  const list = $("#chapterList");
  if (!idx.chapters.length) { list.innerHTML = `<div class="alert error">Không tìm thấy chương nào trong file.</div>`; return; }
  list.innerHTML = idx.chapters.map((c) => {
    const tip = [c.title, !c.has_ko && "Thiếu bản Hàn", !c.has_vi && "Thiếu bản Việt", ...c.warnings].filter(Boolean).join("\n");
    return `<span class="chip conf-${c.confidence}" data-n="${c.number}" title="${esc(tip)}">${c.status ? `<span class="dot st-${c.status}"></span>` : ""}${c.number}</span>`;
  }).join("");
  list.querySelectorAll(".chip").forEach((el) => el.addEventListener("click", () => loadChapter(+el.dataset.n)));
  show("Home");
  loadRecent();  // refresh library progress / active book
}

async function openProject(id) {
  try { setIndex(await withBusy("Đang đọc file Word…", () => api("GET", `/api/projects/${encodeURIComponent(id)}`))); } catch (e) { fail(e); }
}

async function uploadFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".docx")) return toast("Chỉ hỗ trợ file .docx", "error");
  const fd = new FormData(); fd.append("file", file);
  try {
    const idx = await withBusy(`Đang tải lên và đọc ${file.name}…`, () => api("POST", "/api/projects/upload", fd, true));
    setIndex(idx); toast(`Đã đọc ${file.name}: ${idx.chapters.length} chương`, "ok"); loadRecent();
  } catch (e) { fail(e); }
}

// ---------------------------------------------------------------- editor
const ed = () => $("#viEditor");
const H = { stack: [], idx: -1, timer: null };

function snapshot() {
  clearTimeout(H.timer); H.timer = null;
  const html = ed().innerHTML;
  if (H.stack[H.idx] === html) return;
  H.stack = H.stack.slice(0, H.idx + 1); H.stack.push(html);
  if (H.stack.length > 300) H.stack.shift();
  H.idx = H.stack.length - 1; updateUndoButtons();
}
function resetHistory() { H.stack = [ed().innerHTML]; H.idx = 0; updateUndoButtons(); }
function updateUndoButtons() { $("#undoBtn").disabled = H.idx <= 0; $("#redoBtn").disabled = H.idx >= H.stack.length - 1; }
function undo() { if (H.timer) snapshot(); if (H.idx > 0) { ed().innerHTML = H.stack[--H.idx]; setDirty(true); updateUndoButtons(); } }
function redo() { if (H.idx < H.stack.length - 1) { ed().innerHTML = H.stack[++H.idx]; setDirty(true); updateUndoButtons(); } }

function setDirty(v) { S.dirty = v; $("#dirtyMark").classList.toggle("hidden", !v); }

function renderChapter(ch, { keepEditor = false } = {}) {
  S.chapter = ch;
  $("#titleInput").value = ch.title || "";
  setBadge($("#statusBadge"), ch.status);
  $("#koPane").innerHTML = blocksHtml(ch.ko_blocks) || `<p class="muted">(Không có bản Hàn)</p>`;
  $("#koMeta").textContent = `${ch.ko_heading || ""} · ${ch.ko_blocks.length} đoạn`;
  if (!keepEditor) {
    ed().innerHTML = blocksHtml(ch.draft) || "<p><br></p>";
    resetHistory(); setDirty(false);
  }
  $("#viMeta").textContent = `${ch.vi_heading || ""} · ${ch.draft.length} đoạn`;

  const conf = { high: "", medium: "", low: "Độ tin cậy THẤP — " }[ch.confidence];
  $("#chapterWarnings").innerHTML =
    alertBox(ch.notices, "", "Lưu ý:") +
    alertBox(ch.warnings, ch.confidence === "low" ? "error" : "", `${conf}Cảnh báo tách chương ${ch.number}:`);

  const vr = $("#variantRow");
  if (ch.ko_options > 1 || ch.vi_options > 1) {
    const sel = (name, n, cur) => `<label>${name}: <select data-kind="${name}">${Array.from({ length: n }, (_, i) =>
      `<option value="${i}" ${i === cur ? "selected" : ""}>Phần #${i + 1}</option>`).join("")}</select></label>`;
    vr.innerHTML = `<b>Chương trùng số — chọn phần đúng:</b>` +
      (ch.ko_options > 1 ? sel("Hàn", ch.ko_options, ch.ko_choice) : "") +
      (ch.vi_options > 1 ? sel("Việt", ch.vi_options, ch.vi_choice) : "");
    vr.classList.remove("hidden");
    vr.querySelectorAll("select").forEach((s) => s.addEventListener("change", () => {
      if (S.dirty && !confirm("Đổi phần sẽ tải lại nội dung và bỏ thay đổi chưa lưu. Tiếp tục?")) return renderChapter(S.chapter, { keepEditor: true });
      const ko = +(vr.querySelector('[data-kind="Hàn"]')?.value ?? 0), vi = +(vr.querySelector('[data-kind="Việt"]')?.value ?? 0);
      loadChapter(ch.number, ko, vi);
    }));
  } else vr.classList.add("hidden");

  const ackKey = `ack:${S.project.id}:${ch.number}:${ch.source_hash}:${ch.ko_choice}:${ch.vi_choice}`;
  const locked = ch.confidence === "low" && store.get(ackKey) !== "1";
  $("#lockOverlay").classList.toggle("hidden", !locked);
  ed().contentEditable = locked ? "false" : "true";
  $("#ackBtn").onclick = () => { store.set(ackKey, "1"); $("#lockOverlay").classList.add("hidden"); ed().contentEditable = "true"; };

  renderIssues(ch.issues);
  if (!keepEditor) {
    S.suggestion = null;
    $("#aiResult").innerHTML = `Chọn (bôi đen) một đoạn trong bản Việt rồi bấm <b>✨ Suggest correction</b>. AI chỉ gợi ý — bạn quyết định có Apply hay không.`;
  }
}

async function loadChapter(n, koChoice = 0, viChoice = 0) {
  if (!S.project) return;
  if (S.dirty && S.chapter && S.chapter.number !== n && !confirm("Có thay đổi chưa lưu. Bỏ qua và mở chương khác?")) return;
  try {
    const ch = await api("POST", `/api/projects/${S.project.id}/chapters/${n}/load`, { ko_choice: koChoice, vi_choice: viChoice });
    renderChapter(ch); show("Editor");
    $("#chapterInput").value = n;
    loadGlossary();
  } catch (e) { fail(e); }
}

const chUrl = (suffix = "") => `/api/projects/${S.project.id}/chapters/${S.chapter.number}${suffix}`;

async function saveDraft({ quiet = false } = {}) {
  if (H.timer) snapshot();
  try {
    const ch = await api("PUT", chUrl("/draft"), { blocks: editorToBlocks(ed()), title: $("#titleInput").value });
    S.chapter = ch; setBadge($("#statusBadge"), ch.status); setDirty(false); renderIssues(ch.issues);
    $("#viMeta").textContent = `${ch.vi_heading || ""} · ${ch.draft.length} đoạn`;
    if (!quiet) toast("Đã lưu draft", "ok");
    return true;
  } catch (e) { fail(e); return false; }
}

async function resetDraft() {
  if (!confirm("Reset sẽ thay bản đang sửa bằng bản dịch gốc trong file Word. (Có thể Undo ngay sau đó.) Tiếp tục?")) return;
  if (H.timer) snapshot();
  try {
    const ch = await api("POST", chUrl("/reset"));
    S.chapter = ch;
    ed().innerHTML = blocksHtml(ch.draft) || "<p><br></p>"; snapshot();
    $("#titleInput").value = ch.title; setBadge($("#statusBadge"), ch.status); setDirty(false); renderIssues(ch.issues);
    toast("Đã reset về bản gốc trong Word", "ok");
  } catch (e) { fail(e); }
}

// ---------------------------------------------------------------- issues
function renderIssues(issues = []) {
  $("#issueCount").textContent = issues.length || "";
  $("#issueList").innerHTML = issues.length
    ? issues.map((it) => `<div class="issue ${it.level}" data-b="${it.block ?? ""}">${it.block != null ? `<b>¶${it.block + 1}</b> ` : ""}${esc(it.message)}</div>`).join("")
    : `<p class="muted small">Không có vấn đề nào được phát hiện (theo bản đã lưu).</p>`;
  $("#issueList").querySelectorAll(".issue").forEach((el) => el.addEventListener("click", () => {
    if (el.dataset.b === "") return;
    const blk = ed().children[+el.dataset.b];
    if (blk) { blk.scrollIntoView({ block: "center", behavior: "smooth" }); blk.classList.add("flash"); setTimeout(() => blk.classList.remove("flash"), 1500); }
  }));
}

// ---------------------------------------------------------------- AI suggestion
function paragraphIndexOf(node) {
  let n = node.nodeType === Node.TEXT_NODE ? node.parentNode : node;
  while (n && n.parentNode !== ed()) n = n.parentNode;
  return n ? [...ed().childNodes].indexOf(n) : -1;
}

async function suggest() {
  if (!S.chapter) return;
  let range = S.lastRange;
  if (!range || !ed().contains(range.commonAncestorContainer)) return toast("Hãy chọn (bôi đen) một đoạn trong bản Việt trước.", "error");
  if (range.collapsed) { // no selection -> whole paragraph under the caret
    const idx = paragraphIndexOf(range.startContainer);
    const blk = ed().childNodes[idx];
    if (!blk) return toast("Hãy chọn một đoạn văn bản.", "error");
    range = document.createRange(); range.selectNodeContents(blk);
  }
  const original = range.toString();
  if (!original.trim()) return toast("Đoạn được chọn trống.", "error");
  if (original.length > 4000) return toast("Đoạn chọn quá dài (>4000 ký tự). Hãy chọn ít hơn.", "error");
  const idx = paragraphIndexOf(range.startContainer);
  const paras = [...ed().childNodes].map((n) => n.textContent);
  S.suggestion = { range: range.cloneRange(), original };
  $$(".tabs button").find((b) => b.dataset.tab === "ai").click();
  $("#aiResult").innerHTML = `<div class="muted">⏳ Đang hỏi AI…</div>`;
  $("#suggestBtn").disabled = true;
  try {
    const r = await api("POST", chUrl("/suggest"), {
      selected: original, paragraph_index: idx,
      context_before: paras.slice(Math.max(0, idx - 3), idx), context_after: paras.slice(idx + 1, idx + 4),
      instruction: $("#aiInstruction").value.trim(),
    });
    S.suggestion.result = r;
    $("#aiResult").innerHTML = `<div class="suggest-box">
        <h5>Original</h5><div class="orig">${esc(r.original)}</div>
        <h5>Suggestion ${r.changed ? "" : "(không cần sửa)"}</h5><textarea id="sugText">${esc(r.suggestion)}</textarea>
        <h5>Reason</h5><div class="reason">${esc(r.reason)}</div>
        <div class="row"><button class="primary" id="applyBtn">Apply</button><button id="dismissBtn">Bỏ qua</button>
        <span class="muted small">${esc(r.provider)} ${esc(r.model || "")}</span></div></div>`;
    $("#applyBtn").onclick = applySuggestion;
    $("#dismissBtn").onclick = () => { S.suggestion = null; $("#aiResult").innerHTML = `<div class="muted small">Đã bỏ qua gợi ý.</div>`; };
  } catch (e) {
    $("#aiResult").innerHTML = `<div class="alert error">${e.code ? `<b>[${esc(e.code)}]</b> ` : ""}${esc(e.message)}</div>`;
  } finally { $("#suggestBtn").disabled = false; }
}

function findTextRange(root, text) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const i = node.textContent.indexOf(text);
    if (i >= 0) { const r = document.createRange(); r.setStart(node, i); r.setEnd(node, i + text.length); return r; }
  }
  return null;
}

function applySuggestion() {
  const sg = S.suggestion; if (!sg) return;
  const text = $("#sugText").value;
  let range = sg.range;
  if (!ed().contains(range.commonAncestorContainer) || range.toString() !== sg.original) range = findTextRange(ed(), sg.original);
  if (!range) return toast("Đoạn gốc đã bị thay đổi nên không thể Apply tự động. Hãy sửa thủ công.", "error");
  if (H.timer) snapshot();
  ed().focus();
  const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
  document.execCommand("insertText", false, text);
  snapshot(); setDirty(true);
  S.suggestion = null;
  $("#aiResult").innerHTML = `<div class="muted small">✔ Đã áp dụng gợi ý (Undo để hoàn tác).</div>`;
}

// ---------------------------------------------------------------- glossary
async function loadGlossary() {
  try { S.glossary = await api("GET", `/api/projects/${S.project.id}/glossary`); renderGlossary(); } catch (e) { fail(e); }
}
function renderGlossary() {
  $("#glossaryList").innerHTML = S.glossary.length ? S.glossary.map((g) => `<div class="gl-item">
      <div><span class="src">${esc(g.source)}</span> → <b>${esc(g.target)}</b></div>
      <button data-id="${esc(g.id)}" title="Xoá">✕</button>
      <div class="meta">${g.avoid?.length ? `tránh: ${esc(g.avoid.join(", "))}` : ""} ${esc(g.note || "")}</div></div>`).join("")
    : `<p class="muted small">Chưa có mục nào.</p>`;
  $("#glossaryList").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    saveGlossary(S.glossary.filter((g) => g.id !== b.dataset.id));
  }));
}
async function saveGlossary(entries) {
  try {
    S.glossary = await api("PUT", `/api/projects/${S.project.id}/glossary`, entries);
    renderGlossary(); validateNow();
  } catch (e) { fail(e); }
}
async function validateNow() {
  if (!S.chapter) return;
  try { renderIssues(await api("POST", chUrl("/validate"), { blocks: editorToBlocks(ed()) })); } catch { /* ignore */ }
}

// ---------------------------------------------------------------- preview + publish
async function openPreview() {
  if (S.dirty && !(await saveDraft({ quiet: true }))) return;
  const ch = S.chapter;
  $("#previewNumber").textContent = `Chapter ${ch.number}`;
  $("#previewTitle").textContent = ch.title;
  $("#previewBody").innerHTML = blocksHtml(ch.draft);
  $("#wpTitle").value = $("#wpTitle").dataset.ch === String(ch.number) ? $("#wpTitle").value : ch.title;
  $("#wpTitle").dataset.ch = ch.number;
  $("#wpConfirm").checked = false;
  renderPreviewState();
  show("Preview"); window.scrollTo(0, 0);
  refreshWattpad();
}
function renderPreviewState() {
  const ch = S.chapter;
  setBadge($("#previewStatus"), ch.status);
  $("#reviewBtn").disabled = !["LOADED", "EDITING"].includes(ch.status);
  $("#reviewBtn").textContent = ["LOADED", "EDITING"].includes(ch.status) ? "✔ Đánh dấu đã review" : "✔ Đã review";
  const hist = ch.publish_history || [];
  $("#wpHistory").innerHTML = hist.length ? hist.slice().reverse().map((h) =>
    `<div class="hist-item ${h.ok ? "ok" : "fail"}">${esc(h.at)} — ${h.ok ? "✔" : "✖"} ${esc(h.mode)} “${esc(h.title)}” → ${esc(h.story_title || h.story_id)}
     ${h.part_url ? `<br><a href="${esc(h.part_url)}" target="_blank" rel="noopener">${esc(h.part_url)}</a>` : ""}${h.error ? `<br>${esc(h.error)}` : ""}</div>`).join("")
    : "Chưa có.";
  updatePublishButton();
}
// Everything that still prevents publishing, in plain words (shown under the button).
function publishBlockers() {
  const ch = S.chapter, out = [];
  if (!ch) return ["Chưa mở chương."];
  if (ch.status === "PUBLISHED") out.push("Chương này đã đăng. Muốn đăng lại thì sửa nội dung trước (phần cũ trên Wattpad sẽ được cập nhật).");
  if (!$("#wpStory").value) out.push("Chọn truyện ở ô Story.");
  if (!$("#wpTitle").value.trim()) out.push("Nhập tiêu đề chương.");
  if (!$("#wpConfirm").checked) out.push("Tick “I confirm this is the final version”.");
  if (S.job) out.push("Đang có một thao tác Wattpad chạy — đợi xong hoặc bấm Huỷ.");
  return out;
}
// Ticking the confirmation on the Preview screen counts as the review: no separate click needed.
const needsReview = () => ["LOADED", "EDITING"].includes(S.chapter?.status);

function updatePublishButton() {
  const blockers = publishBlockers();
  $("#wpPublishBtn").disabled = blockers.length > 0;
  $("#wpPublishBtn").textContent = $("#wpMode").value === "draft" ? "Lưu nháp lên Wattpad" : "Publish";
  $("#wpBlockers").innerHTML = blockers.length
    ? `Để bật nút ${$("#wpMode").value === "draft" ? "lưu nháp" : "Publish"}:<ul>${blockers.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>`
    : needsReview() ? "Khi bấm, chương sẽ được đánh dấu đã review rồi đăng." : "";
}

async function markReviewed() {
  try { S.chapter = await api("POST", chUrl("/status"), { event: "review" }); renderPreviewState(); toast("Đã đánh dấu REVIEWED", "ok"); } catch (e) { fail(e); }
}
async function exportDocx() {
  try {
    const r = await api("POST", chUrl("/export"));
    toast(`Đã lưu ${r.filename}\n${r.path}`, "ok");
    const a = document.createElement("a"); a.href = r.download; a.download = r.filename; a.click();
  } catch (e) { fail(e); }
}

async function refreshWattpad() {
  try {
    const st = await api("GET", "/api/wattpad/status");
    S.wp = st;
    const ext = st.mode === "extension";
    $("#wpLoginBtn").textContent = ext ? "Mở Wattpad (Edge của bạn)" : "Đăng nhập Wattpad…";
    $("#wpStoriesBtn").textContent = ext ? "↻ Lấy danh sách từ My Works" : "↻ Tải danh sách truyện";
    if (ext) $("#wpSession").innerHTML = st.extension_connected
      ? `🟢 Extension đã kết nối. Wattpad sẽ được mở ngay trong trình duyệt này (dùng đăng nhập + VPN của bạn).`
      : `⚪ Chưa thấy extension <b>Novel Translator – Wattpad Helper</b>${st.extension_last_seen ? ` (lần cuối ${esc(fmtTime(st.extension_last_seen))})` : ""}.
         Cài 1 lần: mở <code>edge://extensions</code> → bật <i>Developer mode</i> → <i>Load unpacked</i> → chọn thư mục
         <code>extension</code> trong thư mục tool. Sau đó mở một trang Wattpad để extension kết nối.`;
    else $("#wpSession").innerHTML = st.available
      ? (st.logged_in_hint ? "🟢 Đã có phiên đăng nhập lưu trên máy." : "⚪ Chưa đăng nhập Wattpad. Bấm “Đăng nhập Wattpad…” (đăng nhập thủ công trong cửa sổ trình duyệt).")
      : `<span class="alert error">Playwright chưa sẵn sàng: ${esc(st.error || "")}</span>`;
    const cur = $("#wpStory").value || S.project.wattpad?.story_id || "";
    $("#wpStory").innerHTML = `<option value="">— chọn truyện —</option>` +
      (st.stories || []).map((s) => `<option value="${esc(s.id)}" ${s.id === cur ? "selected" : ""}>${esc(s.title)}${s.manual ? " (thêm tay)" : ""}</option>`).join("");
    $("#wpStoriesInfo").innerHTML = (st.stories_updated_at
      ? `Danh sách lưu lúc ${esc(fmtTime(st.stories_updated_at))} (${(st.stories || []).length} truyện) — không cần tải lại mỗi lần.`
      : (st.stories || []).length ? "" : "Chưa có danh sách truyện.")
      + (st.has_snapshot ? ` <a href="/api/wattpad/myworks.png" target="_blank" rel="noopener">Xem ảnh My Works</a>` : "");
  } catch (e) { $("#wpSession").textContent = e.message; }
  updatePublishButton();
}

async function runJob(startPromise, onDone) {
  let job;
  try { job = await startPromise; } catch (e) { fail(e); return; }
  S.job = job.id; updatePublishButton();
  const box = $("#wpJob");
  const tick = async () => {
    try {
      const j = await api("GET", `/api/jobs/${job.id}`);
      box.innerHTML = `${j.state === "running" ? "⏳" : j.state === "done" ? "✔" : "✖"} ${esc(j.message || "")}` +
        (j.log?.length ? `<div class="muted">${j.log.slice(-4).map(esc).join("<br>")}</div>` : "") +
        (j.state === "running" && j.external ? `<button class="small ghost" id="jobCancel">Huỷ</button>` : "");
      $("#jobCancel")?.addEventListener("click", () => api("POST", `/api/jobs/${job.id}/cancel`).catch(fail));
      if (j.state === "running") return setTimeout(tick, 1500);
      S.job = null; updatePublishButton();
      if (j.state === "error") box.innerHTML = `<div class="alert error"><b>${esc(j.error_code || "ERROR")}</b>: ${esc(j.message)}</div>`;
      await onDone?.(j);
    } catch (e) { S.job = null; updatePublishButton(); fail(e); }
  };
  tick();
}

function openMyWorks() {
  window.open(`${S.wp.base}/myworks`, "_blank");
  toast("Đã mở My Works trong tab mới. Extension sẽ gửi danh sách truyện về đây.", "ok");
  let n = 0;
  const poll = async () => { await refreshWattpad(); if (++n < 30) setTimeout(poll, 3000); };
  setTimeout(poll, 3000);
}
function wattpadLogin() {
  if (S.wp?.mode === "extension") return openMyWorks();
  runJob(api("POST", "/api/wattpad/login"), async (j) => {
    if (j.state === "done") toast("Đăng nhập Wattpad thành công", "ok");
    await refreshWattpad();
    if (j.state === "done") fetchStories();
  });
}
function fetchStories() {
  if (S.wp?.mode === "extension") return openMyWorks();
  runJob(api("POST", "/api/wattpad/stories"), async (j) => {
    await refreshWattpad();
    if (j.state === "done" && !(j.result?.stories || []).length) $("#wpManualLink").focus();
  });
}
async function addManualStory(ev) {
  ev.preventDefault();
  const link = $("#wpManualLink").value.trim();
  if (!link) return;
  try {
    const story = await api("POST", "/api/wattpad/stories/manual", { link });
    $("#wpManualLink").value = "";
    await refreshWattpad();
    $("#wpStory").value = story.id; updatePublishButton();
    toast(`Đã thêm truyện “${story.title}” (#${story.id})`, "ok");
  } catch (e) { fail(e); }
}
function publish() {
  const opt = $("#wpStory").selectedOptions[0];
  const mode = $("#wpMode").value;
  const verb = mode === "draft" ? "lưu nháp" : "ĐĂNG CÔNG KHAI";
  if (!confirm(`Xác nhận ${verb} “${$("#wpTitle").value}” lên truyện “${opt.textContent}”?`)) return;
  // Extension mode: the Wattpad tab opens in this same (logged-in) browser. Open it now, inside the
  // click, so the popup blocker allows it; its address is set once the task exists.
  const tab = S.wp?.mode === "extension" ? window.open("about:blank", "_blank") : null;
  const review = needsReview()
    ? api("POST", chUrl("/status"), { event: "review" }).then((ch) => { S.chapter = ch; renderPreviewState(); })
    : Promise.resolve();
  const start = review.then(() => api("POST", chUrl("/publish"), {
    story_id: opt.value, story_title: opt.textContent, title: $("#wpTitle").value.trim(), mode, confirm: $("#wpConfirm").checked,
  })).then((job) => {
    if (tab) { if (job.open_url) tab.location.href = job.open_url; else tab.close(); }
    return job;
  }, (e) => { if (tab) tab.close(); throw e; });
  runJob(start, async (j) => {
    S.chapter = await api("GET", chUrl());
    renderPreviewState();
    if (j.state === "done") toast(mode === "draft" ? "Đã lưu nháp lên Wattpad" : "Đăng chương thành công 🎉", "ok");
  });
}

// ---------------------------------------------------------------- wiring
function init() {
  document.execCommand("defaultParagraphSeparator", false, "p");

  $("#fileInput").addEventListener("change", (e) => uploadFile(e.target.files[0]));
  const dz = $("#dropzone");
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
  dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("drag"); uploadFile(e.dataTransfer.files[0]); });
  $("#pathForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const idx = await withBusy("Đang đọc file Word…", () => api("POST", "/api/projects/open", { path: $("#pathInput").value }));
      setIndex(idx); toast(`Đã đọc ${idx.project.name}: ${idx.chapters.length} chương`, "ok"); loadRecent();
    } catch (err) { fail(err); }
  });
  $("#recentProjects").addEventListener("change", (e) => e.target.value && openProject(e.target.value));
  $("#reloadBtn").addEventListener("click", () => S.project && openProject(S.project.id));
  $("#chapterForm").addEventListener("submit", (e) => { e.preventDefault(); loadChapter(+$("#chapterInput").value); });

  $("#backHome").addEventListener("click", () => {
    if (S.dirty && !confirm("Có thay đổi chưa lưu. Rời trang sửa?")) return;
    setDirty(false); openProject(S.project.id);
  });
  $("#saveBtn").addEventListener("click", () => saveDraft());
  $("#undoBtn").addEventListener("click", undo);
  $("#redoBtn").addEventListener("click", redo);
  $("#resetBtn").addEventListener("click", resetDraft);
  $("#boldBtn").addEventListener("click", () => { ed().focus(); document.execCommand("bold"); });
  $("#italicBtn").addEventListener("click", () => { ed().focus(); document.execCommand("italic"); });
  $("#suggestBtn").addEventListener("click", suggest);
  $("#previewBtn").addEventListener("click", openPreview);
  $("#titleInput").addEventListener("input", () => setDirty(true));

  const e = ed();
  e.addEventListener("input", () => { setDirty(true); clearTimeout(H.timer); H.timer = setTimeout(snapshot, 500); });
  e.addEventListener("keydown", (ev) => {
    const mod = ev.ctrlKey || ev.metaKey;
    if (!mod) return;
    const k = ev.key.toLowerCase();
    if (k === "z" && !ev.shiftKey) { ev.preventDefault(); undo(); }
    else if (k === "y" || (k === "z" && ev.shiftKey)) { ev.preventDefault(); redo(); }
  });
  e.addEventListener("paste", (ev) => { // plain-text paste keeps Word/HTML junk out of the draft
    ev.preventDefault();
    document.execCommand("insertText", false, ev.clipboardData.getData("text/plain"));
  });
  document.addEventListener("selectionchange", () => {
    const sel = window.getSelection();
    if (sel.rangeCount && e.contains(sel.anchorNode)) S.lastRange = sel.getRangeAt(0).cloneRange();
  });
  document.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s" && !$("#viewEditor").classList.contains("hidden")) { ev.preventDefault(); saveDraft(); }
  });

  // proportional scroll sync between Korean and Vietnamese panes
  let syncing = false;
  const sync = (from, to) => from.addEventListener("scroll", () => {
    if (syncing) { syncing = false; return; }
    const max = from.scrollHeight - from.clientHeight;
    syncing = true; to.scrollTop = max > 0 ? (from.scrollTop / max) * (to.scrollHeight - to.clientHeight) : 0;
  });
  sync($("#koPane"), e); sync(e, $("#koPane"));

  $$(".tabs button").forEach((b) => b.addEventListener("click", () => {
    $$(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
    $$(".tab").forEach((t) => t.classList.toggle("hidden", t.id !== `tab-${b.dataset.tab}`));
    if (b.dataset.tab === "issues") validateNow();
  }));
  $("#glossaryForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    const entry = { source: f.get("source"), target: f.get("target"), note: f.get("note") || "",
      avoid: String(f.get("avoid") || "").split(",").map((s) => s.trim()).filter(Boolean) };
    const rest = S.glossary.filter((g) => g.source !== entry.source.trim());
    saveGlossary([...rest, entry]); ev.target.reset();
  });

  $("#previewBack").addEventListener("click", () => { renderChapter(S.chapter); show("Editor"); });
  $("#reviewBtn").addEventListener("click", markReviewed);
  $("#exportBtn").addEventListener("click", exportDocx);
  $("#wpLoginBtn").addEventListener("click", wattpadLogin);
  $("#wpStoriesBtn").addEventListener("click", fetchStories);
  $("#wpManualForm").addEventListener("submit", addManualStory);
  for (const id of ["#wpConfirm", "#wpStory", "#wpMode", "#wpTitle"]) $(id).addEventListener("input", updatePublishButton);
  $("#wpPublishBtn").addEventListener("click", publish);

  window.addEventListener("beforeunload", (ev) => { if (S.dirty) { ev.preventDefault(); ev.returnValue = ""; } });
  setInterval(() => { if (S.dirty && !$("#viewEditor").classList.contains("hidden")) saveDraft({ quiet: true }); }, 60000);

  api("GET", "/api/ai/status").then((s) => {
    $("#aiState").textContent = s.enabled ? `AI: ${s.provider} · ${s.model}` : "AI: chưa cấu hình (.env)";
    $("#aiState").title = s.enabled ? "" : s.reason || "";
  }).catch(() => {});
  loadRecent();
  // Resume where the user left off: last book + the chapter being worked on.
  const last = store.get("lastProject");
  if (last) openProject(last).then(() => {
    const ch = S.project?.id === last ? S.project.last_chapter : null;
    if (ch != null && S.index?.chapters.some((c) => c.number === ch)) loadChapter(ch);
  }).catch(() => {});
}

init();
