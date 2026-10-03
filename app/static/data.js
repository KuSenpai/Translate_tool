// "🧹 Xử lý data thô" card on the home screen: clean ChatGPT-pasted rough translations, prepare raw Korean.
const $ = (s) => document.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(method, url, body) {
  const res = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw Object.assign(new Error(data?.error?.message || `HTTP ${res.status}`), { code: data?.error?.code });
  return data;
}

async function loadStories() {
  try {
    const stories = await api("GET", "/api/stories");
    $("#storyList").innerHTML = stories.map((s) => `<option value="${esc(s.name)}">`).join("");
    if (!$("#dataStory").value && stories.length === 1) $("#dataStory").value = stories[0].name;
  } catch { /* non-fatal */ }
}

async function run(kind) {
  const path = $("#dataPath").value.trim();
  if (!path) return ($("#dataResult").innerHTML = `<div class="alert error">Nhập đường dẫn file trước.</div>`);
  const story = $("#dataStory").value.trim() || null;
  const started = Date.now();
  const tick = setInterval(() => {
    $("#dataResult").innerHTML = `⏳ Đang xử lý… ${Math.round((Date.now() - started) / 1000)}s
      <span class="muted">(file Word lớn có thể mất vài phút)</span>`;
  }, 1000);
  $("#dataClean").disabled = $("#dataRaw").disabled = true;
  try {
    if (kind === "clean") {
      const r = await api("POST", "/api/tools/clean-rough", { path, story });
      const rm = r.report.removed;
      $("#dataResult").innerHTML = `<div class="alert">✔ Đã làm sạch <b>${esc(r.source.split(/[\\/]/).pop())}</b>:
        ${r.chapters} chương (${r.confidence.high || 0} tin cậy cao${r.confidence.low ? `, ${r.confidence.low} cần kiểm tra` : ""}).
        Đã bỏ ${rm.prompts} lời nhắc, ${rm.preambles} câu mở đầu, ${rm.outros} lời kết của ChatGPT, ${rm.counters + rm.ads} dòng rác.
        ${r.warnings.length ? `<ul>${r.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
        <div class="muted">File: ${esc(r.output)}</div>
        <button class="small primary" id="dataOpen" data-id="${esc(r.project_id)}">Mở trong Thư viện</button></div>`;
      $("#dataOpen").addEventListener("click", () => {
        try { localStorage.setItem("lastProject", r.project_id); } catch { /* storage unavailable */ }
        location.reload();
      });
    } else {
      const r = await api("POST", "/api/tools/prepare-raw", {
        path, story, from_number: $("#dataFrom").value ? +$("#dataFrom").value : null, to_number: $("#dataTo").value ? +$("#dataTo").value : null,
      });
      $("#dataResult").innerHTML = `<div class="alert">✔ Raw có ${r.raw_chapters} chương (${r.raw_range[0]}–${r.raw_range[1]});
        truyện đã dịch ${r.translated} chương. Các chương chưa dịch đã sẵn sàng ở <b>🤖 Dịch AI → Nguồn đã chuẩn bị</b>:
        <ul>${r.files.map((f) => `<li>${f.kind === "tiep-theo" ? "Phần tiếp theo" : "Chương còn thiếu"} <b>${esc(f.range)}</b>:
          ${f.chapters} chương · ước tính Opus 5.5 ~$${f.estimate["claude-opus-5-5"].usd}, Sonnet 5.5 ~$${f.estimate["claude-sonnet-5-5"].usd}</li>`).join("")}</ul></div>`;
    }
    loadStories();
  } catch (e) {
    $("#dataResult").innerHTML = `<div class="alert error">${e.code ? `[${esc(e.code)}] ` : ""}${esc(e.message)}</div>`;
  } finally {
    clearInterval(tick);
    $("#dataClean").disabled = $("#dataRaw").disabled = false;
  }
}

$("#dataClean").addEventListener("click", () => run("clean"));
$("#dataRaw").addEventListener("click", () => run("raw"));
loadStories();
