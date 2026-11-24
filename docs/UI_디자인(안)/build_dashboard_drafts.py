"""대시보드 시안 5종 생성 — 상단 검색·필터, 좌측 목록(리스트/카드), 우측 통계 패널.

    cd <프로젝트 루트> && python "docs/UI_디자인(안)/build_dashboard_drafts.py"

산출물: docs/UI_디자인(안)/시각화/대시보드_안1~5.html + 대시보드_index.html (파일 하나씩 단독으로 열림, 외부 라이브러리 없음).
실제 DB의 공고로 그리며 앱에는 적용하지 않는다. 통계 요소(도넛·막대·달력·히트맵)를 누르면 목록이 그 조건으로 걸러진다.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "시각화"

from app import create_app  # noqa: E402
from app.db import get_db  # noqa: E402
from app.services.public import SQL, build_item  # noqa: E402

SHORT = {"정보통신산업진흥원": "NIPA", "한국지능정보사회진흥원": "NIA", "한국전파진흥협회": "RAPA"}

VARIANTS = [
    {"n": 1, "name": "종합 현황판", "view": "list", "pool": "public",
     "desc": "핵심 수치 4개 + 월별 게시 추이 + 기관 비율 + 접수 상태 비율. 처음 들어온 사람이 전체 규모를 한눈에 보는 구성",
     "stats": "kpi4,trend,orgdonut,statusbar"},
    {"n": 2, "name": "마감 달력", "view": "card", "pool": "public",
     "desc": "작은 월간 달력에 날짜별 마감 건수를 표시하고, 날짜를 누르면 그날 마감 공고만 목록에 나옴. 임박 공고와 분야 TOP도 함께",
     "stats": "calendar,soonlist,fieldtop"},
    {"n": 3, "name": "분야·대상 분석", "view": "list", "pool": "public",
     "desc": "어떤 분야·누구를 위한 공고가 많은지 보는 구성. 분야 막대, 대상 도넛, 지원방식 비율, 분야×대상 히트맵",
     "stats": "fieldbars,targetdonut,methodbar,heat"},
    {"n": 4, "name": "마감 일정 보드", "view": "card", "pool": "public",
     "desc": "앞으로 마감될 공고의 주간 분포와 가장 급한 공고 3건, 접수 중 비율 게이지, 최근 30일 게시 추이",
     "stats": "dcards,weekly,gauge,spark"},
    {"n": 5, "name": "운영 담당자용", "view": "list", "pool": "all",
     "desc": "담당자가 노출·검토·제외 판정과 기간 누락을 점검하는 구성. 목록에서 '노출로 변경'을 눌러 볼 수 있음(시안이라 저장 안 됨)",
     "stats": "opkpi,expdonut,orgstack,collect,why"},
]

CSS = r"""
:root{color-scheme:light;--bg:#f4f6f9;--surface:#fff;--line:#e3e7ed;--line2:#cfd6df;--t1:#14181f;--t2:#4a5361;--t3:#7a8494;
--navy:#1f3864;--navy2:#2b4c86;--soft:#e8eef8;--blue:#2a78d6;--good:#0ca30c;--warn:#e08a00;--bad:#d03b3b;
--c0:#2a78d6;--c1:#1a9e8f;--c2:#e08a00;--c3:#7a5cc8;--c4:#d6567a;--c5:#6b7b8f;
--sans:"IBM Plex Sans KR","Malgun Gothic","Noto Sans KR",sans-serif}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t1);font-family:var(--sans);font-size:14px;line-height:1.5}
a{color:inherit;text-decoration:none}button{font:inherit;cursor:pointer}
.gnb{background:var(--navy);color:#fff}.gnb .in{max-width:1440px;margin:0 auto;padding:0 24px;height:54px;display:flex;align-items:center;gap:28px}
.gnb b{font-size:16px;letter-spacing:-.02em}.gnb small{opacity:.7;font-weight:400;margin-left:8px}.gnb .r{margin-left:auto;font-size:12.5px;opacity:.8}
.draft{background:#fff8e1;border-bottom:1px solid #f0dca0;font-size:12.5px;color:#7a5a00}.draft .in{max-width:1440px;margin:0 auto;padding:7px 24px;display:flex;gap:14px;flex-wrap:wrap;align-items:center}
.draft a{text-decoration:underline}.draft b{margin-right:4px}
.filter{background:var(--surface);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
.filter .in{max-width:1440px;margin:0 auto;padding:12px 24px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.filter input[type=search]{flex:1;min-width:220px;max-width:420px;padding:9px 12px;border:1px solid var(--line2);border-radius:8px;font:inherit}
.filter select{padding:9px 10px;border:1px solid var(--line2);border-radius:8px;font:inherit;background:#fff;max-width:170px}
.filter .reset{border:1px solid var(--line2);background:#fff;border-radius:8px;padding:9px 12px;color:var(--t2)}
.filter .cnt{margin-left:auto;color:var(--t2);font-size:13px}.filter .cnt b{color:var(--t1);font-size:15px}
.chips{max-width:1440px;margin:0 auto;padding:0 24px 10px;display:flex;gap:6px;flex-wrap:wrap}
.chip{background:var(--soft);color:var(--navy);border-radius:999px;padding:3px 10px;font-size:12.5px;border:0}.chip::after{content:" ✕";opacity:.6}
.main{max-width:1440px;margin:0 auto;padding:18px 24px 60px;display:grid;grid-template-columns:minmax(0,1.2fr) minmax(380px,.95fr);gap:20px;align-items:start}
@media(max-width:1000px){.main{grid-template-columns:1fr}}
.left h2,.panel h3{margin:0}.lhead{display:flex;align-items:center;margin-bottom:10px;gap:10px}.lhead h2{font-size:16px}
.seg{margin-left:auto;display:inline-flex;border:1px solid var(--line2);border-radius:8px;overflow:hidden}.seg button{border:0;background:#fff;padding:5px 12px;color:var(--t2)}.seg button.on{background:var(--navy);color:#fff}
.sortsel{padding:5px 8px;border:1px solid var(--line2);border-radius:8px;font:inherit;background:#fff}
.rows{background:var(--surface);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.row{display:grid;grid-template-columns:auto 1fr auto;gap:4px 12px;padding:11px 14px;border-bottom:1px solid var(--line);align-items:center}.row:last-child{border:0}.row:hover{background:#fafbfd}
.row .t{font-weight:600;letter-spacing:-.01em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.row .m{grid-column:2;color:var(--t3);font-size:12.5px;display:flex;gap:10px;flex-wrap:wrap}
.row .rt{grid-row:1/3;grid-column:3;text-align:right;display:flex;flex-direction:column;gap:5px;align-items:flex-end}
.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}@media(max-width:1250px){.cards{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:8px}.card:hover{border-color:var(--blue)}
.card .top{display:flex;align-items:center;gap:6px}.card .t{font-weight:600;line-height:1.4;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;letter-spacing:-.01em}
.card .s{color:var(--t2);font-size:13px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.card .f{margin-top:auto;color:var(--t3);font-size:12.5px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.org{font-size:11.5px;font-weight:700;border-radius:4px;padding:1px 7px;color:#fff;white-space:nowrap}.org.o0{background:var(--c0)}.org.o1{background:var(--c1)}.org.o2{background:var(--c2)}.org.o3{background:var(--c3)}.org.o4{background:var(--c4)}.org.o5{background:var(--c5)}
.pill{font-size:12px;font-weight:700;border-radius:999px;padding:2px 9px;white-space:nowrap}.pill.urgent{background:#fde8e8;color:#b42323}.pill.open{background:#e7f6e7;color:#0a7a0a}.pill.upcoming{background:#e8f1fd;color:#1a4f9c}.pill.always{background:#eef0f3;color:#4a5361}.pill.ended{background:#eef0f3;color:#8a93a0}
.tag{background:var(--soft);color:var(--navy);border-radius:4px;padding:0 6px;font-size:12px}.xp{font-size:11.5px;font-weight:700;border-radius:4px;padding:1px 7px}.xp.노출{background:#e7f6e7;color:#0a7a0a}.xp.검토{background:#fff3d6;color:#8a5a00}.xp.제외{background:#eef0f3;color:#5b6574}.xp.미판별{background:#fde8e8;color:#b42323}
.mbtn{border:1px solid #0a7a0a;color:#0a7a0a;background:#fff;border-radius:6px;padding:2px 8px;font-size:12px}.mbtn.g{border-color:var(--line2);color:var(--t2)}
.more{display:block;margin:12px auto 0;border:1px solid var(--line2);background:#fff;border-radius:8px;padding:8px 22px;color:var(--t2)}.empty{padding:40px;text-align:center;color:var(--t3)}
.stats{display:flex;flex-direction:column;gap:14px;position:sticky;top:64px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.panel h3{font-size:14px;margin-bottom:10px;display:flex;align-items:baseline;gap:8px}.panel h3 small{color:var(--t3);font-weight:400;font-size:12px}
.kpis{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.kpi{border:1px solid var(--line);border-radius:8px;padding:10px 12px;cursor:pointer;background:#fff;text-align:left}.kpi:hover{border-color:var(--blue)}.kpi.on{border-color:var(--blue);background:var(--soft)}
.kpi b{display:block;font-size:26px;letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1.15}.kpi span{font-size:12.5px;color:var(--t2)}.kpi i{font-style:normal;font-size:11.5px;margin-left:6px}.up{color:var(--good)}.dn{color:var(--bad)}
.leg{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:8px;font-size:12.5px;color:var(--t2)}.leg button{border:0;background:none;padding:2px 4px;border-radius:4px;display:inline-flex;align-items:center;gap:5px;color:var(--t2)}.leg button:hover,.leg button.on{background:var(--soft)}.sw{width:10px;height:10px;border-radius:2px;display:inline-block}
.donutwrap{display:flex;gap:16px;align-items:center}.donutwrap svg{flex:none}.donutwrap .leg{flex-direction:column;margin:0}
.hb{display:grid;grid-template-columns:104px 1fr 34px;gap:8px;align-items:center;padding:3px 0;border:0;background:none;width:100%;text-align:left;border-radius:4px}.hb:hover,.hb.on{background:var(--soft)}.hb .n{font-size:12.5px;color:var(--t2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.hb .bar{height:10px;background:#eef1f5;border-radius:5px;overflow:hidden}.hb .bar i{display:block;height:100%;background:var(--blue);border-radius:5px}.hb .v{font-size:12.5px;text-align:right;font-variant-numeric:tabular-nums}
.stack{display:flex;height:16px;border-radius:8px;overflow:hidden;background:#eef1f5}.stack button{border:0;height:100%;padding:0}.stack button:hover{opacity:.8}
.cal{width:100%;border-collapse:collapse;table-layout:fixed}.cal th{font-size:11.5px;color:var(--t3);font-weight:500;padding:2px 0}.cal td{height:42px;text-align:center;padding:1px;vertical-align:top}
.cal button{width:100%;height:100%;border:1px solid transparent;border-radius:6px;background:none;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;padding-top:3px;gap:1px;font-size:12.5px;color:var(--t1)}
.cal button:hover{background:var(--soft)}.cal button.dim{color:#b5bcc7}.cal button.today{border-color:var(--navy)}.cal button.sel{background:var(--navy);color:#fff}.cal .n{font-size:10.5px;font-weight:700;border-radius:999px;min-width:17px;padding:0 4px;color:#fff;background:var(--c2)}.cal .n.h{background:var(--bad)}.cal button.sel .n{background:#fff;color:var(--navy)}
.calhead{display:flex;align-items:center;gap:8px;margin-bottom:6px}.calhead b{font-size:15px}.calhead button{border:1px solid var(--line2);background:#fff;border-radius:6px;width:28px;height:26px}.calhead .today{margin-left:auto;width:auto;padding:0 8px;font-size:12px}
.mini{display:grid;grid-template-columns:auto 1fr auto;gap:8px;align-items:center;padding:6px 0;border-bottom:1px solid var(--line);font-size:13px}.mini:last-child{border:0}.mini .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dcards{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.dc{border:1px solid var(--line);border-radius:8px;padding:10px;background:#fff;text-align:left}.dc:hover{border-color:var(--blue)}.dc .d{font-size:24px;font-weight:700;color:var(--bad);letter-spacing:-.02em}.dc .t{font-size:12.5px;line-height:1.35;margin-top:3px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.dc .o{margin-top:4px;font-size:11.5px;color:var(--t3)}
.heat{display:grid;gap:3px;font-size:11.5px}.heat .h{color:var(--t3);text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.heat .rl{color:var(--t2);display:flex;align-items:center;overflow:hidden;white-space:nowrap}.heat button{border:0;border-radius:4px;height:28px;font-size:11.5px;color:var(--t1);background:#eef1f5}.heat button:hover{outline:2px solid var(--navy)}
.note{font-size:12px;color:var(--t3);margin-top:6px}svg text{font-family:var(--sans)}.cols button,.cols rect{cursor:pointer}
.warnbox{border:1px solid #f0c9c9;background:#fff5f5;color:#8a2020;border-radius:8px;padding:9px 12px;font-size:13px;display:flex;gap:10px;align-items:center}.warnbox button{margin-left:auto;border:1px solid #d9a0a0;background:#fff;color:#8a2020;border-radius:6px;padding:3px 10px}
"""

JS = r"""
const D=JSON.parse(document.getElementById('data').textContent);
let NOW=new Date(D.now+'T00:00:00');const DAY=86400000;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const iso=d=>d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
const P=s=>new Date(s.slice(0,10)+'T00:00:00');const kd=s=>s?s.slice(0,10).replace(/-/g,'.'):'';
const COL=['var(--c0)','var(--c1)','var(--c2)','var(--c3)','var(--c4)','var(--c5)'];
const ST={urgent:'마감 임박',open:'접수 중',upcoming:'접수 예정',always:'상시 모집',ended:'접수 마감'};
const ALLITEMS=D.items;
function recalc(){   // 기준일을 바꿔 볼 수 있도록 접수 상태·D-day·새 공고를 다시 계산한다(서버 계산 규칙과 같음)
  ALLITEMS.forEach(x=>{const s=x.start?P(x.start):null,e=x.end?new Date(P(x.end).getTime()+DAY-1000):null;let st,dl=null;
    if(/^\s*\[?\s*접수\s*마감/.test(x.title))st='ended';
    else if(!s&&!e)st=(x.posted&&NOW-P(x.posted)>365*DAY)?'ended':'always';
    else if(s&&NOW<s)st='upcoming';else if(e&&NOW>e)st='ended';else if(!e)st='always';
    else{dl=Math.round((P(x.end).getTime()-NOW.getTime())/DAY);st=dl<=7?'urgent':'open'}
    x.st=st;x.dleft=dl;x.label=dl!==null?(dl===0?'오늘 마감':'D-'+dl):ST[st];
    const pd=x.posted?NOW-P(x.posted):-1;x.new=pd>=0&&pd<7*DAY})}
const POOL=V.pool==='all'?ALLITEMS:ALLITEMS.filter(x=>x.exposure==='노출');
const manual={};   // 시안용: 담당자가 누른 '노출로 변경'(저장되지 않음)
const expOf=x=>manual[x.id]?'노출':x.exposure;
const S={weekFrom:null,kind:'',method:'',q:'',org:'',field:'',target:'',status:'',exp:'',day:'',kpi:'',sort:'default',view:V.view,shown:12,calY:NOW.getFullYear(),calM:NOW.getMonth()};
const uniq=(f)=>[...new Set(POOL.flatMap(f))].filter(Boolean);
const count=(arr,f)=>{const m={};arr.forEach(x=>f(x).forEach(k=>{if(k)m[k]=(m[k]||0)+1}));return Object.entries(m).sort((a,b)=>b[1]-a[1])};
const active=x=>x.st==='open'||x.st==='urgent'||x.st==='upcoming'||x.st==='always';
function match(x,skip=''){
  if(S.q){const t=(x.title+' '+x.biz+' '+x.summary+' '+x.orgs).toLowerCase();if(!S.q.toLowerCase().split(/\s+/).every(w=>t.includes(w)))return false}
  if(skip!=='org'&&S.org&&x.orgs!==S.org)return false;
  if(skip!=='field'&&S.field&&!x.fields.includes(S.field))return false;
  if(skip!=='target'&&S.target&&!x.targets.includes(S.target))return false;
  if(skip!=='status'&&S.status){if(S.status==='active'){if(!(x.st==='open'||x.st==='urgent'))return false}else if(x.st!==S.status)return false}
  if(skip!=='exp'&&S.exp&&expOf(x)!==S.exp)return false;
  if(skip!=='day'&&S.day&&(x.end||'').slice(0,10)!==S.day)return false;
  if(skip!=='day'&&S.weekFrom&&!(x.end&&P(x.end).getTime()>=S.weekFrom&&P(x.end).getTime()<S.weekFrom+7*DAY))return false;
  if(S.kind&&(x.kind||'미분류')!==S.kind)return false;if(S.method&&!x.methods.includes(S.method))return false;
  if(skip!=='kpi'&&S.kpi){const k=S.kpi;
    if(k==='soon'&&!(x.dleft!==null&&x.dleft<=7&&x.st!=='ended'))return false;
    if(k==='new'&&!x.new)return false;if(k==='noperiod'&&x.end)return false;
    if(k==='act'&&!(x.st==='open'||x.st==='urgent'))return false}
  return true}
const FIL=()=>POOL.filter(x=>match(x));
function sortItems(a){const r=[...a];
  if(S.sort==='end')r.sort((p,q)=>((p.st==='ended'?1:0)-(q.st==='ended'?1:0))||((p.end||'9')<(q.end||'9')?-1:1));
  else if(S.sort==='views')r.sort((p,q)=>q.views-p.views);else r.sort((p,q)=>(q.posted||'')<(p.posted||'')?-1:1);return r}
const orgBadge=x=>`<span class="org o${x.orgc}">${esc(x.orgs)}</span>`;
const pill=x=>`<span class="pill ${x.st}">${esc(x.label)}</span>`;
const per=x=>x.end?`${kd(x.start||x.posted)} ~ ${kd(x.end)}`:'기간 미표기';
const tags=x=>x.fields.slice(0,2).map(f=>`<span class="tag">${esc(f)}</span>`).join('');
const opCell=x=>V.pool==='all'?`<span class="xp ${expOf(x)}">${expOf(x)}${manual[x.id]?' · 수동':''}</span>${expOf(x)!=='노출'?`<button class="mbtn" data-man="${x.id}">노출로 변경</button>`:(manual[x.id]?`<button class="mbtn g" data-man="${x.id}">자동 판정으로</button>`:'')}`:'';
function listHtml(items){
  const sh=items.slice(0,S.shown);if(!sh.length)return '<div class="rows"><div class="empty">조건에 맞는 공고가 없습니다.</div></div>';
  const more=items.length>sh.length?`<button class="more" data-more="1">더 보기 (${items.length-sh.length}건 남음)</button>`:'';
  if(S.view==='card')return `<div class="cards">${sh.map(x=>`<a class="card" href="#"><div class="top">${orgBadge(x)}${pill(x)}<span style="margin-left:auto;display:flex;gap:4px;align-items:center">${opCell(x)}</span></div><div class="t">${esc(x.title)}</div><div class="s">${esc(x.summary||'요약 없음')}</div><div class="f">${tags(x)}<span>${per(x)}</span><span>조회 ${x.views.toLocaleString()}</span></div></a>`).join('')}</div>${more}`;
  return `<div class="rows">${sh.map(x=>`<a class="row" href="#">${orgBadge(x)}<div class="t">${esc(x.title)}</div><div class="rt">${pill(x)}${opCell(x)}</div><div class="m"><span>${per(x)}</span><span>게시 ${kd(x.posted)}</span>${tags(x)}</div></a>`).join('')}</div>${more}`}
/* ── 차트 조각 ── */
function donut(rows,key,sel,size=150){const tot=rows.reduce((a,r)=>a+r.v,0)||1,R=size/2-4,r=R-24,c=size/2;let a0=-Math.PI/2,paths='';
  rows.forEach((r_,i)=>{const a1=a0+r_.v/tot*Math.PI*2-(rows.length>1?0.012:0);const lg=a1-a0>Math.PI?1:0;const f=(R,a)=>[c+R*Math.cos(a),c+R*Math.sin(a)];
    const [x0,y0]=f(R,a0),[x1,y1]=f(R,a1),[x2,y2]=f(r,a1),[x3,y3]=f(r,a0);
    paths+=`<path data-k="${key}" data-v="${esc(r_.k)}" d="M${x0},${y0} A${R},${R} 0 ${lg} 1 ${x1},${y1} L${x2},${y2} A${r},${r} 0 ${lg} 0 ${x3},${y3}Z" fill="${r_.color||COL[i%6]}" opacity="${sel&&sel!==r_.k?.35:1}" style="cursor:pointer"><title>${esc(r_.k)} ${r_.v}건</title></path>`;a0+=r_.v/tot*Math.PI*2});
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${paths}<text x="${c}" y="${c-2}" text-anchor="middle" font-size="22" font-weight="700" fill="#14181f">${tot.toLocaleString()}</text><text x="${c}" y="${c+16}" text-anchor="middle" font-size="11" fill="#7a8494">건</text></svg>`}
const legend=(rows,key,sel)=>`<div class="leg">${rows.map((r,i)=>`<button data-k="${key}" data-v="${esc(r.k)}" class="${sel===r.k?'on':''}"><i class="sw" style="background:${r.color||COL[i%6]}"></i>${esc(r.k)} <b>${r.v}</b></button>`).join('')}</div>`;
const hbars=(rows,key,sel,max)=>{const m=max||Math.max(1,...rows.map(r=>r[1]));return rows.map(([k,v],i)=>`<button class="hb ${sel===k?'on':''}" data-k="${key}" data-v="${esc(k)}"><span class="n">${esc(k)}</span><span class="bar"><i style="width:${v/m*100}%;background:${COL[i%6]}"></i></span><span class="v">${v}</span></button>`).join('')};
function cols(rows,{h=120,color='var(--blue)',key='',sel='',labelEvery=1}={}){const w=Math.max(260,rows.length*34),m=Math.max(1,...rows.map(r=>r.v)),bw=w/rows.length;
  return `<svg class="cols" width="100%" viewBox="0 0 ${w} ${h+26}" preserveAspectRatio="xMidYMid meet">${rows.map((r,i)=>{const bh=r.v/m*h,x=i*bw+bw*.18;
   return `<g data-k="${key}" data-v="${esc(r.k)}" style="cursor:${key?'pointer':'default'}"><rect x="${x}" y="${h-bh+2}" width="${bw*.64}" height="${bh}" rx="3" fill="${r.color||color}" opacity="${sel&&sel!==r.k?.4:1}"><title>${esc(r.label||r.k)} ${r.v}건</title></rect>
   <text x="${i*bw+bw/2}" y="${h-bh-2}" text-anchor="middle" font-size="10.5" fill="#4a5361">${r.v||''}</text>${i%labelEvery===0?`<text x="${i*bw+bw/2}" y="${h+16}" text-anchor="middle" font-size="10.5" fill="#7a8494">${esc(r.label||r.k)}</text>`:''}</g>`}).join('')}</svg>`}
function spark(rows,{h=70}={}){const w=360,m=Math.max(1,...rows.map(r=>r.v)),st=w/(rows.length-1||1);const pts=rows.map((r,i)=>[i*st,h-r.v/m*(h-8)]);
  const d=pts.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+','+p[1].toFixed(1)).join('');
  return `<svg width="100%" viewBox="0 0 ${w} ${h+4}" preserveAspectRatio="none"><path d="${d}L${w},${h}L0,${h}Z" fill="var(--blue)" opacity=".12"/><path d="${d}" fill="none" stroke="var(--blue)" stroke-width="2"/>${pts.map((p,i)=>rows[i].v?`<circle cx="${p[0]}" cy="${p[1]}" r="2.4" fill="var(--blue)"><title>${esc(rows[i].label)} ${rows[i].v}건</title></circle>`:'').join('')}</svg>`}
const stackbar=(rows,key,sel)=>{const t=rows.reduce((a,r)=>a+r.v,0)||1;return `<div class="stack">${rows.map((r,i)=>`<button data-k="${key}" data-v="${esc(r.k)}" title="${esc(r.k)} ${r.v}건" style="width:${r.v/t*100}%;background:${r.color||COL[i%6]};opacity:${sel&&sel!==r.k?.35:1}"></button>`).join('')}</div>`};
const ST_COLOR={urgent:'#d03b3b',open:'#0ca30c',upcoming:'#2a78d6',always:'#7a8494',ended:'#c3c9d2'};
const stRows=items=>Object.keys(ST).map(k=>({k,v:items.filter(x=>x.st===k).length,color:ST_COLOR[k]})).filter(r=>r.v);
const stLegend=(rows,sel)=>`<div class="leg">${rows.map(r=>`<button data-k="status" data-v="${r.k}" class="${sel===r.k?'on':''}"><i class="sw" style="background:${r.color}"></i>${ST[r.k]} <b>${r.v}</b></button>`).join('')}</div>`;
const monthKey=s=>s.slice(0,7);
function monthRows(P_,n=12){const rows=[];for(let i=n-1;i>=0;i--){const d=new Date(NOW.getFullYear(),NOW.getMonth()-i,1),k=d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0');
  rows.push({k,label:(d.getMonth()===0||i===n-1?String(d.getFullYear()).slice(2)+'.':'')+(d.getMonth()+1)+'월',v:P_.filter(x=>(x.posted||'').slice(0,7)===k).length})}return rows}
/* ── 통계 패널 ── */
const PANELS={
 kpi4(F){const P_=POOL.filter(x=>match(x,'kpi'));const n=f=>P_.filter(f).length;
  return `<div class="panel"><h3>핵심 수치 <small>누르면 목록이 걸러집니다</small></h3><div class="kpis">
  <button class="kpi ${S.kpi===''?'on':''}" data-k="kpi" data-v=""><b>${P_.length}</b><span>전체 공고</span></button>
  <button class="kpi ${S.kpi==='act'?'on':''}" data-k="kpi" data-v="act"><b>${n(x=>x.st==='open'||x.st==='urgent')}</b><span>접수 중</span></button>
  <button class="kpi ${S.kpi==='soon'?'on':''}" data-k="kpi" data-v="soon"><b style="color:var(--bad)">${n(x=>x.dleft!==null&&x.dleft<=7&&x.st!=='ended')}</b><span>7일 내 마감</span></button>
  <button class="kpi ${S.kpi==='new'?'on':''}" data-k="kpi" data-v="new"><b>${n(x=>x.new)}</b><span>새 공고(7일)</span></button></div></div>`},
 trend(F){const rows=monthRows(POOL.filter(x=>match(x,'day')));
  return `<div class="panel"><h3>월별 게시 추이 <small>최근 12개월 · 게시일 기준 · 현재 조건</small></h3>${cols(rows,{h:110})}</div>`},
 orgdonut(F){const P_=POOL.filter(x=>match(x,'org'));const rows=count(P_,x=>[x.orgs]).map(([k,v])=>({k,v,color:COL[{NIPA:0,NIA:1,RAPA:2}[k]??3]}));
  return `<div class="panel"><h3>기관별 비율</h3><div class="donutwrap">${donut(rows,'org',S.org)}${legend(rows,'org',S.org)}</div></div>`},
 statusbar(F){const P_=POOL.filter(x=>match(x,'status'));const rows=stRows(P_);
  return `<div class="panel"><h3>접수 상태 비율</h3>${stackbar(rows,'status',S.status)}${stLegend(rows,S.status)}</div>`},
 calendar(F){const y=S.calY,m=S.calM,P_=POOL.filter(x=>match(x,'day'));const cnt={};P_.forEach(x=>{if(x.end)cnt[x.end.slice(0,10)]=(cnt[x.end.slice(0,10)]||0)+1});
  const first=new Date(y,m,1),start=new Date(y,m,1-first.getDay()),today=iso(NOW);let tr='';
  for(let w=0;w<6;w++){tr+='<tr>';for(let d=0;d<7;d++){const dt=new Date(start.getTime()+(w*7+d)*DAY),k=iso(dt),n=cnt[k]||0;
   tr+=`<td><button data-k="day" data-v="${k}" class="${dt.getMonth()!==m?'dim':''} ${k===today?'today':''} ${S.day===k?'sel':''}">${dt.getDate()}${n?`<span class="n ${k>=today&&k<=iso(new Date(NOW.getTime()+7*DAY))?'h':''}">${n}</span>`:''}</button></td>`}tr+='</tr>'}
  return `<div class="panel"><h3>마감 달력 <small>숫자 = 그날 마감 공고 수 · 붉은색 = 7일 내</small></h3><div class="calhead"><button data-cal="-1">‹</button><b>${y}년 ${m+1}월</b><button data-cal="1">›</button><button class="today" data-cal="0">오늘</button></div>
  <table class="cal"><tr>${'일월화수목금토'.split('').map(d=>`<th>${d}</th>`).join('')}</tr>${tr}</table></div>`},
 soonlist(F){const L=POOL.filter(x=>match(x,'day')&&x.dleft!==null&&x.st!=='ended').sort((a,b)=>a.dleft-b.dleft).slice(0,5);
  return `<div class="panel"><h3>곧 마감되는 공고 <small>가까운 순 5건</small></h3>${L.length?L.map(x=>`<a class="mini" href="#">${pill(x)}<span class="t">${esc(x.title)}</span>${orgBadge(x)}</a>`).join(''):'<div class="note">현재 조건에 마감 예정 공고가 없습니다.</div>'}</div>`},
 fieldtop(F){const P_=POOL.filter(x=>match(x,'field'));const r=count(P_,x=>x.fields).slice(0,6);
  return `<div class="panel"><h3>분야 TOP 6</h3>${hbars(r,'field',S.field)}</div>`},
 fieldbars(F){const P_=POOL.filter(x=>match(x,'field'));const r=count(P_,x=>x.fields).slice(0,9);
  return `<div class="panel"><h3>사업분야별 공고 수 <small>한 공고가 여러 분야에 속할 수 있음</small></h3>${hbars(r,'field',S.field)}</div>`},
 targetdonut(F){const P_=POOL.filter(x=>match(x,'target'));const r=count(P_,x=>x.targets).slice(0,6).map(([k,v])=>({k,v}));
  return `<div class="panel"><h3>지원 대상 비율</h3><div class="donutwrap">${donut(r,'target',S.target)}${legend(r,'target',S.target)}</div></div>`},
 methodbar(F){const r=count(F,x=>x.methods).filter(([k])=>k!=='해당 없음').slice(0,6);
  return `<div class="panel"><h3>지원방식 <small>현재 조건</small></h3>${hbars(r,'method',S.method)}</div>`},
 heat(F){const fs=count(POOL,x=>x.fields).slice(0,6).map(r=>r[0]),ts=count(POOL,x=>x.targets).slice(0,5).map(r=>r[0]);const P_=POOL.filter(x=>match(x,'field')&&match(x,'target'));
  const cell=(f,t)=>P_.filter(x=>x.fields.includes(f)&&x.targets.includes(t)).length;let mx=1;fs.forEach(f=>ts.forEach(t=>mx=Math.max(mx,cell(f,t))));
  let h=`<div class="heat" style="grid-template-columns:96px repeat(${ts.length},1fr)"><span></span>${ts.map(t=>`<span class="h" title="${esc(t)}">${esc(t.replace('·','·'))}</span>`).join('')}`;
  fs.forEach(f=>{h+=`<span class="rl">${esc(f)}</span>`;ts.forEach(t=>{const n=cell(f,t),a=n/mx;h+=`<button data-k="heat" data-v="${esc(f)}|${esc(t)}" style="background:${n?`rgba(42,120,214,${.12+a*.75})`:'#eef1f5'};color:${a>.55?'#fff':'#14181f'}">${n||''}</button>`})});
  return `<div class="panel"><h3>분야 × 대상 <small>칸을 누르면 두 조건으로 걸러집니다</small></h3>${h}</div></div>`},
 dcards(F){const L=POOL.filter(x=>match(x,'day')&&x.dleft!==null&&x.st!=='ended').sort((a,b)=>a.dleft-b.dleft).slice(0,3);
  return `<div class="panel"><h3>가장 급한 공고 <small>마감 가까운 순</small></h3>${L.length?`<div class="dcards">${L.map(x=>`<button class="dc" data-k="q" data-v="${esc(x.title.slice(0,12))}"><div class="d">${x.dleft===0?'오늘':'D-'+x.dleft}</div><div class="t">${esc(x.title)}</div><div class="o">${esc(x.orgs)} · ~${kd(x.end).slice(5)}</div></button>`).join('')}</div>`:'<div class="note">현재 조건에 마감 예정 공고가 없습니다.</div>'}</div>`},
 weekly(F){const P_=POOL.filter(x=>match(x,'day'));const t0=NOW.getTime()-NOW.getDay()*DAY;const rows=[];
  for(let i=-2;i<10;i++){const a=t0+i*7*DAY,b=a+7*DAY;const v=P_.filter(x=>x.end&&P(x.end).getTime()>=a&&P(x.end).getTime()<b).length;const d=new Date(a);
   rows.push({k:iso(d),label:`${d.getMonth()+1}/${d.getDate()}`,v,color:i<0?'#c3c9d2':(i===0?'var(--bad)':'var(--blue)')})}
  return `<div class="panel"><h3>주간 마감 건수 <small>회색 = 지난 주 · 붉은색 = 이번 주</small></h3>${cols(rows,{h:110,key:'week',labelEvery:2})}<div class="note">주를 누르면 그 주 마감 공고만 보입니다.</div></div>`},
 gauge(F){const P_=POOL.filter(x=>match(x,'status'));const a=P_.filter(x=>x.st==='open'||x.st==='urgent').length,t=P_.length||1,p=a/t,w=220,r=84,c=[w/2,100];
  const arc=(f)=>{const ang=Math.PI*(1-f);return [c[0]+r*Math.cos(ang),c[1]-r*Math.sin(ang)]};const [x1,y1]=arc(p);
  return `<div class="panel"><h3>접수 중 비율</h3><div style="text-align:center"><svg width="${w}" height="120" viewBox="0 0 ${w} 120"><path d="M${c[0]-r},${c[1]} A${r},${r} 0 0 1 ${c[0]+r},${c[1]}" fill="none" stroke="#eef1f5" stroke-width="18" stroke-linecap="round"/><path d="M${c[0]-r},${c[1]} A${r},${r} 0 ${p>.5?1:0} 1 ${x1},${y1}" fill="none" stroke="var(--good)" stroke-width="18" stroke-linecap="round"/><text x="${c[0]}" y="${c[1]-8}" text-anchor="middle" font-size="28" font-weight="700">${Math.round(p*100)}%</text><text x="${c[0]}" y="${c[1]+12}" text-anchor="middle" font-size="12" fill="#7a8494">${a} / ${P_.length}건 접수 중</text></svg></div>${stLegend(stRows(P_),S.status)}</div>`},
 spark(F){const P_=POOL.filter(x=>match(x,'day'));const rows=[];for(let i=29;i>=0;i--){const d=new Date(NOW.getTime()-i*DAY),k=iso(d);rows.push({label:`${d.getMonth()+1}/${d.getDate()}`,v:P_.filter(x=>(x.posted||'').slice(0,10)===k).length})}
  const sum=rows.reduce((a,r)=>a+r.v,0);return `<div class="panel"><h3>최근 30일 게시 <small>${sum}건</small></h3>${spark(rows)}</div>`},
 opkpi(F){const n=(f)=>POOL.filter(f).length;const ex=x=>expOf(x);
  return `<div class="panel"><h3>수집·판정 현황 <small>전체 ${POOL.length.toLocaleString()}건</small></h3><div class="kpis">
  <button class="kpi" data-k="exp" data-v="노출"><b style="color:var(--good)">${n(x=>ex(x)==='노출')}</b><span>노출</span></button>
  <button class="kpi" data-k="exp" data-v="검토"><b style="color:var(--warn)">${n(x=>ex(x)==='검토')}</b><span>검토 필요</span></button>
  <button class="kpi" data-k="exp" data-v="제외"><b style="color:var(--t3)">${n(x=>ex(x)==='제외')}</b><span>제외</span></button>
  <button class="kpi ${S.kpi==='noperiod'?'on':''}" data-k="kpi" data-v="noperiod"><b style="color:var(--bad)">${n(x=>ex(x)==='노출'&&!x.end)}</b><span>노출 중 기간 없음</span></button></div></div>`},
 expdonut(F){const P_=POOL.filter(x=>match(x,'exp'));const rows=['노출','검토','제외'].map(k=>({k,v:P_.filter(x=>expOf(x)===k).length,color:{노출:'#0ca30c',검토:'#e08a00',제외:'#c3c9d2'}[k]})).filter(r=>r.v);
  return `<div class="panel"><h3>노출 여부 비율</h3><div class="donutwrap">${donut(rows,'exp',S.exp)}${legend(rows,'exp',S.exp)}</div></div>`},
 orgstack(F){const P_=POOL.filter(x=>match(x,'org'));const orgs=count(P_,x=>[x.orgs]).map(r=>r[0]);
  return `<div class="panel"><h3>기관별 판정 구성</h3>${orgs.map(o=>{const L=P_.filter(x=>x.orgs===o);const rows=['노출','검토','제외'].map(k=>({k,v:L.filter(x=>expOf(x)===k).length,color:{노출:'#0ca30c',검토:'#e08a00',제외:'#c3c9d2'}[k]}));
   return `<div style="margin:8px 0"><div style="display:flex;font-size:12.5px;margin-bottom:3px"><button style="border:0;background:none;padding:0;font-weight:600" data-k="org" data-v="${o}">${o}</button><span style="margin-left:auto;color:var(--t3)">${L.length}건 · 노출 ${rows[0].v}</span></div>${stackbar(rows,'exp',S.exp)}</div>`}).join('')}</div>`},
 collect(F){const rows=monthRows(POOL.filter(x=>match(x,'day')));
  return `<div class="panel"><h3>월별 수집 건수 <small>최근 12개월 · 게시일 기준</small></h3>${cols(rows,{h:100})}</div>`},
 why(F){const P_=POOL.filter(x=>match(x,'exp')&&expOf(x)!=='노출');const r=count(P_,x=>[x.kind||'미분류']).slice(0,6);const np=POOL.filter(x=>expOf(x)==='노출'&&!x.end).length;
  return `<div class="panel"><h3>노출되지 않은 공고의 유형 <small>제외·검토 사유 참고</small></h3>${hbars(r,'kind',S.kind)}${np?`<div class="warnbox" style="margin-top:10px">⚠ 노출 중인데 접수 기간이 없는 공고 ${np}건<button data-k="kpi" data-v="noperiod">보기</button></div>`:''}</div>`}
};
/* ── 렌더 ── */
const $=id=>document.getElementById(id);
function fillSelects(){const mk=(id,vals,lab)=>{$(id).innerHTML=`<option value="">${lab} 전체</option>`+vals.map(v=>`<option>${esc(v)}</option>`).join('')};
  mk('fOrg',uniq(x=>[x.orgs]),'기관');mk('fField',count(POOL,x=>x.fields).map(r=>r[0]),'분야');mk('fTarget',count(POOL,x=>x.targets).map(r=>r[0]),'대상');
  $('fStatus').innerHTML='<option value="">접수 상태 전체</option><option value="active">접수 중(임박 포함)</option>'+Object.keys(ST).map(k=>`<option value="${k}">${ST[k]}</option>`).join('');
  if($('fExp'))$('fExp').innerHTML='<option value="">노출 여부 전체</option><option>노출</option><option>검토</option><option>제외</option>'}
function render(){
  $('fq').value=S.q;['Org:org','Field:field','Target:target','Status:status','Exp:exp'].forEach(p=>{const[i,k]=p.split(':');if($('f'+i))$('f'+i).value=S[k]});
  const F=sortItems(FIL());$('cnt').innerHTML=`조건에 맞는 공고 <b>${F.length.toLocaleString()}</b>건`;
  const ch=[['q','검색: '+S.q],['org','기관: '+S.org],['field','분야: '+S.field],['target','대상: '+S.target],['status','상태: '+(ST[S.status]||'접수 중')],['exp','노출: '+S.exp],['day','마감일: '+S.day],['kind','유형: '+S.kind],['method','지원방식: '+S.method],['weekFrom','마감 주: '+(S.weekFrom?iso(new Date(S.weekFrom)):'')],['kpi','조건: '+({act:'접수 중',soon:'7일 내 마감',new:'새 공고',noperiod:'기간 없음'}[S.kpi]||'')]].filter(([k])=>S[k]);
  $('chips').innerHTML=ch.map(([k,t])=>`<button class="chip" data-clear="${k}">${esc(t)}</button>`).join('');
  $('list').innerHTML=listHtml(F);$('vList').classList.toggle('on',S.view==='list');$('vCard').classList.toggle('on',S.view==='card');
  $('stats').innerHTML=V.stats.map(p=>PANELS[p](F)).join('')}
document.addEventListener('click',e=>{
  const t=e.target.closest('[data-k],[data-more],[data-clear],[data-cal],[data-man]');if(!t){return}
  if(t.dataset.man){const id=+t.dataset.man;if(manual[id])delete manual[id];else manual[id]=1;render();e.preventDefault();return}
  if(t.dataset.more){S.shown+=12;render();return}
  if(t.dataset.clear){S[t.dataset.clear]=t.dataset.clear==='weekFrom'?null:'';S.shown=12;render();return}
  if(t.dataset.cal!==undefined){const c=+t.dataset.cal;if(c===0){S.calY=NOW.getFullYear();S.calM=NOW.getMonth()}else{const d=new Date(S.calY,S.calM+c,1);S.calY=d.getFullYear();S.calM=d.getMonth()}render();return}
  const k=t.dataset.k,v=t.dataset.v;
  if(k==='heat'){const[f,tg]=v.split('|');S.field=f;S.target=tg}
  else if(k==='week'){const a=P(v).getTime();S.day='';S.weekFrom=S.weekFrom===a?null:a}
  else if(k==='status'){S.status=S.status===v?'':v}
  else if(k==='kpi'){S.kpi=S.kpi===v?'':v}
  else if(k==='day'){S.day=S.day===v?'':v}
  else if(k==='q'){S.q=v}
  else{S[k]=S[k]===v?'':v}
  S.shown=12;render();e.preventDefault()});
$('fq').addEventListener('input',e=>{S.q=e.target.value.trim();S.shown=12;render()});
[['fOrg','org'],['fField','field'],['fTarget','target'],['fStatus','status'],['fExp','exp']].forEach(([i,k])=>{if($(i))$(i).addEventListener('change',e=>{S[k]=e.target.value;S.shown=12;render()})});
$('reset').addEventListener('click',()=>{Object.assign(S,{kind:'',method:'',q:'',org:'',field:'',target:'',status:'',exp:'',day:'',kpi:'',shown:12,weekFrom:null});render()});
$('vList').onclick=()=>{S.view='list';render()};$('vCard').onclick=()=>{S.view='card';render()};
$('sort').addEventListener('change',e=>{S.sort=e.target.value;render()});
const asof=$('asof');asof.value=D.now;
asof.addEventListener('change',e=>{if(!e.target.value)return;NOW=new Date(e.target.value+'T00:00:00');recalc();S.calY=NOW.getFullYear();S.calM=NOW.getMonth();S.day='';S.weekFrom=null;S.shown=12;render()});
fillSelects();recalc();render();
"""

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>대시보드 시안 안__N__ — __NAME__</title><style>__CSS__</style></head><body>
<header class="gnb"><div class="in"><b>공모사업 AI RADAR<small>__NAME__</small></b><span class="r">기준일 <input type="date" id="asof" style="border:0;border-radius:4px;padding:2px 6px;font:inherit"> · 실제 수집 데이터 기반 시안(날짜를 바꿔 보세요)</span></div></header>
<div class="draft"><div class="in"><b>대시보드 시안 안__N__</b><span>__DESC__</span><span style="margin-left:auto">__NAV__</span></div></div>
<div class="filter"><div class="in">
  <input id="fq" type="search" placeholder="공고명·사업명·요약 검색">
  <select id="fOrg"></select><select id="fField"></select><select id="fTarget"></select><select id="fStatus"></select>__EXPSEL__
  <button class="reset" id="reset">초기화</button><span class="cnt" id="cnt"></span></div><div class="chips" id="chips"></div></div>
<div class="main">
  <section class="left"><div class="lhead"><h2>공고 목록</h2>
    <select class="sortsel" id="sort"><option value="default">최신 게시순</option><option value="end">마감 임박순</option><option value="views">조회 많은 순</option></select>
    <span class="seg"><button id="vList">리스트</button><button id="vCard">카드</button></span></div><div id="list"></div></section>
  <aside class="stats" id="stats"></aside>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>const V=__V__;__JS__</script></body></html>
"""


def slim(x, public_view):
    return {
        "id": x["id"], "title": x["title"], "orgs": SHORT.get(x["org"], x["org"]), "orgc": x["org_c"], "biz": x["biz"],
        "start": x["start"] or "", "end": x["end"] or "", "posted": (x["posted"] or "")[:10],
        "fields": x["fields"], "targets": x["targets"], "methods": x["methods"],
        "summary": (x["summary"] or "")[:120] if x["exposure"] == "노출" or not public_view else "",
        "views": x["views"], "st": x["st"], "label": x["label"], "dleft": x["dleft"], "new": x["new"],
        "exposure": x["exposure"], "kind": x["kind"] or "",
    }


def main():
    app = create_app()
    now = datetime.now()
    with app.app_context():
        rows = get_db().execute(SQL).fetchall()
        items = [build_item(r, now, app.config["PUBLIC_NEW_DAYS"]) for r in rows]
    data = json.dumps({"now": now.strftime("%Y-%m-%d"), "items": [slim(x, False) for x in items]}, ensure_ascii=False).replace("</", "<\\/")
    OUT.mkdir(exist_ok=True)
    nav = " · ".join(f'<a href="대시보드_안{v["n"]}.html">안{v["n"]}</a>' for v in VARIANTS) + ' · <a href="대시보드_index.html">목록</a>'
    for v in VARIANTS:
        cfg = {"pool": v["pool"], "view": v["view"], "stats": v["stats"].split(",")}
        exp_sel = '<select id="fExp"></select>' if v["pool"] == "all" else ""
        html = (PAGE.replace("__CSS__", CSS).replace("__N__", str(v["n"])).replace("__NAME__", v["name"]).replace("__NOW__", now.strftime("%Y-%m-%d"))
                .replace("__DESC__", v["desc"]).replace("__NAV__", nav).replace("__EXPSEL__", exp_sel)
                .replace("__DATA__", data).replace("__V__", json.dumps(cfg, ensure_ascii=False)).replace("__JS__", JS))
        (OUT / f"대시보드_안{v['n']}.html").write_text(html, encoding="utf-8")
    cards = "".join(f'<a class="c" href="대시보드_안{v["n"]}.html"><b>안{v["n"]} · {v["name"]}</b><p>{v["desc"]}</p><small>목록: {"리스트" if v["view"] == "list" else "카드"}형 시작 · {"전체 판정(담당자용)" if v["pool"] == "all" else "수요자 노출 공고"}</small></a>' for v in VARIANTS)
    (OUT / "대시보드_index.html").write_text(
        f'<!doctype html><html lang="ko"><meta charset="utf-8"><title>대시보드 시안 5종</title><style>body{{font-family:"Malgun Gothic",sans-serif;background:#f4f6f9;margin:0;padding:30px;color:#14181f}}'
        f'h1{{font-size:20px}}.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;max-width:1100px}}.c{{background:#fff;border:1px solid #e3e7ed;border-radius:10px;padding:16px;text-decoration:none;color:inherit}}'
        f'.c:hover{{border-color:#2a78d6}}.c p{{font-size:13.5px;color:#4a5361;margin:6px 0}}small{{color:#7a8494}}</style>'
        f'<h1>대시보드 시안 5종 <small>(기준일 {now:%Y-%m-%d}, 실제 수집 데이터)</small></h1><p>공통: 상단 검색·필터 → 좌측 목록(리스트/카드) → 우측 통계. 통계를 누르면 목록이 걸러집니다.</p><div class="g">{cards}</div></html>',
        encoding="utf-8")
    pub = [x for x in items if x["exposure"] == "노출"]
    print(f"공고 {len(items)}건(노출 {len(pub)}건) → {OUT}")


if __name__ == "__main__":
    main()
