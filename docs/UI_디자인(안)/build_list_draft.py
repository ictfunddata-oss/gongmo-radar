"""목록 화면 서비스 추가 시안 생성 — 현재 수요자 목록 화면에 4가지 작은 서비스를 얹은 단독 HTML.

    cd <프로젝트 루트> && python "docs/UI_디자인(안)/build_list_draft.py"

산출물: docs/UI_디자인(안)/시각화/목록화면_서비스추가.html. 실제 DB의 노출·검토 공고로 그리며 앱에는 적용하지 않는다.
서비스: ① 마감 임박 띠 ② 새 공고 배지 ③ 분야 분포 미니 막대 ④ 관심 공고 저장
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "시각화" / "목록화면_서비스추가.html"

from app import create_app  # noqa: E402
from app.db import get_db  # noqa: E402
from app.services.public import public_items  # noqa: E402

EXTRA_CSS = """
.draft-bar { background:#fff8e1; border-bottom:1px solid #f0dca0; font-size:13px; }
.draft-bar .in { max-width:1280px; margin:0 auto; padding:10px 28px; display:flex; flex-wrap:wrap; gap:8px 18px; align-items:center; }
.draft-bar b { color:#7a5a00; }
.sw { display:inline-flex; gap:6px; align-items:center; cursor:pointer; user-select:none; }
.sw input { accent-color:#1f3864; }
.dbtn { border:1px solid #d9c07a; background:#fff; border-radius:999px; padding:3px 11px; font:inherit; font-size:12.5px; cursor:pointer; color:#5a4400; }
.dbtn.on { background:#7a5a00; color:#fff; border-color:#7a5a00; }
.no { display:inline-flex; width:18px; height:18px; border-radius:50%; background:#d03b3b; color:#fff; font-size:11px; font-weight:700; align-items:center; justify-content:center; margin-right:5px; vertical-align:1px; }
.soon { background:#fff; border:1px solid var(--line); border-radius:10px; padding:12px 16px; margin-bottom:14px; }
.soon h3 { margin:0 0 8px; font-size:14.5px; display:flex; align-items:center; }
.soon .row { display:flex; gap:8px; overflow-x:auto; padding-bottom:4px; }
.sc { flex:none; width:230px; border:1px solid var(--line); border-radius:8px; padding:8px 10px; text-decoration:none; background:#fff; }
.sc:hover { border-color:var(--series-1); }
.sc .d { font-weight:700; font-size:13px; } .sc .d.hot { color:#b42323; }
.sc .t { font-size:13px; line-height:1.35; margin-top:2px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.sc .o { font-size:11.5px; color:var(--t3); margin-top:3px; }
.fbar { display:block; height:5px; border-radius:3px; background:var(--series-1); opacity:.55; margin:2px 0 0 24px; }
.side label { flex-wrap:wrap; row-gap:0; }
.new { font-size:10.5px; font-weight:800; color:#fff; background:#e5484d; border-radius:3px; padding:1px 6px; letter-spacing:.02em; }
.star { margin-left:auto; border:none; background:none; font-size:20px; line-height:1; cursor:pointer; color:#b8c0cc; padding:0 2px; }
.star.on { color:#f5a524; }
.card .ctop { position:relative; }
.fav-chip { border:1px solid var(--line2); background:#fff; border-radius:999px; padding:5px 12px; font:inherit; font-size:13px; cursor:pointer; }
.fav-chip.on { background:#fff3d6; border-color:#f5a524; color:#7a5a00; }
.gnb .fav { margin-left:auto; font-size:13px; opacity:.9; }
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const ITEMS = D.items, $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (n) => Number(n || 0).toLocaleString('ko-KR');
const kdate = (s) => (s ? s.slice(0, 10).replace(/-/g, '.') : '');
const ktime = (s) => (s && s.length > 10 ? s.slice(11, 16) : '');
const iso = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
const day = 86400000, P = (s) => new Date(s.slice(0, 10) + 'T00:00:00');
const url = (x) => D.base + '/notice/' + x.id;
const ST = { urgent: ['마감 임박', '⏰'], open: ['접수 중', '●'], upcoming: ['접수 예정', '◷'], always: ['상시 모집', '∞'], ended: ['접수 마감', '■'] };

let ref = P(new URLSearchParams(location.search).get('ref') || D.today), on = { soon: true, nw: true, mini: true, fav: true }, org = new Set(), field = new Set(), favOnly = false, page = 12;
let favs = new Set(); try { favs = new Set(JSON.parse(localStorage.getItem('draftFavs') || '[]')); } catch (e) {}
const saveFavs = () => { try { localStorage.setItem('draftFavs', JSON.stringify([...favs])); } catch (e) {} };

function status(x) {            // 서버의 services/public.py status()와 같은 규칙을 시안 기준일로 다시 계산
  const s = x.start ? new Date(x.start.length === 10 ? x.start + 'T00:00:00' : x.start) : null;
  const e = x.end ? new Date(x.end.length === 10 ? x.end + 'T23:59:59' : x.end) : null;
  const o = { dleft: null, pct: null };
  if (/^\s*\[?\s*접수\s*마감/.test(x.title)) o.st = 'ended';
  else if (!s && !e) o.st = (x.posted && ref - P(x.posted) > 365 * day) ? 'ended' : 'always';
  else if (s && ref < s) o.st = 'upcoming';
  else if (e && ref > e) o.st = 'ended';
  else if (!e) o.st = 'always';
  else { o.dleft = Math.floor((new Date(e.getFullYear(), e.getMonth(), e.getDate()) - new Date(ref.getFullYear(), ref.getMonth(), ref.getDate())) / day); o.st = o.dleft <= 7 ? 'urgent' : 'open'; }
  if (s && e && e > s) o.pct = Math.round(Math.min(100, Math.max(0, (ref - s) / (e - s) * 100)));
  o.label = o.dleft !== null ? (o.dleft === 0 ? '오늘 마감' : 'D-' + o.dleft) : ST[o.st][0];
  return o;
}
const isNew = (x) => x.posted && ref - P(x.posted) >= 0 && ref - P(x.posted) <= 7 * day;
const FIELDS = [...new Set(ITEMS.flatMap((x) => x.fields))].sort((a, b) => a.localeCompare(b, 'ko'));
const ORGS = [...new Set(ITEMS.map((x) => x.org))];

function card(x) {
  const o = x._s, fav = favs.has(x.id);
  const bar = x.start && x.end
    ? `<div><div class="period">신청 ${kdate(x.start)} ${ktime(x.start)} ~ ${kdate(x.end)} ${ktime(x.end)}</div><div class="ptrack ${o.st}"><div class="pfill" style="width:${o.pct ?? 0}%"></div></div></div>`
    : `<div class="period">신청 기간: 상시 모집(원문 확인)</div>`;
  return `<article class="card">
    <div class="ctop"><span class="dday ${o.st}">${ST[o.st][1]} ${esc(o.label)}</span>${on.nw && isNew(x) ? '<span class="new">NEW</span>' : ''}${x.revision ? `<span class="kind">${esc(x.revision)}</span>` : ''}<span class="org" data-c="${x.orgc}" style="${on.fav ? 'margin-left:auto' : ''}">${esc(x.org)}</span>${on.fav ? `<button class="star ${fav ? 'on' : ''}" data-id="${x.id}" title="${fav ? '관심 공고에서 빼기' : '관심 공고로 저장'}">${fav ? '★' : '☆'}</button>` : ''}</div>
    <h4><a href="${url(x)}" target="_blank">${esc(x.title)}</a></h4>
    <div class="biz">사업명 · ${esc(x.biz || '표시 없음')}</div>
    <div class="sum">${x.summary ? esc(x.summary) : '본문 요약 없음 — 상세 내용은 첨부 파일(' + x.files + '개)에 있습니다.'}</div>
    <div class="tags">${x.fields.filter((t) => t !== '기타').map((t) => `<span class="tag">#${esc(t)}</span>`).join('')}${x.targets.filter((t) => t !== '기타').map((t) => `<span class="tag t">대상 · ${esc(t)}</span>`).join('')}</div>
    ${bar}
    <div class="cfoot"><span>게시 ${kdate(x.posted)} · 조회 ${fmt(x.views)} · 첨부 ${x.files}개</span><a class="go" href="${url(x)}" target="_blank">자세히 보기 →</a></div></article>`;
}

function render() {
  ITEMS.forEach((x) => x._s = status(x));
  const base = ITEMS.filter((x) => (!org.size || org.has(x.org)) && (!field.size || x.fields.some((f) => field.has(f))) && (!favOnly || favs.has(x.id)));
  const endKey = (x) => (x._s.st === 'urgent' || x._s.st === 'open' ? x.end || '9' : x._s.st === 'upcoming' ? '8' + (x.start || '') : x._s.st === 'always' ? '9a' : '9z');
  const rows = base.slice().sort((a, b) => endKey(a).localeCompare(endKey(b)) || (b.posted || '').localeCompare(a.posted || ''));

  // ① 마감 임박 띠 — 접수 중 공고 중 마감이 가까운 순 6건(30일 이내)
  const soon = ITEMS.filter((x) => x._s.dleft !== null && x._s.dleft <= 30 && (!org.size || org.has(x.org))).sort((a, b) => a._s.dleft - b._s.dleft).slice(0, 10);
  $('soon').style.display = on.soon ? '' : 'none';
  $('soonrow').innerHTML = soon.length ? soon.map((x) => `<a class="sc" href="${url(x)}" target="_blank"><div class="d ${x._s.dleft <= 3 ? 'hot' : ''}">⏰ ${esc(x._s.label)}</div><div class="t">${esc(x.title)}</div><div class="o">${esc(x.org)} · ~${kdate(x.end)}</div></a>`).join('')
    : '<div class="empty" style="padding:10px;text-align:left">30일 안에 마감되는 공고가 없습니다. 위의 시안 기준일을 바꿔 보세요.</div>';
  $('soonh').innerHTML = `<span class="no">1</span>곧 마감되는 공고 <small style="font-weight:400;color:var(--t3);margin-left:8px">30일 이내 ${soon.length}건 · 마감 빠른 순</small>`;

  // 통계 카드
  const cnt = (f) => ITEMS.filter(f).length;
  $('stats').innerHTML = [['✅', cnt((x) => ['urgent', 'open'].includes(x._s.st)), '지금 신청할 수 있는 공모'], ['⏰', cnt((x) => x._s.st === 'urgent'), '7일 안에 마감'], ['🗓', cnt((x) => x._s.st === 'upcoming'), '곧 접수 시작'], ['∞', cnt((x) => x._s.st === 'always'), '상시 모집']]
    .map(([ic, n, l]) => `<div class="stat"><div class="ic">${ic}</div><div><div class="v">${fmt(n)}건</div><div class="l">${l}</div></div></div>`).join('');

  // ③ 분야 분포 미니 막대 + 기관
  const fc = Object.fromEntries(FIELDS.map((f) => [f, ITEMS.filter((x) => x.fields.includes(f)).length])), fmax = Math.max(...Object.values(fc));
  $('side').innerHTML = `<h3>기관</h3>` + ORGS.map((o) => `<label><input type="checkbox" data-g="org" value="${esc(o)}" ${org.has(o) ? 'checked' : ''}>${esc(o)}<i>${ITEMS.filter((x) => x.org === o).length}</i></label>`).join('') +
    `<h3>지원 분야 ${on.mini ? '<span class="no">3</span>' : ''}</h3>` + FIELDS.map((f) => `<label><input type="checkbox" data-g="field" value="${esc(f)}" ${field.has(f) ? 'checked' : ''}>${esc(f)}<i>${fc[f]}</i>${on.mini ? `<span style="flex-basis:100%;height:0"></span><span class="fbar" style="width:${Math.max(4, fc[f] / fmax * 100 * .78)}%"></span>` : ''}</label>`).join('') +
    `<hr><button class="reset" id="reset">조건 초기화</button>`;
  $('side').querySelectorAll('input').forEach((c) => c.onchange = () => { const s = c.dataset.g === 'org' ? org : field; c.checked ? s.add(c.value) : s.delete(c.value); page = 12; render(); });
  $('reset').onclick = () => { org.clear(); field.clear(); favOnly = false; page = 12; render(); };

  // 목록
  $('cnt').innerHTML = `조건에 맞는 공고 <b>${fmt(rows.length)}건</b>`;
  $('favchip').style.display = on.fav ? '' : 'none';
  $('favchip').className = 'fav-chip' + (favOnly ? ' on' : '');
  $('favchip').innerHTML = `${on.fav ? '<span class="no">4</span>' : ''}★ 관심 공고만 보기 (${favs.size})`;
  $('favnav').textContent = on.fav ? `★ 관심 공고 ${favs.size}` : '';
  $('cards').innerHTML = rows.slice(0, page).map(card).join('') || `<div class="empty">${favOnly ? '아직 저장한 관심 공고가 없습니다. 카드의 ☆를 눌러 보세요.' : '조건에 맞는 공고가 없습니다.'}</div>`;
  $('more').style.display = rows.length > page ? '' : 'none';
  $('cards').querySelectorAll('.star').forEach((b) => b.onclick = () => { const id = +b.dataset.id; favs.has(id) ? favs.delete(id) : favs.add(id); saveFavs(); render(); });
  $('reftxt').textContent = iso(ref);
  document.querySelectorAll('[data-ref]').forEach((b) => b.classList.toggle('on', b.dataset.ref === iso(ref)));
  const nn = ITEMS.filter(isNew).length;
  $('newtxt').textContent = on.nw ? `NEW 배지(게시 7일 이내): 현재 ${nn}건` : '';
}
document.querySelectorAll('[data-sw]').forEach((c) => c.onchange = () => { on[c.dataset.sw] = c.checked; render(); });
document.querySelectorAll('[data-ref]').forEach((b) => b.onclick = () => { ref = P(b.dataset.ref); page = 12; render(); });
$('favchip').onclick = () => { favOnly = !favOnly; page = 12; render(); };
$('more').onclick = () => { page += 12; render(); };
render();
"""


def main():
    app = create_app()
    with app.app_context():
        items, _ = public_items(get_db(), app.config)
    slim = [{"id": x["id"], "title": x["title"], "org": x["org"], "orgc": x["org_c"], "start": x["start"] or "", "end": x["end"] or "",
             "posted": (x["posted"] or "")[:10], "fields": x["fields"], "targets": x["targets"], "views": x["views"], "files": x["files"],
             "summary": x["summary"], "biz": x["biz"], "revision": x["revision"]} for x in items]
    data = {"today": date.today().isoformat(), "base": "http://127.0.0.1:5000", "items": slim}
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    css = (ROOT / "app" / "static" / "public.css").read_text(encoding="utf-8")
    html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>[시안] 목록 화면 서비스 추가</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@300;400;500;600;700&display=swap">
<style>{css}{EXTRA_CSS}</style></head><body>
<header class="gnb"><div class="in"><span class="logo">ICT기금 공모사업<small>공모정보 통합 조회</small></span><nav><a class="on" href="#">공모사업 찾기</a></nav><span class="fav" id="favnav"></span></div></header>
<div class="draft-bar"><div class="in"><b>시안</b>
  <span>서비스 켜기/끄기:</span>
  <label class="sw"><input type="checkbox" data-sw="soon" checked><span class="no">1</span>마감 임박 띠</label>
  <label class="sw"><input type="checkbox" data-sw="nw" checked><span class="no">2</span>NEW 배지</label>
  <label class="sw"><input type="checkbox" data-sw="mini" checked><span class="no">3</span>분야 분포 막대</label>
  <label class="sw"><input type="checkbox" data-sw="fav" checked><span class="no">4</span>관심 공고 저장</label>
  <span style="margin-left:auto">시안 기준일 <b id="reftxt"></b>
   <button class="dbtn" data-ref="{date.today().isoformat()}">오늘</button><button class="dbtn" data-ref="2026-06-22">2026-06-22</button><button class="dbtn" data-ref="2026-04-02">2026-04-02</button><button class="dbtn" data-ref="2026-03-18">2026-03-18</button></span>
  <span class="note" id="newtxt" style="margin:0 0 0 10px"></span></div></div>
<section class="hero"><div class="in">
  <h1>우리 기관에 맞는 ICT기금 공모사업을 찾아보세요</h1>
  <p>전담기관 홈페이지에 흩어진 공모 공고를 모아, 지원 분야와 대상별로 정리했습니다.</p>
  <div class="sbox"><input placeholder="예: 바우처, GPU, 해외진출, 입주" aria-label="공고 검색"><button>검색</button></div>
</div></section>
<main class="wrap">
  <section class="stats" id="stats"></section>
  <div class="soon" id="soon"><h3 id="soonh"></h3><div class="row" id="soonrow"></div></div>
  <div class="layout">
    <aside class="side" id="side"></aside>
    <section>
      <div class="bar"><div class="cnt" id="cnt"></div><button type="button" id="favchip" class="fav-chip"></button></div>
      <div class="cards" id="cards"></div>
      <button class="more" id="more" style="display:block;margin:18px auto 0;padding:10px 28px;border:1px solid var(--line2);background:#fff;border-radius:6px;font:inherit;cursor:pointer">더 보기(시안은 12건씩, 실제 화면은 쪽 번호)</button>
    </section>
  </div>
</main>
<script type="application/json" id="data">{data_json}</script>
<script>{JS}</script></body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"생성 — 공고 {len(slim)}건 → {OUT}")


if __name__ == "__main__":
    main()
