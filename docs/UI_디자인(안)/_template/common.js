// ── 공통 유틸 (build_ui_drafts.py 가 각 페이지에 인라인) ──
const D = window.NIPA_DATA;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n || 0).toLocaleString("ko-KR");
const NOW = new Date();
const DAY = 86400000;
const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const kdate = (s) => (s ? s.slice(0, 10).replace(/-/g, ".") : "");
const ktime = (s) => (s && s.length > 10 ? s.slice(11, 16) : "");
const toDate = (s, endOfDay) => {
  if (!s) return null;
  if (s.length === 10) return new Date(s + (endOfDay ? "T23:59:59" : "T00:00:00"));
  return new Date(s);
};
const bytes = (b) => (b >= 1024 ** 3 ? (b / 1024 ** 3).toFixed(2) + " GB" : b >= 1024 ** 2 ? (b / 1024 ** 2).toFixed(1) + " MB" : (b / 1024).toFixed(0) + " KB");
const pct = (a, b) => (b ? ((a / b) * 100).toFixed(1) : "0.0");
const ago = (iso) => {
  if (!iso) return "기록 없음";
  const h = (NOW - new Date(iso)) / 3600000;
  if (h < 1) return Math.max(1, Math.round(h * 60)) + "분 전";
  if (h < 24) return Math.round(h) + "시간 전";
  return Math.floor(h / 24) + "일 전";
};

// 접수 상태 — 페이지를 연 시각 기준. 제목에 [접수마감]이 있으면 기간과 무관하게 마감 처리
const STATUS = {
  urgent: { label: "마감 임박", icon: "⏰" },
  open: { label: "접수 중", icon: "●" },
  upcoming: { label: "접수 예정", icon: "◷" },
  always: { label: "상시 모집", icon: "∞" },
  ended: { label: "접수 마감", icon: "■" },
};
const ITEMS = D.items.map((it) => {
  const start = toDate(it.start), end = toDate(it.end, true);
  let st, dleft = null;
  if (/\[?접수\s*마감\]?/.test(it.title.slice(0, 8))) st = "ended";
  // 기간 표기가 없고 게시된 지 1년이 넘은 공고는 상시 모집이 아니라 지난 공고로 본다
  else if (!start && !end) st = it.posted && NOW - toDate(it.posted) > 365 * DAY ? "ended" : "always";
  else if (start && NOW < start) st = "upcoming";
  else if (end && NOW > end) st = "ended";
  else if (!end) st = "always";
  else {
    dleft = Math.round((new Date(ymd(end) + "T00:00:00") - new Date(ymd(NOW) + "T00:00:00")) / DAY);
    st = dleft <= 7 ? "urgent" : "open";
  }
  const span = start && end ? Math.round((end - start) / DAY) : null;
  return { ...it, st, dleft, startDate: start, endDate: end, span, year: (it.posted || "").slice(0, 4) };
});
const isOpen = (x) => x.st === "open" || x.st === "urgent";
const ddayText = (x) => (x.dleft === 0 ? "오늘 마감" : x.dleft != null ? `D-${x.dleft}` : STATUS[x.st].label);

// 간단 툴팁: data-tip 속성을 가진 요소에 마우스를 올리면 표시
(function tooltip() {
  const tip = document.createElement("div");
  tip.className = "viz-tip";
  document.body.appendChild(tip);
  document.addEventListener("mousemove", (e) => {
    const t = e.target.closest("[data-tip]");
    if (!t) { tip.style.opacity = 0; return; }
    tip.innerHTML = t.getAttribute("data-tip");
    tip.style.opacity = 1;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = e.clientX + 14, y = e.clientY + 14;
    if (x + w > innerWidth - 8) x = e.clientX - w - 14;
    if (y + h > innerHeight - 8) y = e.clientY - h - 14;
    tip.style.transform = `translate(${x}px, ${y}px)`;
  });
})();

// 가로 막대 목록 (단일 계열 = 한 색)
function hbars(rows, opt = {}) {
  const max = Math.max(1, ...rows.map((r) => r[1]));
  return `<div class="hbars">` + rows.map(([label, v, tipExtra]) => `
    <div class="hbar" data-tip="<b>${esc(label)}</b><br>${fmt(v)}${opt.unit || "건"}${tipExtra ? "<br>" + tipExtra : ""}">
      <span class="hbar-label">${esc(label)}</span>
      <span class="hbar-track"><span class="hbar-fill" style="width:${((v / max) * 100).toFixed(1)}%"></span></span>
      <span class="hbar-val">${fmt(v)}</span>
    </div>`).join("") + `</div>`;
}

// 세로 막대 (SVG, 단일 계열). rows: [{label, v, tip, hl}]
function vbars(rows, { h = 200, color = "var(--series-1)", hlColor = "var(--series-hl)", every = 1 } = {}) {
  const W = 800, top = 18, bottom = 26, left = 34, max = Math.max(4, ...rows.map((r) => r.v));
  const nice = Math.ceil(max / 4) * 4, ph = h - top - bottom, slot = (W - left) / rows.length, bw = Math.min(46, slot * 0.62);
  let s = `<svg viewBox="0 0 ${W} ${h}" class="vbars" preserveAspectRatio="none" role="img">`;
  for (let i = 0; i <= 4; i++) {
    const y = top + ph * (1 - i / 4);
    s += `<line x1="${left}" x2="${W}" y1="${y}" y2="${y}" class="grid"/><text x="${left - 6}" y="${y + 3}" class="axis" text-anchor="end">${(nice * i) / 4}</text>`;
  }
  rows.forEach((r, i) => {
    const bh = (r.v / nice) * ph, x = left + i * slot + (slot - bw) / 2, y = top + ph - bh;
    s += `<g data-tip="${esc(r.tip || r.label + " · " + r.v + "건")}"><rect x="${x - (slot - bw) / 2}" y="${top}" width="${slot}" height="${ph}" fill="transparent"/>`;
    if (r.v) s += `<path d="M${x},${top + ph} V${y + 4} q0,-4 4,-4 H${x + bw - 4} q4,0 4,4 V${top + ph} Z" fill="${r.hl ? hlColor : color}"/>`;
    if (r.v && r.label_v !== false) s += `<text x="${x + bw / 2}" y="${y - 5}" class="val" text-anchor="middle">${r.v}</text>`;
    if (i % every === 0 || r.hl) s += `<text x="${x + bw / 2}" y="${h - 8}" class="axis" text-anchor="middle">${esc(r.label)}</text>`;
    s += `</g>`;
  });
  return s + `</svg>`;
}

// 표 보기 (접근성 — 차트 아래 접이식)
const tableView = (head, rows) => `<details class="tv"><summary>표로 보기</summary><table><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></details>`;
