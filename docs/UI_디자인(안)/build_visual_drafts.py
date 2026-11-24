"""시각화 시안 5개 생성 — DB의 노출·검토 공고(수요자 화면과 같은 목록)를 읽어 단독 HTML로 만든다.

    cd <프로젝트 루트> && python "docs/UI_디자인(안)/build_visual_drafts.py"

산출물: docs/UI_디자인(안)/시각화/ (안1~안5 + index.html). 파일을 열어 보는 용도이며 앱 화면에는 적용하지 않는다.
공고 링크는 로컬 서버(http://127.0.0.1:5000)가 켜져 있을 때 열린다.
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "시각화"

from app import create_app  # noqa: E402
from app.db import get_db  # noqa: E402
from app.services.public import public_items  # noqa: E402

PAGES = [
    ("안1_일정타임라인", "접수 일정 타임라인", "사업마다 접수 시작~마감을 가로 막대로 겹쳐 보여 주는 간트형 화면"),
    ("안2_월간달력", "월간 마감 달력", "날짜 칸에 마감·시작 공고를 표시하고 날짜를 누르면 목록을 보여 주는 달력"),
    ("안3_분야트리맵", "분야별 트리맵", "분야마다 공고 수에 비례한 사각형으로 어느 분야에 사업이 몰리는지 보여 줌"),
    ("안4_월별추이", "월별 공고 추이", "월별 게시 건수를 기관별·분야별로 쌓은 막대 차트"),
    ("안5_분야대상히트맵", "분야 × 대상 히트맵", "분야와 지원 대상의 교차 건수를 색 농도로 보여 주는 표"),
]

CSS = """
:root { color-scheme: light; --bg:#f4f6f9; --surface:#fff; --line:#e3e7ed; --line2:#cfd6df; --t1:#14181f; --t2:#4a5361; --t3:#7a8494;
  --navy:#1f3864; --navy2:#2b4c86; --brand-soft:#e8eef8; --series-1:#2a78d6; --crit:#d03b3b;
  --sans:"IBM Plex Sans KR","Malgun Gothic","Noto Sans KR",sans-serif; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--t1); font-family:var(--sans); font-size:14px; line-height:1.55; }
a { color:inherit; }
.gnb { background:var(--navy); color:#fff; } .gnb .in { max-width:1280px; margin:0 auto; padding:0 28px; height:56px; display:flex; align-items:center; gap:26px; }
.logo { font-weight:700; font-size:16px; } .logo small { font-weight:400; opacity:.7; margin-left:8px; font-size:12.5px; }
.gnb nav { display:flex; gap:20px; font-size:13.5px; flex-wrap:wrap; } .gnb nav a { text-decoration:none; opacity:.7; padding:17px 0; }
.gnb nav a.on { opacity:1; font-weight:600; box-shadow:inset 0 -3px 0 #fff; }
.wrap { max-width:1280px; margin:0 auto; padding:24px 28px 56px; }
h1 { margin:0 0 4px; font-size:24px; letter-spacing:-.02em; } .sub { margin:0 0 18px; color:var(--t2); }
.panel { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:16px 18px; }
.tools { display:flex; gap:14px; flex-wrap:wrap; align-items:center; margin-bottom:14px; }
.chips { display:flex; gap:6px; flex-wrap:wrap; align-items:center; } .chips b { font-size:12.5px; color:var(--t3); font-weight:500; margin-right:2px; }
.chip { border:1px solid var(--line2); background:#fff; border-radius:999px; padding:4px 12px; font:inherit; font-size:13px; color:var(--t2); cursor:pointer; }
.chip.on { background:var(--navy); border-color:var(--navy); color:#fff; }
select { font:inherit; font-size:13px; padding:5px 8px; border:1px solid var(--line2); border-radius:6px; background:#fff; }
.org { font-size:11.5px; font-weight:600; padding:1px 7px; border-radius:4px; white-space:nowrap; background:#eef0f3; color:var(--t2); }
.org[data-c="0"] { background:#e8eef8; color:#1f3864; } .org[data-c="1"] { background:#e6f5f0; color:#0b6b52; }
.org[data-c="2"] { background:#fdf0e3; color:#9a5300; } .org[data-c="3"] { background:#f1e9fb; color:#5b2b9a; }
.legend { display:flex; gap:12px; flex-wrap:wrap; font-size:12.5px; color:var(--t2); margin-top:10px; } .legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; vertical-align:-1px; }
.note { font-size:12.5px; color:var(--t3); margin-top:10px; }
.list { display:flex; flex-direction:column; gap:6px; max-height:560px; overflow:auto; }
.li { display:flex; gap:8px; align-items:baseline; padding:7px 9px; border:1px solid var(--line); border-radius:8px; text-decoration:none; background:#fff; }
.li:hover { border-color:var(--series-1); } .li .t { font-weight:500; flex:1; } .li .m { font-size:12px; color:var(--t3); white-space:nowrap; }
.empty { color:var(--t3); padding:24px; text-align:center; }
"""

JS_COMMON = """
const D = JSON.parse(document.getElementById('data').textContent);
const ITEMS = D.items, TODAY = new Date(D.today + 'T00:00:00');
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const FC = {'인공지능':'#2a78d6','데이터':'#0e9aa7','클라우드':'#7a5af8','네트워크·IoT':'#ec835a','융합(의료·제조·안전 등)':'#2e9e4f',
  'SW·SaaS·오픈소스':'#c99a06','AI컴퓨팅·반도체':'#b4531a','디지털콘텐츠':'#d6336c','XR·메타버스':'#0b7fb0','기타':'#9aa4b2'};
const FIELDS = Object.keys(FC);
const prim = (x) => x.fields.find((f) => f !== '기타') || '기타';
const col = (x) => FC[prim(x)] || FC['기타'];
const dt = (s) => (s ? new Date(s.slice(0, 10) + 'T00:00:00') : null);
const day = 86400000;
const url = (x) => D.base + '/notice/' + x.id;
const short = (s, n) => (s.length > n ? s.slice(0, n - 1) + '…' : s);
const orgs = [...new Set(ITEMS.map((x) => x.org))];
const orgC = Object.fromEntries(ITEMS.map((x) => [x.org, x.orgc]));
const orgBadge = (x) => `<span class="org" data-c="${x.orgc}">${esc(x.org.replace('한국', '').replace('정보통신산업진흥원', 'NIPA').replace('지능정보사회진흥원', 'NIA'))}</span>`;
function orgChips(el, sel, onchange) {
  el.innerHTML = '<b>기관</b>' + orgs.map((o) => `<button class="chip ${sel.has(o) ? 'on' : ''}" data-o="${esc(o)}">${esc(o)}</button>`).join('');
  el.querySelectorAll('.chip').forEach((b) => b.onclick = () => { sel.has(b.dataset.o) ? sel.delete(b.dataset.o) : sel.add(b.dataset.o); if (!sel.size) orgs.forEach((o) => sel.add(o)); orgChips(el, sel, onchange); onchange(); });
}
function fieldLegend(el) { el.innerHTML = FIELDS.map((f) => `<span><i style="background:${FC[f]}"></i>${esc(f)}</span>`).join(''); }
"""

BODIES = {}
SCRIPTS = {}

BODIES[0] = """
<div class="tools panel">
  <div class="chips" id="orgs"></div>
  <div class="chips"><b>기간</b><select id="back"><option value="30">최근 1개월</option><option value="90">최근 3개월</option><option value="180" selected>최근 6개월</option><option value="400">전체</option></select></div>
  <div class="chips"><button class="chip on" id="tgEnded">접수 마감 포함</button></div>
</div>
<div class="panel"><div id="gantt"></div><div class="legend" id="legend"></div>
<div class="note" id="cnt"></div></div>
"""
SCRIPTS[0] = """
const sel = new Set(orgs); let back = 180, ended = true;
const LBL = 340, ROW = 34;
function render() {
  const from = new Date(TODAY - back * day), to = new Date(+TODAY + 75 * day), span = to - from;
  let rows = ITEMS.filter((x) => sel.has(x.org) && x.start && x.end).map((x) => ({ x, s: dt(x.start), e: dt(x.end) }))
    .filter((r) => r.e >= from && r.s <= to && (ended || r.e >= TODAY));
  rows.sort((a, b) => (a.e >= TODAY) === (b.e >= TODAY) ? (a.e >= TODAY ? a.e - b.e : b.e - a.e) : (a.e >= TODAY ? -1 : 1));
  const total = rows.length; rows = rows.slice(0, 40);
  const W = 1000, pct = (d) => Math.min(100, Math.max(0, (d - from) / span * 100));
  let ticks = '', m = new Date(from.getFullYear(), from.getMonth() + 1, 1);
  for (; m < to; m = new Date(m.getFullYear(), m.getMonth() + 1, 1))
    ticks += `<div style="position:absolute;left:${pct(m)}%;top:0;bottom:0;border-left:1px dashed var(--line)"><span style="position:absolute;top:-20px;left:3px;font-size:11.5px;color:var(--t3);white-space:nowrap">${m.getFullYear() % 100}.${m.getMonth() + 1}</span></div>`;
  const today = `<div style="position:absolute;left:${pct(TODAY)}%;top:-6px;bottom:0;border-left:2px solid var(--crit);z-index:3"><span style="position:absolute;top:-17px;left:-14px;background:var(--crit);color:#fff;font-size:10.5px;padding:0 5px;border-radius:3px;white-space:nowrap">오늘</span></div>`;
  const body = rows.map((r, i) => {
    const l = pct(r.s), w = Math.max(0.6, pct(r.e) - l), over = r.e < TODAY;
    const bar = `<a href="${url(r.x)}" target="_blank" title="${esc(r.x.title)}\\n${r.x.start.slice(0,10)} ~ ${r.x.end.slice(0,10)}" style="position:absolute;left:${l}%;width:${w}%;top:7px;height:20px;border-radius:5px;background:${col(r.x)};opacity:${over ? .4 : 1};${over ? 'background-image:repeating-linear-gradient(135deg,rgba(255,255,255,.35) 0 4px,transparent 4px 8px);' : ''}"></a>`;
    return `<div style="display:flex;height:${ROW}px;border-bottom:1px solid #f0f2f5;${i % 2 ? '' : 'background:#fafbfc'}"><div style="width:${LBL}px;flex:none;display:flex;gap:6px;align-items:center;padding-right:10px;overflow:hidden">${orgBadge(r.x)}<a href="${url(r.x)}" target="_blank" style="text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${esc(r.x.title)}">${esc(r.x.title)}</a></div><div style="position:relative;flex:1">${bar}</div></div>`;
  }).join('');
  $('gantt').innerHTML = `<div style="display:flex;margin-top:22px"><div style="width:${LBL}px;flex:none"></div><div style="position:relative;flex:1;height:0">${''}</div></div>
    <div style="position:relative"><div style="position:absolute;left:${LBL}px;right:0;top:0;bottom:0;pointer-events:none">${ticks}${today}</div>${body || '<div class="empty">조건에 맞는 공고가 없습니다.</div>'}</div>`;
  $('cnt').textContent = `접수 기간이 있는 공고 ${total}건 중 ${rows.length}건 표시(마감 빠른 순). 막대를 누르면 공고가 열립니다. 빗금 막대는 이미 마감된 공고입니다.`;
}
orgChips($('orgs'), sel, render); fieldLegend($('legend'));
$('back').onchange = (e) => { back = +e.target.value; render(); };
$('tgEnded').onclick = (e) => { ended = !ended; e.target.classList.toggle('on', ended); render(); };
render();
"""

BODIES[1] = """
<div class="tools panel">
  <div class="chips" id="orgs"></div>
  <div class="chips"><button class="chip on" id="tgStart">접수 시작 표시</button><button class="chip" id="busy">최근 1년 중 마감이 가장 많은 달</button><button class="chip" id="now">오늘</button></div>
</div>
<div style="display:grid;grid-template-columns:1fr 340px;gap:16px;align-items:start">
  <div class="panel"><div style="display:flex;align-items:center;gap:12px;margin-bottom:10px"><button class="chip" id="prev">‹</button><b id="ym" style="font-size:18px;min-width:120px;text-align:center"></b><button class="chip" id="next">›</button><span class="note" id="mcnt" style="margin:0 0 0 auto"></span></div>
  <div id="cal"></div><div class="legend" id="legend"></div></div>
  <div class="panel"><b id="dtitle">날짜를 선택하세요</b><div class="list" id="dlist" style="margin-top:10px"><div class="empty">달력의 날짜를 누르면 그날 마감·시작 공고가 나옵니다.</div></div></div>
</div>
"""
SCRIPTS[1] = """
const sel = new Set(orgs); let showStart = true, cur = new Date(TODAY.getFullYear(), TODAY.getMonth(), 1), picked = null;
const ymd = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
function events() {
  const m = {};
  ITEMS.filter((x) => sel.has(x.org)).forEach((x) => {
    if (x.end) (m[x.end.slice(0, 10)] ||= []).push({ x, k: 'end' });
    if (showStart && x.start) (m[x.start.slice(0, 10)] ||= []).push({ x, k: 'start' });
  });
  return m;
}
function render() {
  const ev = events(), y = cur.getFullYear(), mo = cur.getMonth();
  $('ym').textContent = `${y}년 ${mo + 1}월`;
  const first = new Date(y, mo, 1), startOff = first.getDay(), n = new Date(y, mo + 1, 0).getDate();
  let html = '<div style="display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px">' + ['일','월','화','수','목','금','토'].map((d, i) => `<div style="text-align:center;font-size:12px;color:${i ? (i === 6 ? '#2a78d6' : 'var(--t3)') : '#d03b3b'};padding:4px">${d}</div>`).join('');
  let ends = 0;
  for (let i = 0; i < startOff; i++) html += '<div></div>';
  for (let d = 1; d <= n; d++) {
    const key = ymd(new Date(y, mo, d)), list = ev[key] || [], isToday = key === ymd(TODAY);
    ends += list.filter((e) => e.k === 'end').length;
    const chips = list.slice(0, 3).map((e) => `<div title="${esc(e.x.title)}" style="font-size:11px;line-height:1.35;padding:1px 4px;margin-top:2px;border-radius:3px;border-left:3px solid ${col(e.x)};background:${e.k === 'end' ? '#f1f3f6' : '#fff'};color:${e.k === 'end' ? 'var(--t1)' : 'var(--t3)'};white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${e.k === 'end' ? '■' : '▶'} ${esc(short(e.x.title.replace(/^\\[[^\\]]+\\]\\s*/, ''), 11))}</div>`).join('');
    html += `<div data-k="${key}" style="min-height:96px;border:1px solid ${key === picked ? 'var(--series-1)' : 'var(--line)'};border-radius:7px;padding:4px 5px;cursor:${list.length ? 'pointer' : 'default'};background:${isToday ? '#fff7e6' : '#fff'}"><div style="font-size:12px;color:${isToday ? 'var(--crit)' : 'var(--t2)'};font-weight:${isToday ? 700 : 400}">${d}${list.length > 3 ? `<span style="float:right;color:var(--t3)">+${list.length - 3}</span>` : ''}</div>${chips}</div>`;
  }
  $('cal').innerHTML = html + '</div>';
  $('mcnt').textContent = `이달 마감 ${ends}건`;
  $('cal').querySelectorAll('[data-k]').forEach((c) => c.onclick = () => { picked = c.dataset.k; pick(ev[picked] || [], picked); render(); });
}
function pick(list, k) {
  $('dtitle').textContent = k + ' (' + list.length + '건)';
  $('dlist').innerHTML = list.length ? list.map((e) => `<a class="li" href="${url(e.x)}" target="_blank"><span class="m">${e.k === 'end' ? '■ 마감' : '▶ 시작'}</span><span class="t">${esc(e.x.title)}</span>${orgBadge(e.x)}</a>`).join('') : '<div class="empty">공고가 없습니다.</div>';
}
$('prev').onclick = () => { cur = new Date(cur.getFullYear(), cur.getMonth() - 1, 1); render(); };
$('next').onclick = () => { cur = new Date(cur.getFullYear(), cur.getMonth() + 1, 1); render(); };
$('now').onclick = () => { cur = new Date(TODAY.getFullYear(), TODAY.getMonth(), 1); render(); };
$('tgStart').onclick = (e) => { showStart = !showStart; e.target.classList.toggle('on', showStart); render(); };
$('busy').onclick = () => {
  const c = {}, lo = new Date(TODAY.getFullYear(), TODAY.getMonth() - 12, 1), hi = new Date(TODAY.getFullYear(), TODAY.getMonth() + 6, 1);
  ITEMS.filter((x) => x.end && sel.has(x.org) && dt(x.end) >= lo && dt(x.end) <= hi).forEach((x) => { const k = x.end.slice(0, 7); c[k] = (c[k] || 0) + 1; });
  const best = Object.entries(c).sort((a, b) => b[1] - a[1])[0]; if (best) { cur = new Date(best[0] + '-01T00:00:00'); render(); }
};
orgChips($('orgs'), sel, render); fieldLegend($('legend'));
// 처음에는 최근 1년 중 마감이 가장 많은 달을 보여 준다(오늘이 있는 달에 공고가 적을 수 있음)
$('busy').click();
"""

BODIES[2] = """
<div class="tools panel">
  <div class="chips" id="orgs"></div>
  <div class="chips"><b>범위</b><button class="chip on" data-m="all">전체</button><button class="chip" data-m="open">접수 중·예정·상시</button></div>
</div>
<div style="display:grid;grid-template-columns:1fr 360px;gap:16px;align-items:start">
  <div class="panel"><div id="tree" style="position:relative;height:540px"></div><div class="note">사각형의 넓이 = 공고 수. 아래 띠는 기관 비율, 숫자는 전체 / 접수 중(예정·상시 포함). 사각형을 누르면 오른쪽에 목록이 나옵니다.</div></div>
  <div class="panel"><b id="ptitle">분야를 선택하세요</b><div class="list" id="plist" style="margin-top:10px"><div class="empty">왼쪽 사각형을 누르세요.</div></div></div>
</div>
"""
SCRIPTS[2] = """
const sel = new Set(orgs); let mode = 'all', pickedF = null;
const live = (x) => ['urgent', 'open', 'upcoming', 'always'].includes(x.st);
function squarify(items, x, y, w, h) {
  const total = items.reduce((s, i) => s + i.v, 0), out = [];
  items = items.slice().sort((a, b) => b.v - a.v).map((i) => ({ ...i, a: i.v / total * w * h }));
  const worst = (row, side) => { const s = row.reduce((t, i) => t + i.a, 0); const mx = Math.max(...row.map((i) => i.a)), mn = Math.min(...row.map((i) => i.a)); return Math.max(side * side * mx / (s * s), s * s / (side * side * mn)); };
  while (items.length) {
    const side = Math.min(w, h); let row = [items.shift()];
    while (items.length && worst([...row, items[0]], side) <= worst(row, side)) row.push(items.shift());
    const s = row.reduce((t, i) => t + i.a, 0);
    if (w >= h) { const rw = s / h; let yy = y; row.forEach((i) => { const hh = i.a / rw; out.push({ ...i, x, y: yy, w: rw, h: hh }); yy += hh; }); x += rw; w -= rw; }
    else { const rh = s / w; let xx = x; row.forEach((i) => { const ww = i.a / rh; out.push({ ...i, x: xx, y, w: ww, h: rh }); xx += ww; }); y += rh; h -= rh; }
  }
  return out;
}
function render() {
  const base = ITEMS.filter((x) => sel.has(x.org) && (mode === 'all' || live(x)));
  const g = {}; base.forEach((x) => { (g[prim(x)] ||= []).push(x); });
  const data = Object.entries(g).map(([f, list]) => ({ f, list, v: list.length, live: list.filter(live).length }));
  const el = $('tree'), W = el.clientWidth, H = el.clientHeight;
  el.innerHTML = squarify(data, 0, 0, W, H).map((t) => {
    const byOrg = {}; t.list.forEach((x) => { byOrg[x.org] = (byOrg[x.org] || 0) + 1; });
    const bar = Object.entries(byOrg).map(([o, n]) => `<i style="flex:${n};background:${['#1f3864','#0b6b52','#9a5300','#5b2b9a'][orgC[o] % 4]};opacity:.9" title="${esc(o)} ${n}건"></i>`).join('');
    return `<div data-f="${esc(t.f)}" style="position:absolute;left:${t.x}px;top:${t.y}px;width:${t.w}px;height:${t.h}px;padding:2px;cursor:pointer"><div style="height:100%;border-radius:8px;background:${FC[t.f]};color:#fff;padding:10px 12px;display:flex;flex-direction:column;overflow:hidden;outline:${t.f === pickedF ? '3px solid #14181f' : 'none'}"><b style="font-size:${t.w > 200 ? 17 : 13}px;line-height:1.3">${esc(t.f)}</b><span style="font-size:${t.w > 200 ? 28 : 18}px;font-weight:700;line-height:1.2">${t.v}<small style="font-size:12px;font-weight:400;opacity:.85"> 건 · 접수 ${t.live}</small></span><div style="margin-top:auto;display:flex;height:7px;border-radius:4px;overflow:hidden;gap:1px;background:rgba(255,255,255,.3)">${bar}</div></div></div>`;
  }).join('') || '<div class="empty">조건에 맞는 공고가 없습니다.</div>';
  el.querySelectorAll('[data-f]').forEach((t) => t.onclick = () => { pickedF = t.dataset.f; const l = g[pickedF] || []; $('ptitle').textContent = `${pickedF} · ${l.length}건`; $('plist').innerHTML = l.slice().sort((a, b) => (b.posted || '').localeCompare(a.posted || '')).slice(0, 60).map((x) => `<a class="li" href="${url(x)}" target="_blank"><span class="t">${esc(x.title)}</span>${orgBadge(x)}</a>`).join(''); render(); });
}
document.querySelectorAll('[data-m]').forEach((b) => b.onclick = () => { mode = b.dataset.m; document.querySelectorAll('[data-m]').forEach((c) => c.classList.toggle('on', c === b)); render(); });
orgChips($('orgs'), sel, render); render();
window.onresize = render;
"""

BODIES[3] = """
<div class="tools panel">
  <div class="chips"><b>쌓는 기준</b><button class="chip on" data-by="org">기관별</button><button class="chip" data-by="field">분야별</button></div>
  <div class="chips"><b>기간</b><select id="span"><option value="12">최근 12개월</option><option value="24" selected>최근 24개월</option><option value="120">전체</option></select></div>
  <div class="chips"><b>기준일</b><button class="chip on" data-d="posted">게시일</button><button class="chip" data-d="end">마감일</button></div>
</div>
<div class="panel"><div id="chart"></div><div class="legend" id="legend"></div><div class="note" id="cnt"></div></div>
"""
SCRIPTS[3] = """
let by = 'org', dkey = 'posted', span = 24;
const OC = ['#1f3864', '#2e9e4f', '#d98a1a', '#7a5af8'];
function render() {
  const rows = ITEMS.filter((x) => x[dkey]);
  const months = [...new Set(rows.map((x) => x[dkey].slice(0, 7)))].sort();
  const hi = months[months.length - 1], all = [];
  let [hy, hm] = hi.split('-').map(Number);
  for (let i = 0; i < span; i++) { all.unshift(hy + '-' + String(hm).padStart(2, '0')); if (--hm < 1) { hm = 12; hy--; } if (all[0] <= months[0]) break; }
  const lo = all[0];
  const keys = by === 'org' ? orgs : FIELDS, colr = (k) => by === 'org' ? OC[orgC[k] % 4] : FC[k];
  const cnt = {}; all.forEach((m) => cnt[m] = Object.fromEntries(keys.map((k) => [k, 0])));
  const inRange = rows.filter((x) => cnt[x[dkey].slice(0, 7)]);
  inRange.forEach((x) => { const m = x[dkey].slice(0, 7), k = by === 'org' ? x.org : prim(x); if (cnt[m]) cnt[m][k]++; });
  const tot = all.map((m) => keys.reduce((s, k) => s + cnt[m][k], 0)), max = Math.max(...tot, 1);
  const nice = max <= 10 ? 2 : max <= 30 ? 5 : max <= 60 ? 10 : 20, top = Math.ceil(max / nice) * nice;
  const W = 1180, H = 380, L = 44, B = 46, T = 16, bw = (W - L - 10) / all.length;
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-height:420px">`;
  for (let v = 0; v <= top; v += nice) { const y = T + (H - T - B) * (1 - v / top); svg += `<line x1="${L}" x2="${W}" y1="${y}" y2="${y}" stroke="#e3e7ed"/><text x="${L - 8}" y="${y + 4}" text-anchor="end" font-size="11.5" fill="#7a8494">${v}</text>`; }
  all.forEach((m, i) => {
    let y = H - B; const x = L + i * bw + bw * .16, w = bw * .68;
    keys.forEach((k) => { const h = cnt[m][k] / top * (H - T - B); if (h > 0) { y -= h; svg += `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${colr(k)}" rx="1.5"><title>${m} · ${k} ${cnt[m][k]}건</title></rect>`; } });
    if (tot[i]) svg += `<text x="${x + w / 2}" y="${y - 5}" text-anchor="middle" font-size="11.5" fill="#4a5361" font-weight="600">${tot[i]}</text>`;
    if (all.length <= 26 || i % 3 === 0) svg += `<text x="${x + w / 2}" y="${H - B + 18}" text-anchor="middle" font-size="11.5" fill="#7a8494">${m.slice(2).replace('-', '.')}</text>`;
  });
  $('chart').innerHTML = svg + '</svg>';
  $('legend').innerHTML = keys.filter((k) => all.some((m) => cnt[m][k])).map((k) => `<span><i style="background:${colr(k)}"></i>${esc(k)}</span>`).join('');
  $('cnt').textContent = `${dkey === 'posted' ? '게시일' : '마감일'} 기준 ${inRange.length}건(${lo} ~ ${hi}, 전체 ${rows.length}건 중). 막대에 마우스를 올리면 월·항목별 건수가 보입니다.`;
}
document.querySelectorAll('[data-by]').forEach((b) => b.onclick = () => { by = b.dataset.by; document.querySelectorAll('[data-by]').forEach((c) => c.classList.toggle('on', c === b)); render(); });
$('span').onchange = (e) => { span = +e.target.value; render(); };
document.querySelectorAll('[data-d]').forEach((b) => b.onclick = () => { dkey = b.dataset.d; document.querySelectorAll('[data-d]').forEach((c) => c.classList.toggle('on', c === b)); render(); });
render();
"""

BODIES[4] = """
<div class="tools panel">
  <div class="chips" id="orgs"></div>
  <div class="chips"><button class="chip" id="tgEtc">'기타' 대상 포함</button><button class="chip" id="tgLive">접수 중·예정·상시만</button></div>
</div>
<div class="panel"><div id="heat" style="overflow:auto"></div><div class="note">칸의 숫자 = 그 분야이면서 그 대상을 받는 공고 수(한 공고가 여러 칸에 들어갈 수 있음). 진할수록 많습니다. 칸을 누르면 아래에 목록이 나옵니다.</div></div>
<div class="panel" style="margin-top:14px"><b id="ctitle">칸을 선택하세요</b><div class="list" id="clist" style="margin-top:10px"></div></div>
"""
SCRIPTS[4] = """
const sel = new Set(orgs); let etc = false, liveOnly = false, pk = null;
const TARGETS = ['중소·벤처기업', '창업기업', '중견·대기업', '공공기관·지자체', '대학·병원·연구기관', '협회·단체', '개인', '기타'];
const live = (x) => ['urgent', 'open', 'upcoming', 'always'].includes(x.st);
const tcol = (t) => t;
function render() {
  const rows = ITEMS.filter((x) => sel.has(x.org) && (!liveOnly || live(x)));
  const tg = TARGETS.filter((t) => etc || t !== '기타'), fl = FIELDS.filter((f) => f !== '기타').concat(['기타']);
  const cell = {}; let max = 1;
  rows.forEach((x) => (x.fields.length ? x.fields : ['기타']).forEach((f) => x.targets.forEach((t) => { if (tg.includes(t)) { const k = f + '|' + t; (cell[k] ||= []).push(x); } })));
  Object.values(cell).forEach((l) => max = Math.max(max, l.length));
  const shade = (n) => n ? `rgba(31,56,100,${(.12 + .88 * Math.sqrt(n / max)).toFixed(2)})` : '#f4f6f9';
  let h = '<table style="border-collapse:separate;border-spacing:3px;width:100%"><tr><th></th>' + tg.map((t) => `<th style="font-size:12.5px;color:var(--t2);font-weight:500;padding:4px 2px;width:${88 / tg.length}%">${esc(t)}</th>`).join('') + '<th style="font-size:12.5px;color:var(--t3);font-weight:500">합계</th></tr>';
  fl.forEach((f) => {
    const own = rows.filter((x) => (x.fields.length ? x.fields : ['기타']).includes(f)).length;
    h += `<tr><th style="text-align:left;font-size:13px;font-weight:500;padding:0 10px 0 0;white-space:nowrap"><i style="display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;background:${FC[f]}"></i>${esc(f)}</th>` +
      tg.map((t) => { const n = (cell[f + '|' + t] || []).length, dark = n / max > .45; return `<td data-k="${esc(f + '|' + t)}" style="height:44px;text-align:center;border-radius:6px;background:${shade(n)};color:${dark ? '#fff' : '#14181f'};font-weight:600;cursor:${n ? 'pointer' : 'default'};outline:${pk === f + '|' + t ? '3px solid #d03b3b' : 'none'}">${n || ''}</td>`; }).join('') +
      `<td style="text-align:center;color:var(--t3);font-size:12.5px">${own}</td></tr>`;
  });
  $('heat').innerHTML = h + '</table>';
  $('heat').querySelectorAll('[data-k]').forEach((c) => c.onclick = () => {
    const l = cell[c.dataset.k] || []; if (!l.length) return; pk = c.dataset.k;
    $('ctitle').textContent = c.dataset.k.replace('|', ' × ') + ' · ' + l.length + '건';
    $('clist').innerHTML = l.slice(0, 60).map((x) => `<a class="li" href="${url(x)}" target="_blank"><span class="t">${esc(x.title)}</span><span class="m">${x.label}</span>${orgBadge(x)}</a>`).join(''); render();
  });
}
$('tgEtc').onclick = (e) => { etc = !etc; e.target.classList.toggle('on', etc); render(); };
$('tgLive').onclick = (e) => { liveOnly = !liveOnly; e.target.classList.toggle('on', liveOnly); render(); };
orgChips($('orgs'), sel, render); render();
"""


def page(i, data_json):
    name, title, desc = PAGES[i]
    nav = "".join(f'<a href="{n}.html" class="{"on" if j == i else ""}">{t}</a>' for j, (n, t, _) in enumerate(PAGES))
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>[시각화 {name.split('_')[0]}] {title}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@300;400;500;600;700&display=swap">
<style>{CSS}</style></head><body>
<header class="gnb"><div class="in"><span class="logo">공모사업 AI RADAR<small>시각화 시안</small></span><nav><a href="index.html">시안 목록</a>{nav}</nav></div></header>
<main class="wrap"><h1>{title}</h1><p class="sub">{desc} · 실제 DB의 노출·검토 공고 {{N}}건 기준(시안)</p>
{BODIES[i]}
</main>
<script type="application/json" id="data">{data_json}</script>
<script>{JS_COMMON}{SCRIPTS[i]}</script></body></html>"""


def main():
    app = create_app()
    with app.app_context():
        items, total = public_items(get_db(), app.config)
    slim = [{"id": x["id"], "title": x["title"], "org": x["org"], "orgc": x["org_c"], "start": x["start"] or "", "end": x["end"] or "",
             "posted": (x["posted"] or "")[:10], "st": x["st"], "label": x["label"], "fields": x["fields"], "targets": x["targets"],
             "kind": x["kind"]} for x in items]
    data = {"today": date.today().isoformat(), "base": "http://127.0.0.1:5000", "items": slim}
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    OUT.mkdir(exist_ok=True)
    for i, (name, *_rest) in enumerate(PAGES):
        (OUT / f"{name}.html").write_text(page(i, data_json).replace("{N}", str(len(slim))), encoding="utf-8")
    cards = "".join(f'<a class="card" href="{n}.html"><b>{n.split("_")[0]}</b><h3>{t}</h3><p>{d}</p></a>' for n, t, d in PAGES)
    (OUT / "index.html").write_text(f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>시각화 시안 목록</title><style>{CSS}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}}.card{{display:block;background:#fff;border:1px solid var(--line);border-radius:10px;padding:18px;text-decoration:none}}
.card:hover{{border-color:var(--series-1)}}.card b{{color:var(--series-1);font-size:13px}}.card h3{{margin:4px 0 6px;font-size:18px}}.card p{{margin:0;color:var(--t2)}}</style></head><body>
<header class="gnb"><div class="in"><span class="logo">공모사업 AI RADAR<small>시각화 시안</small></span></div></header>
<main class="wrap"><h1>시각화 시안 5종</h1><p class="sub">수요자 화면에 붙일 시각적 서비스 후보. 실제 DB의 노출·검토 공고 {len(slim)}건으로 그린 시안이며 앱에는 적용하지 않았습니다.</p><div class="grid">{cards}</div></main></body></html>""", encoding="utf-8")
    print(f"시각화 시안 {len(PAGES)}개 생성 — 공고 {len(slim)}건 → {OUT}")


if __name__ == "__main__":
    main()
