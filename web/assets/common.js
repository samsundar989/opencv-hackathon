// RiverSight dashboard: shared helpers (no build step).
const RS = (() => {
  const NAV = [["index.html", "Live"], ["judge.html", "Judges: start here"], ["approvals.html", "Approvals"], ["proof.html", "Proof"], ["api.html", "Data API"]];

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
  const FEATURED = ["IL_Salt_Creek_at_Wood_Dale", "NY_Neversink_River_at_Godeffroy",
    "NY_East_Branch_Delaware_River_at_Hancock_Staff", "OH_Bean_Creek_at_Powers", "NJ_Stony_Brook_at_Princeton",
    "TX_Buffalo_Bayou_at_State_HWY_6_near_Addicks", "WI_East_Branch_Pecatonica_River_near_Blanchardville_Bullet"];  // D-0011
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
  const hm = (iso) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  // night / stale card line: the last daylight camera reading next to what the gauge said then (D-0011 W1-3)
  function lastDay(s) {
    if (!s.last_daylight_t) return "";
    const c = s.last_daylight_camera_at_least_ft != null ? `≥ ${Number(s.last_daylight_camera_at_least_ft).toFixed(2)} ft`
      : s.last_daylight_camera_ft != null ? `${Number(s.last_daylight_camera_ft).toFixed(2)} ft` : null;
    const when = (Date.now() - Date.parse(s.last_daylight_t)) > 20 * 3600e3
      ? new Date(s.last_daylight_t).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : hm(s.last_daylight_t);
    return c ? `camera ${c} at ${esc(when)}, gauge then ${ft(s.last_daylight_gauge_ft)}` : `last daylight frame ${esc(when)}`;
  }
  const WHY = {
    ok: "Daylight frame registered to the camera's reference; the camera reading and the gauge agree within the model's error.",
    provisional: "The USGS gauge has not reported for more than 90 minutes, so this camera reading stands in for it (gap-fill). Treat it as provisional.",
    quarantined: "The agent stopped trusting this camera (e.g. it moved or disagrees with the gauge). It is released automatically after 3 good cycles in a row.",
    night: "It is dark at the camera, so there is no camera reading. The gauge reading carries on; the image shown is the last daylight frame.",
    view_change: "The latest frame does not line up with this camera's reference view (it may have been moved or re-aimed), so no camera reading is made.",
    no_frame: "USGS has not published a frame from this camera.",
    stale: "This camera has not published a new frame for more than 2 hours. The last frame is shown; the gauge reading is current.",
    above_range: "The river is above any stage this camera has seen during calibration, so it can only say 'at least this high'. The gauge is trusted.",
    above_range_provisional: "Above the calibrated range and the gauge is down: the camera reports only a lower bound.",
    error: "This site failed in the last cycle; the other sites were not affected.", pending: "Waiting for the first reading." };
  // headline "RiverSight stage" (D-0013 W1-1): fused value + provenance
  const SRC = { "gauge": ["gauge", "ok", "The USGS gauge is reporting, so RiverSight shows the gauge."],
    "camera gap-fill": ["camera gap-fill", "provisional", "The gauge is down: the camera's reading, anchored to the gauge's last 48 h, fills the gap. σ grows the longer it lasts."],
    "last gauge": ["last gauge, σ growing", "night", "No fresh gauge and no usable camera frame: the last value, with uncertainty growing at the river's own rate of change."],
    "lower bound": ["lower bound", "above_range", "Above the camera's calibrated range with the gauge down: the river is at least this high."] };
  function fused(r) {
    if (!r || r.fused_stage_ft == null) return "";
    const [lab, cls, why] = SRC[r.fused_source] || [r.fused_source || "?", "pending", ""];
    const v = `${r.fused_source === "lower bound" ? "≥ " : ""}${Number(r.fused_stage_ft).toFixed(2)} ft` +
      (r.fused_sigma_ft != null && r.fused_source !== "gauge" ? ` ± ${Number(r.fused_sigma_ft).toFixed(2)}` : "");
    return `<span>RiverSight stage <b style="font-size:1.15em">${v}</b> <span class="pill ${cls}" tabindex="0" title="${esc(why)}" aria-label="${esc(lab + ". " + why)}">${esc(lab)}</span></span>`;
  }
  const pill = (s) => `<span class="pill ${esc(s || "pending")}" tabindex="0" title="${esc(WHY[s] || "")}" aria-label="${esc((LABEL[s] || s || "pending") + ". " + (WHY[s] || ""))}">${esc(LABEL[s] || s || "pending")}</span>`;
  const flags = (fs) => (fs || []).map((f) => `<span class="flag">${esc(f)}</span>`).join("");

  const qs = (k) => new URLSearchParams(location.search).get(k);
  const days = (n) => [...Array(n).keys()].map((i) => new Date(Date.now() - i * 86400000).toISOString().slice(0, 10)).reverse();

  return { header, json, jsonl, esc, ft, nice, ago, pill, flags, qs, days, cam, panel, FEATURED, featuredRank, lastDay, LABEL, WHY, fused };
})();
document.addEventListener("DOMContentLoaded", RS.header);
