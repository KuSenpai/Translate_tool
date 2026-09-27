const send = (msg) => new Promise((res) => chrome.runtime.sendMessage(msg, res));
const $ = (s) => document.querySelector(s);

async function check() {
  const r = await send({ type: "config" });
  $("#status").innerHTML = r?.ok
    ? `<span class="ok">● Đã kết nối tool</span> <span class="muted">(Wattpad: ${r.data.base})</span>`
    : `<span class="bad">● Không kết nối được tool.</span> <span class="muted">Tool có đang chạy không? (${r?.error || ""})</span>`;
}

(async () => {
  const r = await send({ type: "getApp" });
  $("#app").value = r?.data?.app || "";
  check();
})();

$("#save").addEventListener("click", async () => {
  await send({ type: "setApp", app: $("#app").value.trim() || "http://127.0.0.1:8765" });
  $("#msg").textContent = "Đã lưu.";
  check();
});

$("#diag").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/^https:\/\/www\.wattpad\.com\//.test(tab.url || "")) {
    $("#msg").textContent = "Hãy mở một trang Wattpad (vd My Works hoặc trang soạn chương) rồi bấm lại.";
    return;
  }
  chrome.tabs.sendMessage(tab.id, { type: "diag" }, (res) => {
    $("#msg").textContent = res?.ok ? `Đã gửi. File: ${res.path}` : `Không gửi được: ${res?.error || chrome.runtime.lastError?.message || ""}`;
  });
});
