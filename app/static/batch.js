// "📤 Đăng nhiều chương lên Wattpad" card on the home screen: pick a range of chapters, the tool publishes them
// one after another through the Wattpad Helper extension (see app/publishing/publish_service.py → publish_batch).
const $ = (s) => document.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(method, url, body) {
  let res;
  try {
    res = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw Object.assign(new Error("Không kết nối được tới server local. Server còn chạy không?"), { code: "NETWORK" });
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw Object.assign(new Error(data?.error?.message || `HTTP ${res.status}`), { code: data?.error?.code });
  return data;
}

const B = { idx: null, wp: null, plan: null, timer: null, batchId: null };
const fmtRange = (nums) => { // [10,11,12,15] → "10-12, 15" (runs of neighbours in the chapter list)
  const all = (B.idx?.chapters || []).map((c) => c.number);
  const pos = new Map(all.map((n, i) => [n, i]));
  const out = [];
  for (let i = 0; i < nums.length; i++) {
    let j = i;
    while (j + 1 < nums.length && pos.get(nums[j + 1]) === pos.get(nums[j]) + 1) j++;
    out.push(j > i ? `${nums[i]}-${nums[j]}` : `${nums[i]}`);
    i = j;
  }
  return out.join(", ");
};

// "12-20, 25" → chapters of the open file that are in the ranges. A single number that does not exist is an error;
// a range simply takes the chapters that exist inside it.
function parseRange(text) {
  const have = new Map((B.idx?.chapters || []).map((c) => [c.number, c]));
  const picked = new Set(), errors = [];
  for (const tok of text.split(/[,;\s]+/).filter(Boolean)) {
    const m = tok.match(/^(\d+)(?:[-–—](\d+))?$/);
    if (!m) { errors.push(`Không hiểu “${tok}” — viết dạng 12-20, 25.`); continue; }
    const a = +m[1], b = m[2] ? +m[2] : a;
    if (a > b) { errors.push(`Khoảng “${tok}” bị ngược.`); continue; }
    if (!m[2] && !have.has(a)) { errors.push(`Không có chương ${a} trong file.`); continue; }
    for (const n of have.keys()) if (n >= a && n <= b) picked.add(n);
  }
  return { numbers: [...picked].sort((x, y) => x - y), errors };
}

// Everything that prevents starting, in plain words; also the chapters that will be skipped.
function plan() {
  const { numbers, errors } = parseRange($("#bpRange").value);
  const have = new Map((B.idx?.chapters || []).map((c) => [c.number, c]));
  const todo = [], skipped = [], blockers = [...errors];
  for (const n of numbers) {
    const c = have.get(n);
    if (c.status === "PUBLISHED") { skipped.push(n); continue; }
    if (!c.has_vi) { blockers.push(`Chương ${n} thiếu bản Việt.`); continue; }
    if (c.confidence === "low" && (!c.status || c.status === "LOADED")) {
      blockers.push(`Chương ${n}: parser không chắc ranh giới chương — mở chương này trong editor để kiểm tra trước.`);
      continue;
    }
    todo.push(n);
  }
  if (!$("#bpStory").value) blockers.push("Chọn truyện ở ô Truyện trên Wattpad.");
  if (!numbers.length && !errors.length) blockers.push("Nhập các chương cần đăng, ví dụ 12-20.");
  else if (!todo.length && !blockers.length) blockers.push("Tất cả các chương đã chọn đều đã đăng rồi.");
  if (!$("#bpConfirm").checked) blockers.push("Tick “Tôi xác nhận các chương này là bản cuối cùng”.");
  if (B.batchId && B.running) blockers.push("Đang có một đợt đăng chạy — đợi xong hoặc bấm Huỷ đợt đăng.");
  return { todo, skipped, blockers };
}

function updatePlan() {
  const p = B.plan = plan();
  const draft = $("#bpMode").value === "draft";
  $("#bpStart").disabled = p.blockers.length > 0;
  $("#bpStart").textContent = p.todo.length ? `${draft ? "Lưu nháp" : "Đăng"} ${p.todo.length} chương` : (draft ? "Lưu nháp" : "Đăng");
  $("#bpCount").textContent = p.todo.length
    ? `Sẽ ${draft ? "lưu nháp" : "đăng"} ${p.todo.length} chương: ${fmtRange(p.todo)}${p.skipped.length ? ` · bỏ qua ${p.skipped.length} chương đã đăng (${fmtRange(p.skipped)})` : ""}`
    : "";
  $("#bpBlockers").innerHTML = p.blockers.length
    ? `Để bật nút:<ul>${p.blockers.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : "";
}

const staleExtension = (st) => st.extension_connected && st.extension_version !== st.extension_expected
  ? `<div class="alert error">⚠ Extension đang chạy bản <b>${esc(st.extension_version)}</b>, tool cần <b>${esc(st.extension_expected)}</b>.
     Mở <code>edge://extensions</code> → bấm <b>Tải lại (⟳)</b> ở “Novel Translator – Wattpad Helper” → F5 các tab Wattpad.
     Bản cũ sẽ không đăng đúng được.</div>` : "";

async function refreshWattpad() {
  try {
    const st = B.wp = await api("GET", "/api/wattpad/status");
    const cur = $("#bpStory").value || B.idx?.project?.wattpad?.story_id || "";
    $("#bpStory").innerHTML = `<option value="">— chọn truyện —</option>` +
      (st.stories || []).map((s) => `<option value="${esc(s.id)}" ${s.id === cur ? "selected" : ""}>${esc(s.title)}${s.manual ? " (thêm tay)" : ""}</option>`).join("");
    $("#bpExt").innerHTML = st.mode !== "extension" ? "" : st.extension_connected
      ? staleExtension(st) + `🟢 Extension đã kết nối. Tool sẽ mở một tab Wattpad và đăng lần lượt từng chương trong đó.
         <b>Giữ tab đó mở và hiển thị</b> (đừng thu nhỏ cửa sổ) cho tới khi xong.`
      : `⚪ Chưa thấy extension <b>Novel Translator – Wattpad Helper</b> — cài theo hướng dẫn trong README rồi mở một trang Wattpad để nó kết nối.`;
    if (!(st.stories || []).length) {
      $("#bpExt").innerHTML += `<div class="muted">Chưa có danh sách truyện: mở một chương → Preview → “Lấy danh sách từ My Works”,
        hoặc thêm truyện bằng link ở đó.</div>`;
    }
  } catch { /* the rest of the card still works */ }
  updatePlan();
}

// ---------------------------------------------------------------- progress
const ICON = { queued: "⏳", running: "▶", done: "✔", failed: "✖", skipped: "⏭", cancelled: "⛔" };
const STATE = { queued: "chờ", running: "đang đăng", done: "xong", failed: "lỗi", skipped: "bỏ qua", cancelled: "đã huỷ" };

function renderBatch(b) {
  B.running = b.state === "running";
  const done = b.items.filter((i) => i.state === "done").length;
  const cls = b.state === "error" ? "error" : "";
  $("#bpProgress").innerHTML = `<div class="bp-head ${cls}">
      <b>${esc(b.story_title || "Truyện #" + b.story_id)}</b> · ${b.mode === "draft" ? "lưu nháp" : "đăng"} ·
      ${done}/${b.items.length} chương
      ${B.running ? `<button class="small ghost" id="bpCancel">Huỷ đợt đăng</button>` : ""}
      <div class="${b.state === "error" ? "alert error" : "muted"}">${esc(b.message || "")}</div>
    </div>
    <table class="bp-table"><tbody>${b.items.map((i) => `<tr class="bp-${i.state}">
      <td>${ICON[i.state] || ""}</td><td>Chương ${i.number}</td><td>${esc(i.title)}</td>
      <td>${STATE[i.state] || i.state}${i.part_url && i.state === "done" ? ` · <a href="${esc(i.part_url)}" target="_blank" rel="noopener">xem</a>` : ""}
        ${i.state === "failed" || (i.message && i.state === "skipped") ? `<div class="small">${esc(i.message)}</div>` : ""}</td></tr>`).join("")}</tbody></table>
    ${b.skipped?.length ? `<div class="muted small">Đã bỏ qua (đã đăng trước đó): ${esc(fmtRange(b.skipped.map((s) => s.number)))}</div>` : ""}
    ${b.state === "error" ? `<div class="small">Các chương chưa đăng vẫn giữ nguyên. Sửa lỗi rồi bấm đăng lại cùng khoảng chương:
      chương lỗi sẽ cập nhật đúng phần đã tạo, không bị tạo trùng.</div>` : ""}`;
  $("#bpCancel")?.addEventListener("click", cancelBatch);
  updatePlan();
}

async function pollBatch() {
  clearTimeout(B.timer);
  let b;
  try { b = (await api("GET", "/api/wattpad/batch")).batch; } catch { B.timer = setTimeout(pollBatch, 3000); return; }
  if (!b || (B.idx && b.pid !== B.idx.project.id)) { B.running = false; updatePlan(); return; }
  B.batchId = b.id;
  renderBatch(b);
  if (b.state === "running") { B.watching = b.id; B.timer = setTimeout(pollBatch, 1500); return; }
  if (B.watching === b.id) { // the user saw this batch run: report once and refresh chapter statuses
    B.watching = null;
    document.dispatchEvent(new CustomEvent("nt:toast", { detail: { msg: b.message, kind: b.state === "done" ? "ok" : "error" } }));
    document.dispatchEvent(new CustomEvent("nt:reload-project"));
  }
}

async function cancelBatch() {
  try { renderBatch((await api("POST", `/api/wattpad/batch/${B.batchId}/cancel`)).batch); } catch (e) { alert(e.message); }
}

async function start() {
  const p = plan();
  if (p.blockers.length) return updatePlan();
  const opt = $("#bpStory").selectedOptions[0];
  const draft = $("#bpMode").value === "draft";
  if (!confirm(`${draft ? "Lưu nháp" : "ĐĂNG CÔNG KHAI"} ${p.todo.length} chương (${fmtRange(p.todo)}) lên truyện “${opt.textContent}”?\n\n` +
    "Các chương được đăng lần lượt, mỗi chương cách nhau vài giây. Bạn có thể huỷ bất cứ lúc nào; chương đã đăng không bị gỡ.")) return;
  // Extension mode: the Wattpad tab opens in this same (logged-in) browser. Open it now, inside the click, so the
  // popup blocker allows it; its address is set once the batch exists.
  const tab = B.wp?.mode === "extension" ? window.open("about:blank", "_blank") : null;
  $("#bpStart").disabled = true;
  try {
    const b = await api("POST", `/api/projects/${encodeURIComponent(B.idx.project.id)}/publish-batch`, {
      story_id: opt.value, story_title: opt.textContent, chapters: p.todo, mode: $("#bpMode").value, confirm: true,
    });
    if (tab) { if (b.open_url) tab.location.href = b.open_url; else tab.close(); }
    B.watching = b.id; B.batchId = b.id;
    renderBatch(b);
    pollBatch();
  } catch (e) {
    if (tab) tab.close();
    $("#bpProgress").innerHTML = `<div class="alert error"><b>${esc(e.code || "ERROR")}</b>: ${esc(e.message).replace(/\n/g, "<br>")}</div>`;
    updatePlan();
  }
}

// ---------------------------------------------------------------- wiring
function onIndex(idx) {
  const samePrj = B.idx?.project?.id === idx.project.id;
  B.idx = idx;
  $("#batchCard").classList.remove("hidden");
  if (!samePrj) { $("#bpRange").value = ""; $("#bpProgress").innerHTML = ""; B.batchId = null; B.running = false; }
  refreshWattpad();
  pollBatch();
}

document.addEventListener("nt:index", (e) => onIndex(e.detail));
if (window.__ntIndex) onIndex(window.__ntIndex);

for (const id of ["#bpStory", "#bpRange", "#bpMode", "#bpConfirm"]) $(id).addEventListener("input", updatePlan);
$("#bpUnpublished").addEventListener("click", () => {
  const nums = (B.idx?.chapters || []).filter((c) => c.has_vi && c.status !== "PUBLISHED").map((c) => c.number);
  $("#bpRange").value = fmtRange(nums);
  updatePlan();
});
$("#bpStart").addEventListener("click", start);
$("#batchCard").addEventListener("toggle", () => { if ($("#batchCard").open) refreshWattpad(); });
