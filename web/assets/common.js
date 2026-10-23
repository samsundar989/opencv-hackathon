// RiverSight dashboard: shared helpers (no build step).
const RS = (() => {
  const NAV = [["index.html", "Live"], ["judge.html", "Judges: start here"], ["approvals.html", "Approvals"], ["proof.html", "Proof"]];

  function header() {
    const here = location.pathname.split("/").pop() || "index.html";
    const h = document.createElement("header");
    h.className = "top";
    h.innerHTML = `<a class="brand" href="index.html">River<span>Sight</span></a><nav aria-label="Main">` +
      NAV.map(([href, label]) => `<a href="${href}"${href === here ? ' aria-current="page"' : ""}>${label}</a>`).join("") +
      `</nav>`;
    document.body.prepend(h);
    const f = document.createElement("footer");
    f.innerHTML = `Images: USGS HIVIS cameras (public domain), faces blurred with YuNet before display. Gauge data: USGS NWIS.
      Camera stage comes from per-site <b>live models</b> refit on all data; the evaluated numbers are the frozen-protocol ones on
      <a href="judge.html">the judge page</a>. OpenCV AI Competition 2026 entry. Not an official USGS product.`;
    document.body.append(f);
  }

  async function json(url, opts) {
    const r = await fetch(url + (url.includes("?") ? "&" : "?") + "t=" + Math.floor(Date.now() / 30000), opts);
    if (!r.ok) throw new Error(`${r.status} ${url}`);
    return r.json();
  }

  async function jsonl(url) {
    const r = await fetch(url + "?t=" + Math.floor(Date.now() / 30000));
    if (!r.ok) return [];
    return (await r.text()).split("\n").filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ft = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "—" : `${Number(v).toFixed(d)} ft`);
  const nice = (cam) => cam.replace(/^([A-Z]{2})_/, "$1 · ").replace(/_/g, " ");

  function ago(iso) {
    if (!iso) return "—";
    const m = Math.round((Date.now() - Date.parse(iso)) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m} min ago`;
    const h = Math.round(m / 60);
    return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
  }

  const LABEL = { ok: "OK", provisional: "provisional (gauge down)", quarantined: "quarantined", night: "night",
    view_change: "view changed", no_frame: "no new frame", error: "error", pending: "pending" };
  const pill = (s) => `<span class="pill ${esc(s || "pending")}">${esc(LABEL[s] || s || "pending")}</span>`;
  const flags = (fs) => (fs || []).map((f) => `<span class="flag">${esc(f)}</span>`).join("");

  const qs = (k) => new URLSearchParams(location.search).get(k);
  const days = (n) => [...Array(n).keys()].map((i) => new Date(Date.now() - i * 86400000).toISOString().slice(0, 10)).reverse();

  return { header, json, jsonl, esc, ft, nice, ago, pill, flags, qs, days };
})();
document.addEventListener("DOMContentLoaded", RS.header);
