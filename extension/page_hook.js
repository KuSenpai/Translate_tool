// Runs in the page's own JavaScript world (manifest: "world": "MAIN") so it can answer the browser's native
// confirm()/alert() popups that Wattpad shows when Publish is clicked - a content script cannot click those.
// It only does so while content.js has flagged a Publish click (data-nt-auto-confirm on <html>); at any other time
// the page's dialogs behave exactly as before.
(() => {
  if (window.__ntHook) return;
  window.__ntHook = true;
  const root = () => document.documentElement;
  const armed = () => !!root() && root().getAttribute("data-nt-auto-confirm") === "1";
  const note = (kind, msg) => root().setAttribute("data-nt-last-dialog",
    `${kind}: “${String(msg ?? "").replace(/\s+/g, " ").slice(0, 200)}”`);
  const nativeConfirm = window.confirm, nativeAlert = window.alert;
  window.confirm = function (msg) {
    if (armed()) { note("confirm", msg); return true; }
    return nativeConfirm.apply(this, arguments);
  };
  window.alert = function (msg) {
    if (armed()) { note("alert", msg); return undefined; }
    return nativeAlert.apply(this, arguments);
  };
})();
