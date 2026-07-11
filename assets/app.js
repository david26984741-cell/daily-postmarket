/* 每日盤後資料 — 共用前端邏輯 (純前端, 讀取 ./data/*.json) */
const DATA = "data/";
const CATS = [
  {id:"options_foreign", title:"外資選擇權",       file:"options_foreign.json"},
  {id:"options_dealer",  title:"自營選擇權",       file:"options_dealer.json"},
  {id:"foreign_fut_spot",title:"外資期貨、現貨",   file:"foreign_fut_spot.json"},
  {id:"large_opt",       title:"大額交易人選擇權", file:"large_opt.json"},
  {id:"large_fut_txf",   title:"大額交易人期貨",   file:"large_fut_txf.json"},
  {id:"stocks",          title:"大額交易人股票期貨",file:null},
  {id:"rank",            title:"股期增減排行",      file:null},
  {id:"analysis",        title:"籌碼研究",          file:null},
  {id:"help",            title:"使用說明",          file:null},
];
const PAGE_MAP = {stocks:"stocks.html", rank:"rank.html", analysis:"analysis.html", help:"help.html"};
const catHref = c => PAGE_MAP[c.id] || `detail.html?cat=${c.id}`;
const UPDATE_NOTE = " · 每交易日約 16:00 前更新";
const $ = (s,r=document)=>r.querySelector(s);
const el = (t,c,h)=>{const e=document.createElement(t); if(c)e.className=c; if(h!=null)e.innerHTML=h; return e;};
async function getJSON(f){const r=await fetch(DATA+f,{cache:"no-store"}); if(!r.ok)throw new Error(f); return r.json();}
const fmt = n => (n===null||n===undefined||n==="")?"–":Number(n).toLocaleString("en-US");
function signed(n){ if(n===null||n===undefined)return "–"; const c=n>0?"up":(n<0?"down":""); const s=n>0?"+":""; return `<span class="${c}">${s}${fmt(n)}</span>`; }
function navActive(id){document.querySelectorAll("nav.main a").forEach(a=>{if(a.dataset.k===id)a.classList.add("active");});}

/* ---------- 統一符號:較前一日增減 (▲紅增 / ▼綠減) ---------- */
function arrow(d){
  if(d===null||d===undefined) return '<span class="mut arw">—</span>';
  if(d>0) return `<span class="up arw">▲ +${fmt(d)}</span>`;
  if(d<0) return `<span class="down arw">▼ ${fmt(Math.abs(d))}</span>`;
  return '<span class="mut arw">▬ 0</span>';
}
function biasArrow(s){
  if(s>0) return '<span class="up bias">▲</span>';
  if(s<0) return '<span class="down bias">▼</span>';
  return '<span class="mut bias">▬</span>';
}
function netCell(v,d){ const c=v>0?'up':(v<0?'down':''); const s=v>0?'+':'';
  let h=`<span class="${c}">${s}${fmt(v)}</span>`; if(d!==undefined) h+=` <span class="dlt">${arrow(d)}</span>`; return {raw:v,html:h}; }
function cntCell(v,d){ let h=`<span>${fmt(v)}</span>`; if(d!==undefined) h+=` <span class="dlt">${arrow(d)}</span>`; return {raw:v,html:h}; }

/* ---------- 排序表格 ---------- */
function sortableTable(headers, rows, opts={}){
  const wrap = el("div","tablewrap");
  const t = el("table", opts.dense?"dense":"");
  const thead = el("thead"); const htr = el("tr");
  headers.forEach((h,i)=>{
    const th = el("th", h.sort===false?"noSort":"", h.label+(h.sort===false?"":' <span class="ar">↕</span>'));
    if(h.sort!==false){ th.onclick=()=>doSort(i,h); }
    htr.appendChild(th);
  });
  thead.appendChild(htr); t.appendChild(thead);
  const tb = el("tbody"); t.appendChild(tb);
  let sortState={i:-1,dir:1};
  function render(rs){
    tb.innerHTML="";
    rs.forEach(r=>{
      const tr=el("tr");
      headers.forEach(h=>{
        const v=r[h.label];
        const td=el("td", h.num?"num":"");
        td.innerHTML = (v&&v.html)?v.html:(v===undefined?"":v);
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
  }
  function doSort(i,h){
    sortState.dir = sortState.i===i ? -sortState.dir : 1;
    sortState.i=i;
    const key=h.label;
    rows.sort((a,b)=>{
      let av=a[key], bv=b[key];
      av = (av&&av.raw!==undefined)?av.raw : av; bv=(bv&&bv.raw!==undefined)?bv.raw:bv;
      if(h.num){ av=Number(av)||0; bv=Number(bv)||0; return (av-bv)*sortState.dir; }
      return String(av).localeCompare(String(bv),"zh-Hant")*sortState.dir;
    });
    render(rows);
  }
  render(rows);
  wrap.appendChild(t);
  return wrap;
}
function cell(n,signedFlag){ return {raw:n, html: signedFlag?signed(n):`<span>${fmt(n)}</span>`}; }

/* ---------- 契約月份工具 ---------- */
function monthLabel(m){ if(m==="999999")return "所有契約"; if(m==="666666")return "週合約合計"; return m.slice(0,4)+"/"+m.slice(4)+" 當月"; }
function orderMonths(arr){
  const spec={"999999":0,"666666":2};
  return arr.sort((a,b)=>{ const oa=(a in spec)?spec[a]:1, ob=(b in spec)?spec[b]:1; return oa!==ob?oa-ob:a.localeCompare(b); });
}
function collectMonths(rec){ const s=new Set(); (rec.call||[]).forEach(x=>s.add(x.month)); (rec.put||[]).forEach(x=>s.add(x.month)); return orderMonths([...s]); }
function collectMonthsRows(rows){ const s=new Set(); (rows||[]).forEach(x=>s.add(x.month)); return orderMonths([...s]); }
function monthSelector(box,months,cur,onChange){
  const bar=el("div","optbar"); bar.appendChild(el("span","muted","契約 "));
  const sel=el("select"); months.forEach(m=>{const o=el("option",null,monthLabel(m));o.value=m;if(m===cur)o.selected=true;sel.appendChild(o);});
  sel.onchange=()=>onChange(sel.value); bar.appendChild(sel); box.appendChild(bar);
}

/* ---------- ① 選擇權 (外資/自營) 未平倉;差額金額為重點,附較前一日 ---------- */
function renderOptions(rec, prev){
  const headers=[{label:"買賣權",sort:false},{label:"買方未平倉",num:true},{label:"賣方未平倉",num:true},
    {label:"買賣差額(口)",num:true},{label:"買方契約金額(千元)",num:true},{label:"賣方契約金額(千元)",num:true},{label:"差額金額(千元)",num:true}];
  const mk=(lab,o,po,cls)=>({
    "買賣權":{html:`<span class="pill ${cls}">${lab}</span>`},
    "買方未平倉":cell(o.buy_oi_lots),"賣方未平倉":cell(o.sell_oi_lots),
    "買賣差額(口)":cell(o.diff_oi_lots,true),
    "買方契約金額(千元)":cell(o.buy_oi_amt),"賣方契約金額(千元)":cell(o.sell_oi_amt),
    "差額金額(千元)":netCell(o.diff_oi_amt, po?(o.diff_oi_amt-po.diff_oi_amt):undefined)
  });
  const rows=[];
  if(rec.call)rows.push(mk("買權 CALL",rec.call,prev&&prev.call,"call"));
  if(rec.put)rows.push(mk("賣權 PUT",rec.put,prev&&prev.put,"put"));
  return sortableTable(headers,rows);
}

/* ---------- ② 外資期貨、現貨;多空淨額 + 較前一日 ---------- */
function renderFutSpot(rec, prev){
  const box=el("div");
  if(rec.fut){
    box.appendChild(el("div","muted","臺股期貨 — 外資及陸資 未平倉"));
    const pf=prev&&prev.fut;
    const h=[{label:"項目",sort:false},{label:"多方",num:true},{label:"空方",num:true},{label:"多空淨額",num:true},{label:"較前一日",sort:false,num:true}];
    const rows=[
      {"項目":"未平倉口數","多方":cell(rec.fut.long_oi_lots),"空方":cell(rec.fut.short_oi_lots),
       "多空淨額":netCell(rec.fut.net_oi_lots), "較前一日":{html:arrow(pf?rec.fut.net_oi_lots-pf.net_oi_lots:undefined)}},
      {"項目":"未平倉契約金額(千元)","多方":cell(rec.fut.long_oi_amt),"空方":cell(rec.fut.short_oi_amt),
       "多空淨額":netCell(rec.fut.net_oi_amt), "較前一日":{html:arrow(pf?rec.fut.net_oi_amt-pf.net_oi_amt:undefined)}},
    ];
    box.appendChild(sortableTable(h,rows));
  }
  if(rec.spot){
    const ps=prev&&prev.spot;
    const t=el("div","muted","外資及陸資(不含外資自營商) 現貨買賣 (單位:元)"); t.style.marginTop="12px"; box.appendChild(t);
    const h=[{label:"買進金額",num:true},{label:"賣出金額",num:true},{label:"買賣差額",num:true},{label:"較前一日",sort:false,num:true}];
    const rows=[{"買進金額":cell(rec.spot.buy_amt),"賣出金額":cell(rec.spot.sell_amt),
      "買賣差額":netCell(rec.spot.net_amt),"較前一日":{html:arrow(ps?rec.spot.net_amt-ps.net_amt:undefined)}}];
    const w=sortableTable(h,rows); w.style.marginTop="6px"; box.appendChild(w);
  }
  return box;
}

/* ---------- 大額交易人:原始明細 (可展開) ---------- */
function typeLabel(t){ return t==="1" ? "其中特定法人" : "全部交易人"; }
function largeRows(rows){
  const headers=[{label:"契約",sort:false},{label:"交易人別",sort:false},
    {label:"前五大買方",num:true},{label:"前五大賣方",num:true},{label:"前十大買方",num:true},{label:"前十大賣方",num:true},{label:"全市場未沖銷",num:true}];
  const data=(rows||[]).map(r=>({"契約":monthLabel(r.month),"交易人別":typeLabel(r.type),
    "前五大買方":cell(r.top5_buy),"前五大賣方":cell(r.top5_sell),"前十大買方":cell(r.top10_buy),"前十大賣方":cell(r.top10_sell),"全市場未沖銷":cell(r.market_oi)}));
  return sortableTable(headers,data,{dense:true});
}
function rawDetails(inner){ const d=el("details","rawdet"); d.appendChild(el("summary",null,"展開原始買方/賣方明細")); d.appendChild(inner); return d; }

/* ---------- 由 type0(全部)/type1(特定法人) 推導 自然人大戶 與 法人 ---------- */
function pickRow(arr,m,t){ return (arr||[]).find(x=>x.month===m&&x.type===t) || {top5_buy:0,top5_sell:0,top10_buy:0,top10_sell:0,market_oi:0}; }
function optSide(arr,m){
  const t0=pickRow(arr,m,"0"), t1=pickRow(arr,m,"1");
  const n5b=t0.top5_buy-t1.top5_buy, n5s=t0.top5_sell-t1.top5_sell, n10b=t0.top10_buy-t1.top10_buy, n10s=t0.top10_sell-t1.top10_sell;
  return { market:t0.market_oi, rows:{
    inst5:{buy:t1.top5_buy,sell:t1.top5_sell,net:t1.top5_buy-t1.top5_sell},
    inst10:{buy:t1.top10_buy,sell:t1.top10_sell,net:t1.top10_buy-t1.top10_sell},
    nat5:{buy:n5b,sell:n5s,net:n5b-n5s},
    nat10:{buy:n10b,sell:n10s,net:n10b-n10s},
  }};
}
function optGroups(rec,m){ return {call:optSide(rec.call,m), put:optSide(rec.put,m)}; }
function futSide(rows,m){
  const t0=pickRow(rows,m,"0"), t1=pickRow(rows,m,"1");
  const n5L=t0.top5_buy-t1.top5_buy, n5S=t0.top5_sell-t1.top5_sell, n10L=t0.top10_buy-t1.top10_buy, n10S=t0.top10_sell-t1.top10_sell;
  return { market:t0.market_oi, rows:{
    nat5:{long:n5L,short:n5S,net:n5L-n5S},
    nat10:{long:n10L,short:n10S,net:n10L-n10S},
    inst5:{long:t1.top5_buy,short:t1.top5_sell,net:t1.top5_buy-t1.top5_sell},
    inst10:{long:t1.top10_buy,short:t1.top10_sell,net:t1.top10_buy-t1.top10_sell},
  }};
}

/* ---------- ③ 大額交易人選擇權 (淨部位 + 傾向) ---------- */
function renderLargeOpt(rec, prev){
  const box=el("div");
  const months=collectMonths(rec); let cur=months.includes("999999")?"999999":(months[0]||"999999");
  monthSelector(box,months,cur,v=>{cur=v;draw();});
  box.appendChild(el("div","legend","未平倉<b>淨部位</b>(買−賣,口) · <span class='up'>紅=淨買方</span> · <span class='down'>綠=淨賣方</span> · ()=較前一日 · 傾向 <span class='up'>▲</span>/<span class='down'>▼</span>"));
  const holder=el("div"); box.appendChild(holder);
  function draw(){
    holder.innerHTML="";
    const g=optGroups(rec,cur), gp=prev?optGroups(prev,cur):null;
    const headers=[{label:"交易人別",sort:false},{label:"買權 CALL 淨部位",sort:false,num:true},{label:"賣權 PUT 淨部位",sort:false,num:true},{label:"傾向",sort:false}];
    const order=[["前十特定法人","inst10"]];
    const rows=order.map(([name,k])=>{
      const cN=g.call.rows[k].net, pN=g.put.rows[k].net;
      const dC=gp?cN-gp.call.rows[k].net:undefined, dP=gp?pN-gp.put.rows[k].net:undefined;
      return {"交易人別":name,"買權 CALL 淨部位":netCell(cN,dC),"賣權 PUT 淨部位":netCell(pN,dP),
        "傾向":{html:biasArrow(cN-pN)}};
    });
    holder.appendChild(sortableTable(headers,rows,{dense:true}));
    const inner=el("div");
    inner.appendChild(el("div","muted","臺指買權 CALL")); inner.appendChild(largeRows((rec.call||[]).filter(x=>x.month===cur)));
    const pp=el("div","muted","臺指賣權 PUT"); pp.style.marginTop="8px"; inner.appendChild(pp); inner.appendChild(largeRows((rec.put||[]).filter(x=>x.month===cur)));
    holder.appendChild(rawDetails(inner));
  }
  draw();
  return box;
}

/* ---------- ④ 大額交易人期貨 (自然人大戶 / 法人;多單/空單/淨部位) ---------- */
function renderLargeFut(rec, prev){
  if(rec.pending || !(rec.rows&&rec.rows.length)) return el("div","warn", rec.note||"資料未更新");
  const box=el("div");
  const months=collectMonthsRows(rec.rows); let cur=months.includes("999999")?"999999":(months[0]||"999999");
  monthSelector(box,months,cur,v=>{cur=v;draw();});
  box.appendChild(el("div","legend","多單=買方部位 · 空單=賣方部位 · 未平倉<b>淨部位</b>=多−空(<span class='up'>紅淨多</span>/<span class='down'>綠淨空</span>) · ()=較前一日"));
  const holder=el("div"); box.appendChild(holder);
  function draw(){
    holder.innerHTML="";
    const g=futSide(rec.rows,cur), gp=(prev&&prev.rows&&prev.rows.length)?futSide(prev.rows,cur):null;
    const headers=[{label:"交易人別",sort:false},{label:"多單",sort:false,num:true},{label:"空單",sort:false,num:true},{label:"未平倉淨部位",sort:false,num:true}];
    const order=[["前十特定法人","inst10"]];
    const rows=order.map(([name,k])=>{
      const o=g.rows[k], p=gp?gp.rows[k]:null;
      return {"交易人別":name,
        "多單":cntCell(o.long, p?o.long-p.long:undefined),
        "空單":cntCell(o.short, p?o.short-p.short:undefined),
        "未平倉淨部位":netCell(o.net, p?o.net-p.net:undefined)};
    });
    holder.appendChild(sortableTable(headers,rows,{dense:true}));
    holder.appendChild(el("div","muted2","全市場未沖銷部位:"+fmt(g.market)+" 口"));
    const inner=el("div"); inner.appendChild(largeRows((rec.rows||[]).filter(x=>x.month===cur)));
    holder.appendChild(rawDetails(inner));
  }
  draw();
  return box;
}
