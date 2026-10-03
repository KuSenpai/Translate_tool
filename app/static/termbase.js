// Termbase screen: user data import, story notes, AI scan of old chapters, proposal review, consistency check.
const $ = (s) => document.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const B = { pid: null, data: null, check: null, poll: null, models: [] };

async function api(method, url, body, isForm = false) {
  const res = await fetch(url, {
    method, headers: body && !isForm ? { "Content-Type": "application/json" } : {},
    body: isForm ? body : body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw Object.assign(new Error(data?.error?.message || `HTTP ${res.status}`), { code: data?.error?.code });
  return data;
}
function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg; t.className = `toast ${kind}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), kind === "error" ? 9000 : 4000);
}
const fail = (e) => toast(`${e.code ? `[${e.code}] ` : ""}${e.message}`, "error");
const usd = (n) => `$${Number(n || 0).toFixed(2)}`;
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } } };

async function showView() {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== "viewTerms"));
  try {
    const [projects, info] = await Promise.all([api("GET", "/api/projects"), api("GET", "/api/translate/info")]);
    B.models = info.models;
    $("#tbModel").innerHTML = info.models.map((m) => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join("");
    if (!projects.length) {
      $("#tbProject").innerHTML = "";
      return toast("Chưa có truyện nào — hãy mở file Word song ngữ (các chương cũ đã dịch) ở trang chương trước.", "error");
    }
    const cur = B.pid || store.get("lastProject") || projects[0].id;
    $("#tbProject").innerHTML = projects.map((p) => `<option value="${esc(p.id)}" ${p.id === cur ? "selected" : ""}>${p.story ? `📚 ${esc(p.story)} · ` : ""}${esc(p.name)}${p.chapter_count ? ` (${p.chapter_count} chương)` : ""}</option>`).join("");
    B.projects = projects;
    await load($("#tbProject").value);
  } catch (e) { fail(e); }
}

async function load(pid) {
  B.pid = pid; B.check = null;
  B.data = await api("GET", `/api/projects/${pid}/termbase`);
  $("#tbNotes").value = B.data.notes || "";
  const p = (B.projects || []).find((x) => x.id === pid);
  if (p?.chapter_range && !$("#tbFrom").value) {
    $("#tbFrom").value = Math.max(p.chapter_range[0], p.chapter_range[1] - 29);
    $("#tbTo").value = p.chapter_range[1];
  }
  renderStory();
  renderScan(); renderProposals(); renderTable(); estimate();
}

function renderStory() {
  const s = B.data.story;
  $("#tbStory").innerHTML = s
    ? `📚 Kho dùng chung cho truyện <b>${esc(s.name)}</b> — ${s.projects.length} file:
       ${s.projects.map((p) => `${esc(p.name)}${p.chapter_range ? ` (${p.chapter_range[0]}–${p.chapter_range[1]})` : ""}`).join(", ")}.
       Quét/kiểm tra nhất quán chạy trên tất cả các file này.`
    : `File này chưa thuộc truyện nào. <input id="tbStoryName" placeholder="Tên truyện, vd: Into Creation" style="width:220px">
       <button class="small" id="tbStorySet">Gắn vào truyện</button>
       <span class="muted">— các file cùng truyện dùng chung một kho thuật ngữ.</span>`;
  $("#tbStorySet")?.addEventListener("click", async () => {
    const name = $("#tbStoryName").value.trim();
    if (!name) return;
    try { await api("PUT", `/api/projects/${B.pid}/story`, { name }); toast(`Đã gắn vào truyện “${name}”`, "ok"); await showView(); } catch (e) { fail(e); }
  });
}

// ---------------------------------------------------------------- 1. data / 2. notes
async function importData() {
  const file = $("#tbFile").files[0], text = $("#tbPaste").value.trim(), overwrite = $("#tbOverwrite").checked;
  if (!file && !text) return toast("Chọn file hoặc dán data trước.", "error");
  try {
    let r;
    if (file) {
      const fd = new FormData(); fd.append("file", file);
      r = await api("POST", `/api/projects/${B.pid}/termbase/import?overwrite=${overwrite}`, fd, true);
    } else {
      r = await api("POST", `/api/projects/${B.pid}/termbase/import-text`, { text, overwrite });
    }
    toast(`Đã nhập: +${r.added} thuật ngữ, cập nhật ${r.updated}, ${r.notes_lines} dòng ghi chú`, "ok");
    $("#tbFile").value = ""; $("#tbPaste").value = "";
    await load(B.pid);
  } catch (e) { fail(e); }
}
async function saveNotes() {
  try { await api("PUT", `/api/projects/${B.pid}/termbase/notes`, { notes: $("#tbNotes").value }); toast("Đã lưu ghi chú truyện", "ok"); } catch (e) { fail(e); }
}

// ---------------------------------------------------------------- 3. AI scan
async function estimate() {
  if (!B.pid) return;
  const q = new URLSearchParams();
  if ($("#tbFrom").value) q.set("from_number", $("#tbFrom").value);
  if ($("#tbTo").value) q.set("to_number", $("#tbTo").value);
  try {
    const e = await api("GET", `/api/projects/${B.pid}/termbase/scan-estimate?${q}`);
    B.est = e;
    const m = B.models.find((x) => x.id === $("#tbModel").value) || {};
    $("#tbEstimate").textContent = `${e.chapters} chương song ngữ · ${e.batches} lượt gọi · ` +
      (m.provider === "antigravity" ? "dùng hạn mức Gemini của Antigravity (không tính tiền API)"
        : m.subscription ? "dùng lượt của gói Claude (không tính tiền API)" : `ước tính ~${usd(e.estimate[$("#tbModel").value])}`);
    $("#tbScan").disabled = !e.chapters;
  } catch (err) { $("#tbEstimate").textContent = err.message; }
}
async function startScan() {
  if (!confirm(`Quét ${B.est?.chapters || ""} chương bằng ${$("#tbModel").selectedOptions[0].textContent}?\n${$("#tbEstimate").textContent}`)) return;
  try {
    B.data.scan = await api("POST", `/api/projects/${B.pid}/termbase/scan`, {
      model: $("#tbModel").value, from_number: $("#tbFrom").value ? +$("#tbFrom").value : null, to_number: $("#tbTo").value ? +$("#tbTo").value : null,
    });
    renderScan(); pollScan();
  } catch (e) { fail(e); }
}
async function pollScan() {
  clearTimeout(B.poll);
  try {
    B.data = await api("GET", `/api/projects/${B.pid}/termbase`);
    renderScan(); renderProposals();
    if (B.data.scan.running && !$("#viewTerms").classList.contains("hidden")) B.poll = setTimeout(pollScan, 2000);
  } catch (e) { fail(e); }
}
function renderScan() {
  const s = B.data?.scan || {};
  $("#tbScanStop").classList.toggle("hidden", !s.running);
  $("#tbScan").classList.toggle("hidden", !!s.running);
  if (!s.status) { $("#tbScanState").innerHTML = ""; return; }
  const pct = s.batches_total ? Math.round((100 * s.batches_done) / s.batches_total) : 0;
  $("#tbScanState").innerHTML = `<div class="tr-bar"><span style="width:${pct}%;background:#3b82f6"></span></div>
    ${s.running ? "⏳" : s.status === "done" ? "✔" : "•"} ${esc(s.message || "")} · chương ${s.from}–${s.to} · ${esc(s.model)} · đã tốn ${usd(s.cost_usd)}
    ${(s.errors || []).length ? `<div class="alert error"><ul>${s.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>` : ""}`;
  if (s.running) { clearTimeout(B.poll); B.poll = setTimeout(pollScan, 2000); }
}

// ---------------------------------------------------------------- 4. proposals
function catSelect(value, attrs = "") {
  const cats = B.data?.categories || {};
  return `<select ${attrs}>${Object.entries(cats).map(([k, v]) => `<option value="${k}" ${k === value ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
}
function renderProposals() {
  const props = B.data?.proposals || [];
  $("#tbPropCount").textContent = props.length || "";
  if (!props.length) { $("#tbProps").innerHTML = `<span class="muted">Chưa có đề xuất.</span>`; return; }
  $("#tbProps").innerHTML = `<div class="tb-scroll"><table class="tb-table"><thead><tr>
      <th><input type="checkbox" id="tbPropAll" checked></th><th>Tiếng Hàn</th><th>Cách dịch (sửa được)</th><th>Loại</th>
      <th>Cách dịch khác đã gặp</th><th>Nguồn</th></tr></thead><tbody>${props.map((p) => `<tr data-src="${esc(p.source)}">
      <td><input type="checkbox" class="sel" checked></td><td class="ko">${esc(p.source)}</td>
      <td><input type="text" class="tgt" value="${esc(p.target)}"></td><td>${catSelect(p.category, 'class="cat"')}</td>
      <td>${p.variants?.length ? `<span style="color:#c07a00">${esc(p.variants.join(" · "))}</span>` : `<span class="muted">—</span>`}</td>
      <td class="muted">${p.origin === "translation" ? "khi dịch" : "quét"}${p.chapters?.length ? ` · ${p.chapters.length} chương` : ""}</td></tr>`).join("")}
    </tbody></table></div>`;
  $("#tbPropAll").addEventListener("change", (e) => $("#tbProps").querySelectorAll(".sel").forEach((c) => { c.checked = e.target.checked; }));
}
async function decide(accept) {
  const rows = [...$("#tbProps").querySelectorAll("tr[data-src]")].filter((r) => r.querySelector(".sel").checked);
  if (!rows.length) return toast("Chưa chọn đề xuất nào.", "error");
  const body = accept
    ? { accept: rows.map((r) => ({ source: r.dataset.src, target: r.querySelector(".tgt").value, category: r.querySelector(".cat").value })), reject: [] }
    : { accept: [], reject: rows.map((r) => r.dataset.src) };
  try {
    const r = await api("POST", `/api/projects/${B.pid}/termbase/proposals`, body);
    toast(accept ? `Đã thêm ${r.added} thuật ngữ vào kho` : "Đã bỏ qua", "ok");
    await load(B.pid);
  } catch (e) { fail(e); }
}

// ---------------------------------------------------------------- 5. glossary + consistency
function pctCell(p) {
  if (p == null) return `<span class="muted">—</span>`;
  return `<span class="pct ${p >= 90 ? "good" : p >= 60 ? "mid" : "bad"}">${p}%</span>`;
}
function renderTable() {
  const g = B.data?.glossary || [];
  $("#tbCount").textContent = g.length || "";
  const stats = Object.fromEntries((B.check?.rows || []).map((r) => [r.id, r]));
  const f = $("#tbFilter").value.trim().toLowerCase();
  let rows = g.filter((e) => !f || `${e.source} ${e.target} ${e.note || ""}`.toLowerCase().includes(f));
  if (B.check) rows.sort((a, b) => ((stats[a.id]?.consistency ?? 101) - (stats[b.id]?.consistency ?? 101)) || ((stats[b.id]?.chapters || 0) - (stats[a.id]?.chapters || 0)));
  if (!g.length) { $("#tbTable").innerHTML = `<p class="muted small">Kho trống — nhập data hoặc quét chương cũ.</p>`; return; }
  $("#tbTable").innerHTML = `<div class="tb-scroll"><table class="tb-table"><thead><tr><th>Tiếng Hàn</th><th>Cách dịch</th><th>Loại</th>
      <th>Tránh dùng</th>${B.check ? "<th>Số chương</th><th>Nhất quán</th><th>Chương lệch</th>" : ""}<th></th></tr></thead><tbody>
    ${rows.map((e) => { const s = stats[e.id]; return `<tr data-id="${esc(e.id)}">
      <td class="ko">${esc(e.source)}</td><td><input type="text" class="tgt" value="${esc(e.target)}"></td>
      <td>${catSelect(e.category || "other", 'class="cat"')}</td>
      <td><input type="text" class="avoid" value="${esc((e.avoid || []).join(", "))}" placeholder="—"></td>
      ${B.check ? `<td>${s ? s.chapters : "—"}</td><td>${s ? pctCell(s.consistency) : "—"}${s && Object.keys(s.variants).length
        ? `<div class="muted">${Object.entries(s.variants).map(([v, n]) => `${esc(v)}: ${n}`).join(", ")}</div>` : ""}</td>
        <td class="muted">${s?.deviating_total ? esc(s.deviating_chapters.join(", ")) + (s.deviating_total > s.deviating_chapters.length ? "…" : "") : "—"}</td>` : ""}
      <td><button class="small ghost del" title="Xoá">✕</button></td></tr>`; }).join("")}
    </tbody></table></div>
    <div class="row" style="margin-top:6px"><span class="muted small">Sửa trực tiếp trong bảng rồi bấm Lưu. “Tránh dùng”: các cách dịch cũ không còn dùng (phân tách bằng dấu phẩy) — editor sẽ cảnh báo khi gặp.</span>
      <span class="spacer"></span><button class="primary small" id="tbSave">💾 Lưu kho</button></div>`;
  $("#tbTable").querySelectorAll(".del").forEach((b) => b.addEventListener("click", () => {
    const id = b.closest("tr").dataset.id;
    B.data.glossary = B.data.glossary.filter((e) => e.id !== id); renderTable();
  }));
  $("#tbSave").addEventListener("click", saveTable);
  const c = B.check?.candidates || [];
  $("#tbCandidates").innerHTML = c.length ? `<h4 class="small">Từ trong ngoặc [ ] 「 」 『 』 lặp lại nhiều chương nhưng chưa có trong kho (bấm để thêm):</h4>
    ${c.map((x) => `<span class="tb-cand" data-src="${esc(x.source)}" title="${x.chapters} chương">${esc(x.source)} <span class="muted">${x.chapters}</span></span>`).join("")}` : "";
  $("#tbCandidates").querySelectorAll(".tb-cand").forEach((el) => el.addEventListener("click", () => addCandidate(el.dataset.src)));
}
function collectTable() {
  const byId = Object.fromEntries((B.data.glossary || []).map((e) => [e.id, e]));
  $("#tbTable").querySelectorAll("tr[data-id]").forEach((r) => {
    const e = byId[r.dataset.id];
    if (!e) return;
    e.target = r.querySelector(".tgt").value.trim() || e.target;
    e.category = r.querySelector(".cat").value;
    e.avoid = r.querySelector(".avoid").value.split(",").map((s) => s.trim()).filter(Boolean);
  });
  return B.data.glossary;
}
async function saveTable() {
  try {
    B.data.glossary = await api("PUT", `/api/projects/${B.pid}/glossary`, collectTable());
    toast("Đã lưu kho thuật ngữ", "ok");
    if (B.check) runCheck(); else renderTable();
  } catch (e) { fail(e); }
}
async function addCandidate(src) {
  const target = prompt(`Cách dịch tiếng Việt cho “${src}”:`);
  if (!target) return;
  B.data.glossary.push({ source: src, target, category: "skill", avoid: [], note: "", origin: "manual" });
  await saveTable();
}
async function runCheck() {
  $("#tbCheckInfo").textContent = "Đang kiểm tra…";
  try {
    B.check = await api("POST", `/api/projects/${B.pid}/termbase/check`);
    const bad = B.check.rows.filter((r) => r.consistency != null && r.consistency < 90).length;
    $("#tbCheckInfo").innerHTML = `Đã kiểm tra ${B.check.chapters_checked} chương song ngữ. ${bad
      ? `<b style="color:#c0392b">${bad} thuật ngữ dịch chưa thống nhất</b> (xếp lên đầu bảng).` : "Mọi thuật ngữ đều nhất quán ≥ 90%."}`;
    renderTable();
  } catch (e) { $("#tbCheckInfo").textContent = e.message; }
}

// ---------------------------------------------------------------- wiring
$("#navTerms").addEventListener("click", showView);
$("#tbBack").addEventListener("click", () => {
  clearTimeout(B.poll);
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== "viewHome"));
});
$("#tbProject").addEventListener("change", (e) => { $("#tbFrom").value = ""; $("#tbTo").value = ""; load(e.target.value).catch(fail); });
$("#tbImport").addEventListener("click", importData);
$("#tbNotesSave").addEventListener("click", saveNotes);
for (const id of ["#tbFrom", "#tbTo", "#tbModel"]) $(id).addEventListener("change", estimate);
$("#tbScan").addEventListener("click", startScan);
$("#tbScanStop").addEventListener("click", async () => { try { await api("POST", `/api/projects/${B.pid}/termbase/scan/cancel`); toast("Sẽ dừng sau lượt hiện tại"); } catch (e) { fail(e); } });
$("#tbAcceptSel").addEventListener("click", () => decide(true));
$("#tbRejectSel").addEventListener("click", () => decide(false));
$("#tbCheck").addEventListener("click", runCheck);
$("#tbFilter").addEventListener("input", () => { if (B.data) { collectTable(); renderTable(); } });
