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
    view_change: "view changed", no_frame: "no new frame", error: "error", pending: "pending", stale: "stale frame",
    above_range: "above range — gauge trusted", above_range_provisional: "above range (gauge down)" };

  // D-0009: featured first (demo quality), the rest alphabetically
  const FEATURED = ["WI_East_Branch_Pecatonica_River_near_Blanchardville_Bullet", "IL_Salt_Creek_at_Wood_Dale",
    "NY_East_Branch_Delaware_River_at_Hancock_Staff", "NY_Neversink_River_at_Godeffroy", "OH_Bean_Creek_at_Powers",
    "NJ_Stony_Brook_at_Princeton", "TX_Buffalo_Bayou_at_State_HWY_6_near_Addicks"];
  const featuredRank = (cam) => { const i = FEATURED.indexOf(cam); return i < 0 ? 99 : i; };

  // camera stage text: never a number above the calibrated range (OUT_OF_RANGE)
  function cam(r, withSigma = true) {
    if (!r) return "—";
    if (r.camera_at_least_ft != null) return `≥ ${Number(r.camera_at_least_ft).toFixed(2)} ft <span class="muted small">(above calibrated range)</span>`;
    if (r.camera_stage_ft == null) return "—";
    return `${Number(r.camera_stage_ft).toFixed(2)} ft` + (withSigma && r.camera_sigma_ft ? ` ± ${Number(r.camera_sigma_ft).toFixed(2)}` : "");
  }

  // run one panel; a failure shows in that panel only (D-0009 W1-3)
  async function panel(id, fn) {
    try { await fn(document.getElementById(id)); }
    catch (e) { const el = document.getElementById(id); if (el) el.innerHTML = `<span class="err small">Could not render (${esc(e.message)}).</span>`; console.error(id, e); }
  }
  const pill = (s) => `<span class="pill ${esc(s || "pending")}">${esc(LABEL[s] || s || "pending")}</span>`;
  const flags = (fs) => (fs || []).map((f) => `<span class="flag">${esc(f)}</span>`).join("");

  const qs = (k) => new URLSearchParams(location.search).get(k);
  const days = (n) => [...Array(n).keys()].map((i) => new Date(Date.now() - i * 86400000).toISOString().slice(0, 10)).reverse();

  return { header, json, jsonl, esc, ft, nice, ago, pill, flags, qs, days, cam, panel, FEATURED, featuredRank };
})();
document.addEventListener("DOMContentLoaded", RS.header);
