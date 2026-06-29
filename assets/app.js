/* 每日盤後資料 — 共用前端邏輯 (純前端, 讀取 ./data/*.json) */
const DATA = "data/";
const CATS = [
  {id:"options_foreign", title:"外資選擇權",       file:"options_foreign.json"},
  {id:"options_dealer",  title:"自營選擇權",       file:"options_dealer.json"},
  {id:"foreign_fut_spot",title:"外資期貨、現貨",   file:"foreign_fut_spot.json"},
  {id:"large_opt",       title:"大額交易人選擇權", file:"large_opt.json"},
  {id:"large_fut_txf",   title:"大額交易人期貨",   file:"large_fut_txf.json"},
  {id:"stocks",          title:"大額交易人股票期貨",file:null},
];
const $ = (s,r=document)=>r.querySelector(s);
const el = (t,c,h)=>{const e=document.createElement(t); if(c)e.className=c; if(h!=null)e.innerHTML=h; return e;};
async function getJSON(f){const r=await fetch(DATA+f,{cache:"no-store"}); if(!r.ok)throw new Error(f); return r.json();}
const fmt = n => (n===null||n===undefined||n==="")?"–":Number(n).toLocaleString("en-US");
function signed(n){ if(n===null||n===undefined)return "–"; const c=n>0?"up":(n<0?"down":""); const s=n>0?"+":""; return `<span class="${c}">${s}${fmt(n)}</span>`; }
function navActive(id){document.querySelectorAll("nav.main a").forEach(a=>{if(a.dataset.k===id)a.classList.add("active");});}

/* ---------- 排序表格 ---------- */
function sortableTable(headers, rows, opts={}){
  // headers: [{k:'label', sort:true/false, num:true}] ; rows: array of objects keyed by header label OR html
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

/* ---------- 各分類渲染 ---------- */
// 選擇權 (外資/自營) 未平倉
function renderOptions(rec){
  const headers=[{label:"買賣權",sort:false},{label:"買方未平倉",num:true},{label:"賣方未平倉",num:true},
    {label:"買賣差額",num:true},{label:"買方契約金額(千元)",num:true},{label:"賣方契約金額(千元)",num:true},{label:"差額金額(千元)",num:true}];
  const mk=(lab,o,cls)=>({"買賣權":{html:`<span class="pill ${cls}">${lab}</span>`}, "買方未平倉":cell(o.buy_oi_lots),
    "賣方未平倉":cell(o.sell_oi_lots),"買賣差額":cell(o.diff_oi_lots,true),
    "買方契約金額(千元)":cell(o.buy_oi_amt),"賣方契約金額(千元)":cell(o.sell_oi_amt),"差額金額(千元)":cell(o.diff_oi_amt,true)});
  const rows=[]; if(rec.call)rows.push(mk("買權 CALL",rec.call,"call")); if(rec.put)rows.push(mk("賣權 PUT",rec.put,"put"));
  return sortableTable(headers,rows);
}
// 外資期貨+現貨
function renderFutSpot(rec){
  const box=el("div");
  if(rec.fut){
    box.appendChild(el("div","muted","臺股期貨 — 外資及陸資 未平倉"));
    const h=[{label:"項目",sort:false},{label:"多方",num:true},{label:"空方",num:true},{label:"多空淨額",num:true}];
    const rows=[
      {"項目":"未平倉口數","多方":cell(rec.fut.long_oi_lots),"空方":cell(rec.fut.short_oi_lots),"多空淨額":cell(rec.fut.net_oi_lots,true)},
      {"項目":"未平倉契約金額(千元)","多方":cell(rec.fut.long_oi_amt),"空方":cell(rec.fut.short_oi_amt),"多空淨額":cell(rec.fut.net_oi_amt,true)},
    ];
    box.appendChild(sortableTable(h,rows));
  }
  if(rec.spot){
    box.appendChild(el("div","muted","外資及陸資(不含外資自營商) 現貨買賣 (單位:元)"));
    box.style.marginTop="0";
    const h=[{label:"買進金額",num:true},{label:"賣出金額",num:true},{label:"買賣差額",num:true}];
    const rows=[{"買進金額":cell(rec.spot.buy_amt),"賣出金額":cell(rec.spot.sell_amt),"買賣差額":cell(rec.spot.net_amt,true)}];
    const w=sortableTable(h,rows); w.style.marginTop="6px"; box.appendChild(w);
  }
  return box;
}
// 大額交易人 (選擇權: call/put ; 期貨/個股: rows)
function monthLabel(m){ if(m==="999999")return "所有契約"; if(m==="666666")return "週合約合計"; return m.slice(0,4)+"/"+m.slice(4)+" 當月"; }
function typeLabel(t){ return t==="1" ? "其中特定法人" : "全部交易人"; }
function largeRows(rows){
  const headers=[{label:"契約",sort:false},{label:"交易人別",sort:false},
    {label:"前五大買方",num:true},{label:"前五大賣方",num:true},{label:"前十大買方",num:true},{label:"前十大賣方",num:true},{label:"全市場未沖銷",num:true}];
  const data=rows.map(r=>({"契約":monthLabel(r.month),"交易人別":typeLabel(r.type),
    "前五大買方":cell(r.top5_buy),"前五大賣方":cell(r.top5_sell),"前十大買方":cell(r.top10_buy),"前十大賣方":cell(r.top10_sell),"全市場未沖銷":cell(r.market_oi)}));
  return sortableTable(headers,data,{dense:true});
}
function renderLargeOpt(rec){
  const box=el("div");
  box.appendChild(el("div","muted","臺指買權 CALL"));
  box.appendChild(largeRows(rec.call||[]));
  const p=el("div","muted","臺指賣權 PUT"); p.style.marginTop="10px"; box.appendChild(p);
  box.appendChild(largeRows(rec.put||[]));
  return box;
}
function renderLargeFut(rec){
  if(rec.pending || !(rec.rows&&rec.rows.length)){
    return el("div","warn", rec.note || "資料未更新");
  }
  return largeRows(rec.rows);
}
