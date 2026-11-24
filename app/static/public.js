// 수요자 화면 — UI 시안 안2의 필터·카드 로직. 접수 상태(st·D-day)는 서버(services/public.py)가 계산해 넘긴다.
(() => {
  const D = JSON.parse(document.getElementById("data").textContent);
  const ITEMS = D.items;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => Number(n || 0).toLocaleString("ko-KR");
  const kdate = (s) => (s ? s.slice(0, 10).replace(/-/g, ".") : "");
  const ktime = (s) => (s && s.length > 10 ? s.slice(11, 16) : "");
  const detailUrl = (id) => D.detail.replace(/0$/, String(id));
  const ST = [["urgent", "마감 임박(7일 이내)"], ["open", "접수 중"], ["upcoming", "접수 예정"], ["always", "상시 모집"], ["ended", "접수 마감"]];
  const uniq = (get) => [...new Set(ITEMS.flatMap(get))].sort((a, b) => a.localeCompare(b, "ko"));

  const GROUPS = [
    ["st", "접수 상태", ST, (x) => [x.st]],
    ["org", "기관", uniq((x) => [x.org]).length > 1 ? uniq((x) => [x.org]).map((k) => [k, k]) : [], (x) => [x.org]],   // 기관이 하나뿐이면 숨긴다
  ];
  // 접수 마감 포함 여부는 서버 설정(PUBLIC_SHOW_ENDED)을 따른다
  const fresh = () => ({
    st: new Set(["urgent", "open", "upcoming", "always", ...(D.showEnded ? ["ended"] : [])]),
    org: new Set(),
  });
  let sel = fresh(), q = "", sort = "end", page = 1, favOnly = false, lastCount = 0;
  const PAGE = 10;   // 한 쪽에 보여 줄 공고 수

  // 관심 공고 — 이 브라우저(localStorage)에만 저장한다. 저장소를 쓸 수 없으면 이번 방문 동안만 유지된다
  const KEY = "gongmoFavs";
  let favs = new Set();
  try { favs = new Set(JSON.parse(localStorage.getItem(KEY) || "[]")); } catch (e) { /* 저장소 사용 불가 */ }
  const saveFavs = () => { try { localStorage.setItem(KEY, JSON.stringify([...favs])); } catch (e) { /* 무시 */ } };
  const favCount = () => ITEMS.filter((x) => favs.has(x.id)).length;   // 노출에서 빠진 공고는 세지 않는다

  const text = (x) => [x.org, x.title, x.biz, x.summary].join(" ").toLowerCase();
  const pass = (x, skip) => GROUPS.every(([k, , , get]) => k === skip || !sel[k].size || get(x).some((v) => sel[k].has(v))) &&
    (!q || text(x).includes(q)) && (!favOnly || favs.has(x.id));

  // 조건 선택 — 검색창 옆 '상세검색' 버튼으로 펼치는 패널. 묶음마다 버튼 한 줄, 한 묶음에서 하나만 고르고 '전체'는 조건 없음이다
  let panelOpen = false;
  function side() {
    const defSt = [...fresh().st].sort().join(",");
    const cur = (k) => {
      if (k !== "st") return [...sel[k]][0] || "";
      const v = [...sel.st].sort().join(",");
      return v === defSt ? "" : v === "open,urgent" ? "now" : sel.st.size === 1 ? [...sel.st][0] : "";
    };
    const active = GROUPS.filter(([k]) => cur(k) !== "").length;
    $("fn").textContent = active; $("fn").hidden = !active;
    $("fopen").setAttribute("aria-expanded", String(panelOpen));
    $("side").hidden = !panelOpen;
    $("side").innerHTML = `<div class="fgrid">` + GROUPS.map(([k, title, opts, get]) => {
      if (!opts.length) return "";
      const all = k === "st" ? [["now", "지금 신청 가능"], ...opts] : opts;
      const n = (v) => ITEMS.filter((x) => pass(x, k) && (k === "st" && v === "now" ? ["urgent", "open"].includes(x.st) : get(x).includes(v))).length;
      const c = cur(k);
      const btn = (v, l, cnt) => `<button type="button" class="fo${c === v ? " sel" : ""}" data-g="${k}" data-v="${esc(v)}" aria-pressed="${c === v}">${esc(l)}${cnt === null ? "" : ` <em>${fmt(cnt)}</em>`}</button>`;
      return `<div class="fg"><h4>${title}</h4><div class="fopts">${btn("", "전체", null)}${all.map(([v, l]) => btn(v, l, n(v))).join("")}</div></div>`;
    }).join("") + `</div><div class="ffoot"><span class="fsum">${active ? `${active}개 조건 적용 중 · ` : ""}조건에 맞는 공고 <b>${fmt(lastCount)}</b>건</span><span class="facts"><button type="button" class="reset" id="reset">조건 초기화</button><button type="button" class="done" id="fdone">결과 보기</button></span></div>`;
    $("side").querySelectorAll(".fo").forEach((el) => el.onclick = () => {
      const k = el.dataset.g, v = el.dataset.v;
      if (k === "st") sel.st = v === "" ? fresh().st : v === "now" ? new Set(["urgent", "open"]) : new Set([v]);
      else sel[k] = v ? new Set([v]) : new Set();
      page = 1; render();
    });
    $("reset").onclick = () => { sel = fresh(); q = ""; $("q").value = ""; favOnly = false; page = 1; render(); };
    $("fdone").onclick = () => { panelOpen = false; side(); $("cnt").scrollIntoView({ behavior: "smooth", block: "center" }); };
  }
  $("fopen").onclick = () => { panelOpen = !panelOpen; side(); };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && panelOpen) { panelOpen = false; side(); $("fopen").focus(); } });

  // 공고 한 줄(K-Startup 목록의 구조): 배지 줄 → 제목 → 요약 → 날짜·조회 줄 → (우리 추가) 지원 규모·자부담 줄. 오른쪽에 스크랩·새 창
  function card(x) {
    const sum = x.summary ? esc(x.summary) : `본문 요약 없음 — 상세 내용은 첨부 파일(${x.files}개)에 있습니다.`;
    const fav = favs.has(x.id);
    const end = x.end ? kdate(x.end) + (ktime(x.end) ? " " + ktime(x.end) : "") : "상시 모집";
    const m = (k, v) => `<span class="mi"><span class="k">${k}</span><span class="v">${v}</span></span>`;
    return `<article class="card st-${x.st}">
      <div class="cmain">
        <div class="rbadges">
          <span class="bg org" data-c="${x.org_c}">${esc(x.org)}</span><span class="bg dd ${x.st}">${esc(x.label)}</span>
          ${x.new ? `<span class="newb" title="최근 게시된 공고">NEW</span>` : ""}${x.astruct ? `<span class="prep att" title="첨부 공고문까지 읽어 정리한 공고">첨부 구조화</span>` : ""}
        </div>
        <h4><a href="${detailUrl(x.id)}">${esc(x.title)}</a></h4>
        <div class="sum">${sum}</div>
        <div class="rmeta">${m("등록일자", kdate(x.posted) || "—")}${m("시작일자", kdate(x.start) || "—")}${m("마감일자", esc(end))}${m("조회", fmt(x.views))}</div>
      </div>
      <div class="ract">
        <button type="button" class="star ${fav ? "on" : ""}" data-id="${x.id}" aria-pressed="${fav}" title="${fav ? "관심 공고에서 빼기" : "관심 공고로 저장"}">${fav ? "★" : "☆"}</button>
        <a class="ext" href="${detailUrl(x.id)}" target="_blank" rel="noopener" aria-label="새 창으로 열기" title="새 창으로 열기">↗</a>
      </div>
    </article>`;
  }

  // 쪽 번호 막대 — 위·아래 두 곳에 같은 내용을 그린다
  function pager(pages) {
    const html = pages < 2 ? "" : (() => {
      const nums = [...new Set([1, pages, ...Array.from({ length: 5 }, (_, i) => page - 2 + i)])]
        .filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
      const b = (p, label, extra = "") => `<button type="button" data-p="${p}" class="${extra}" ${p === page && !extra ? 'aria-current="page"' : ""} ${extra === "nav" && (p < 1 || p > pages || p === page) ? "disabled" : ""}>${label}</button>`;
      let out = b(1, "«", "nav") + b(page - 1, "‹", "nav"), prev = 0;
      for (const n of nums) { if (n - prev > 1) out += `<span class="gap">…</span>`; out += b(n, n, n === page ? "on" : ""); prev = n; }
      return out + b(page + 1, "›", "nav") + b(pages, "»", "nav");
    })();
    document.querySelectorAll(".pager").forEach((el) => {
      el.innerHTML = html;
      el.querySelectorAll("button").forEach((btn) => btn.onclick = () => {
        page = Number(btn.dataset.p); render(); scrollTo({ top: $("cnt").offsetTop - 20, behavior: "smooth" });
      });
    });
  }

  const endKey = (x) => (x.st === "urgent" || x.st === "open" ? x.end || "9" : x.st === "upcoming" ? "8" + (x.start || "") : "9");
  function render() {
    const rows = ITEMS.filter((x) => pass(x)).sort((a, b) =>
      sort === "new" ? (b.posted || "").localeCompare(a.posted || "") :
      sort === "views" ? b.views - a.views :
      endKey(a).localeCompare(endKey(b)) || (b.posted || "").localeCompare(a.posted || ""));
    lastCount = rows.length;
    $("cnt").innerHTML = `조건에 맞는 공고 <b>${fmt(rows.length)}건</b>`;
    const pages = Math.max(1, Math.ceil(rows.length / PAGE));
    page = Math.min(Math.max(1, page), pages);
    $("cards").innerHTML = rows.slice((page - 1) * PAGE, page * PAGE).map(card).join("") || emptyMsg();
    pager(pages);
    $("cards").querySelectorAll(".star").forEach((b) => b.onclick = () => {
      const id = Number(b.dataset.id); favs.has(id) ? favs.delete(id) : favs.add(id); saveFavs(); render();
    });
    const n = favCount();
    $("favchip").className = "favchip" + (favOnly ? " on" : "");
    $("favchip").textContent = `★ 관심 공고만 보기 (${n})`;
    $("favnav").hidden = !n; $("favnav").textContent = `★ 관심 공고 ${n}`;
    side();
  }
  const emptyMsg = () => favOnly ? `<div class="empty">아직 저장한 관심 공고가 없습니다. 카드의 ☆를 눌러 저장해 보세요.</div>` : ITEMS.length
    ? `<div class="empty">조건에 맞는 공고가 없습니다. 상세검색 조건을 줄이거나 “접수 마감”을 포함해 보세요.</div>`
    : `<div class="empty">아직 화면에 보여 줄 공고가 없습니다.<br>수집한 공고가 아직 없습니다.</div>`;

  const cnt = (sts) => ITEMS.filter((x) => sts.includes(x.st)).length;
  const QUICK = [["✅", ["urgent", "open"], "지금 신청할 수 있는 공모"], ["⏰", ["urgent"], "7일 안에 마감"], ["🗓", ["upcoming"], "곧 접수 시작"], ["∞", ["always"], "상시 모집"]];
  $("stats").innerHTML = QUICK.map(([ic, sts, l], i) =>
    `<div class="stat" data-i="${i}" role="button" tabindex="0"><div class="l">${l}</div><div class="v">${fmt(cnt(sts))}<small>건</small></div></div>`).join("");
  document.querySelectorAll(".stat").forEach((s) => s.onclick = () => {
    sel.st = new Set(QUICK[s.dataset.i][1]); page = 1; render(); scrollTo({ top: $("cnt").offsetTop - 20, behavior: "smooth" });
  });

  // 곧 마감 띠 — 조건(필터·검색)과 무관하게 접수 중인 공고 중 마감이 가까운 순. 없으면 띠를 숨긴다
  const soon = ITEMS.filter((x) => x.dleft !== null && x.dleft <= D.soonDays && ["urgent", "open"].includes(x.st))
    .sort((a, b) => a.dleft - b.dleft || (a.end || "").localeCompare(b.end || "")).slice(0, D.soonMax);
  if (soon.length) {
    $("soon").hidden = false;
    $("soonh").innerHTML = `곧 마감되는 공고 <small>${D.soonDays}일 이내 · 마감 빠른 순</small>`;
    $("soonrow").innerHTML = soon.map((x) => `<a class="sc" href="${detailUrl(x.id)}"><div class="d ${x.dleft <= 3 ? "hot" : ""}">⏰ ${esc(x.label)}</div><div class="t">${esc(x.title)}</div><div class="o">${esc(x.org)} · ~${kdate(x.end)}</div></a>`).join("");
  }
  const toggleFav = () => { favOnly = !favOnly; page = 1; render(); scrollTo({ top: $("cnt").offsetTop - 20, behavior: "smooth" }); };
  $("favchip").onclick = toggleFav; $("favnav").onclick = toggleFav;

  // 검색어 기록(F-SVC-18) — 직접 입력한 검색어만 보낸다. 입력을 멈추고 1.5초가 지나거나 검색 버튼·Enter를 누르면 기록하고,
  // 같은 방문(탭)에서 같은 검색어는 한 번만 보낸다. 많이 찾는 검색어 칩을 누른 것은 기록하지 않는다.
  const sent = new Set();
  let logTimer = null;
  function logSearch() {
    const term = $("q").value.trim().replace(/\s+/g, " ");
    if (term.length < 2 || sent.has(term.toLowerCase())) return;
    sent.add(term.toLowerCase());
    try { fetch(D.searchLog, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ q: term, n: lastCount }), keepalive: true }); } catch (e) { /* 기록 실패는 무시 */ }
  }
  $("q").oninput = (e) => { q = e.target.value.trim().toLowerCase(); page = 1; render(); clearTimeout(logTimer); logTimer = setTimeout(logSearch, 1500); };
  $("q").onkeydown = (e) => { if (e.key === "Enter") { clearTimeout(logTimer); logSearch(); } };
  $("go").onclick = () => { render(); clearTimeout(logTimer); logSearch(); };
  document.querySelectorAll(".qtags button").forEach((b) => b.onclick = () => {
    $("q").value = b.textContent; q = b.textContent.toLowerCase(); sel.st = new Set(); render();
  });
  $("sort").onchange = (e) => { sort = e.target.value; page = 1; render(); };
  render();
})();
