'use strict';
const $ = id => document.getElementById(id);
const state = {meta:null,stats:null,devices:new Set(),view:'overview',dimension:'categories',timeline:null,sessionLimit:200,request:0,timelineRequest:0,deviceTimeline:null,deviceTimelineRequest:0};
const palette=['#5473e8','#19a996','#e9ab55','#a483d0','#ed8495','#6eb8d1','#9eaabe'];
const esc = s => String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const hh = n => String(n).padStart(2,'0');
const dateKey = d => `${d.getFullYear()}-${hh(d.getMonth()+1)}-${hh(d.getDate())}`;
const dtInput = (day,hour) => `${day}T${hh(hour)}:00:00+08:00`;
const fmtTime = ts => ts == null ? '—' : new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(ts*1000));
const fmtStamp = ts => ts ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(ts*1000)) : '暂无记录';
const fmtDuration = s => {s=Math.round(s||0);if(s<60)return `${s} 秒`;const m=Math.floor(s/60);return m>=60?`${Math.floor(m/60)} 小时 ${m%60} 分`:`${m} 分钟`;};
const compact = s => s>=3600 ? `${(s/3600).toFixed(1)}h` : s>=60?`${Math.round(s/60)}m`:`${Math.round(s)}s`;
const metric = s => {let m=Math.round(s/60);return m>=60?`${Math.floor(m/60)}<small>小时</small>${m%60}<small>分</small>`: m>0?`${m}<small>分钟</small>`:`${Math.round(s)}<small>秒</small>`;};
function today(){let d=new Date(new Date().toLocaleString('en-US',{timeZone:'Asia/Shanghai'}));d.setHours(d.getHours()-state.meta.settings.boundary);return dateKey(d);}
function shiftDate(day,n){const d=new Date(day+'T12:00:00+08:00');d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10);}
function dayClock(ts,day){if(ts==null)return '—';const key=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(ts*1000));return `${fmtTime(ts)}${key>day?' <span class="next-day">次日</span>':''}`;}
function cat(id){return state.meta.categories.find(x=>x.id===id)||{id:'other',name:'未分类',color:'#bcc4cf'};}
function appColor(bundle){let hash=0;for(const c of bundle)hash=(hash*31+c.charCodeAt(0))>>>0;return palette[hash%palette.length];}
function toast(msg){$('toast').textContent=msg;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,3300);}
function error(e){$('error').textContent=e.message||String(e);$('error').hidden=false;}
const run = fn => async (...args) => {try{await fn(...args);}catch(e){error(e);}};
async function api(path,data){const r=await fetch(path,data===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(r.status===401){location.href='/login'+location.search;throw new Error('访问已锁定');}const body=await r.json();if(!r.ok)throw new Error(body.error||'读取失败');return body;}
function period(){const start=$('start-date').value,end=$('end-date').value;if(!start||!end)throw new Error('请选择开始和结束日期');let a,b;if($('exact').checked){a=`${start}T${$('start-time').value}:00+08:00`;b=`${end}T${$('end-time').value}:00+08:00`;}else{a=dtInput(start,state.meta.settings.boundary);b=dtInput(shiftDate(end,1),state.meta.settings.boundary);}if(new Date(b)<=new Date(a))throw new Error('结束时间必须晚于开始时间');if(!state.devices.size&&state.meta.devices.length)throw new Error('请至少选择一个设备');return {start:a,end:b,devices:[...state.devices].join(','),group:$('group').value};}
function query(p){return new URLSearchParams(p).toString();}
function preset(n){const end=today();$('end-date').value=end;$('start-date').value=shiftDate(end,1-n);$('exact').checked=false;$('exact-fields').hidden=true;document.querySelectorAll('[data-days]').forEach(b=>b.classList.toggle('selected',Number(b.dataset.days)===n));}
// Device preferences are browser-local; URL state takes precedence for shared links.
const DEVICE_STORAGE_KEY = 'screentime.devices.v1';
let routeRestoring = 0;
let routeRequest = 0;
const routeViews = new Set(['overview','timeline','device-timeline','apps','sources','settings']);
function validDate(value) {
 if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false;
 const d = new Date(value + 'T12:00:00Z');
 return Number.isFinite(d.getTime()) && d.toISOString().slice(0,10) === value;
}
function validTime(value) { return /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value || ''); }
function rememberedDevices() {
 try {
  const value = JSON.parse(localStorage.getItem(DEVICE_STORAGE_KEY));
  return Array.isArray(value) ? value.filter(x => typeof x === 'string') : [];
 } catch (_) { return []; }
}
function rememberDevices() {
 try { localStorage.setItem(DEVICE_STORAGE_KEY, JSON.stringify([...state.devices].sort())); }
 catch (_) { /* Private browsing or storage restrictions must not block navigation. */ }
}
function currentRoute() {
 const p = new URLSearchParams();
 p.set('view', state.view);
 if(state.view==='device-timeline'){p.set('fromAt',$('device-start').value);p.set('toAt',$('device-end').value);return '/?'+p.toString();}
 p.set('devices', [...state.devices].sort().join(','));
 p.set('start', $('start-date').value);
 p.set('end', $('end-date').value);
 if ($('exact').checked) {
  p.set('exact','1');p.set('from',$('start-time').value);p.set('to',$('end-time').value);
 }
 if (state.dimension !== 'categories') p.set('dimension', state.dimension);
 if ($('group').value !== 'day') p.set('group', $('group').value);
 if ($('trend-series').value && $('trend-series').value !== 'top') p.set('series',$('trend-series').value);
 if ($('show-empty').checked) p.set('empty','1');
 p.set('day', $('timeline-date').value || today());
 if ($('session-search').value) p.set('q',$('session-search').value);
 if ($('app-search').value) p.set('appq',$('app-search').value);
 return '/?' + p.toString();
}
function updateTitle() {
 const names = state.meta.devices.filter(d => state.devices.has(d.device_id)).map(d => d.label);
 const device = names.length === 1 ? names[0] : names.length + ' 台设备';
 const start = $('start-date').value, end = $('end-date').value;
 const range = $('exact').checked ? start + ' ' + $('start-time').value + ' ~ ' + end + ' ' + $('end-time').value : (start === end ? start : start + ' ~ ' + end);
 const labels = {overview:'时间概览',timeline:'每日时间线','device-timeline':'设备时间轴',apps:'应用与分类',sources:'同步与接入',settings:'偏好设置'};
 let context = '';
 if (state.view === 'overview') context = range + ' · ' + (state.dimension === 'apps' ? '按应用' : '按分类') + ' · ' + device;
 else if (state.view === 'device-timeline') context = $('device-start').value.replace('T',' ')+' ~ '+$('device-end').value.replace('T',' ');
 else if (state.view === 'timeline') context = $('timeline-date').value + ' · ' + device;
 document.title = labels[state.view] + (context ? ' · ' + context : '') + ' | Screen Time';
}
function syncLocation(mode = 'push') {
 if (routeRestoring || !state.meta) return;
 updateTitle();
 const url = currentRoute();
 if (location.pathname + location.search + location.hash !== url) history[mode === 'replace' ? 'replaceState' : 'pushState'](null,'',url);
}
async function restoreLocation() {
 const request = ++routeRequest;
 routeRestoring++;
 try {
  const p = new URLSearchParams(location.search);
  const available = new Set(state.meta.devices.map(d => d.device_id));
  const requested = p.has('devices') ? p.get('devices').split(',') : rememberedDevices();
  const ids = requested.filter(id => available.has(id));
  state.devices = new Set(ids.length ? ids : [state.meta.default_device].filter(Boolean));
  preset(7);
  if (validDate(p.get('start')) && validDate(p.get('end'))) {
   $('start-date').value = p.get('start');$('end-date').value = p.get('end');
   document.querySelectorAll('[data-days]').forEach(b => b.classList.remove('selected'));
  }
  $('exact').checked = p.get('exact') === '1' && validTime(p.get('from')) && validTime(p.get('to'));
  $('start-time').value = validTime(p.get('from')) ? p.get('from') : '04:00';
  $('end-time').value = validTime(p.get('to')) ? p.get('to') : '04:00';
  $('exact-fields').hidden = !$('exact').checked;
  // Ignore malformed or oversized shared ranges instead of starting with a broken page.
  try { const r = period();if((new Date(r.end)-new Date(r.start)) > 366*86400000) preset(7); }
  catch (_) { preset(7); }
  document.querySelectorAll('[data-days]').forEach(b => b.classList.toggle('selected', !$('exact').checked && $('end-date').value === today() && $('start-date').value === shiftDate(today(),1-Number(b.dataset.days))));
  state.dimension = p.get('dimension') === 'apps' ? 'apps' : 'categories';
  document.querySelectorAll('[data-dim]').forEach(b => b.classList.toggle('active',b.dataset.dim === state.dimension));
  $('trend-series').value = 'top';
  $('group').value = ['day','week','month'].includes(p.get('group')) ? p.get('group') : 'day';
  $('timeline-date').value = validDate(p.get('day')) ? p.get('day') : today();
  $('show-empty').checked = p.get('empty') === '1';
  $('session-search').value = (p.get('q') || '').slice(0,300);
  $('app-search').value = (p.get('appq') || '').slice(0,300);
  const validAt=v=>v&&validDate(v.slice(0,10))&&v[10]==='T'&&validTime(v.slice(11))&&v.length===16;
  $('device-start').value=validAt(p.get('fromAt'))?p.get('fromAt'):today()+'T'+hh(state.meta.settings.boundary)+':00';
  $('device-end').value=validAt(p.get('toAt'))?p.get('toAt'):shiftDate(today(),1)+'T'+hh(state.meta.settings.boundary)+':00';
  renderMeta();
  const view = routeViews.has(p.get('view')) ? p.get('view') : 'overview';
  await showView(view);
  await loadStats();
  if (request !== routeRequest) return;
  const series = p.get('series');
  if (series && [...$('trend-series').options].some(o => o.value === series)) {
   $('trend-series').value = series;renderTrend();
  }
 } finally {
  routeRestoring--;
  if (!routeRestoring) syncLocation('replace');
 }
}
window.addEventListener('popstate',run(restoreLocation));

function renderDevices(){const visible=state.meta.devices.filter(d=>d.sessions||state.devices.has(d.device_id)||$('show-empty').checked);$('devices').innerHTML=visible.map(d=>`<button class="device-button ${state.devices.has(d.device_id)?'selected':''}" data-device="${esc(d.device_id)}" aria-pressed="${state.devices.has(d.device_id)}" title="${esc(d.device_id+' · '+d.source_label+' · '+d.sessions+' 条记录 · 最新数据 '+fmtStamp(d.latest))}">${d.platform==='ios'||d.platform==='android'?'▯':d.platform==='macos'?'▰':'◇'} ${esc(d.label)}<small>${esc(d.source_label)}</small></button>`).join('');}
function renderMeta(){$('onboarding').hidden=state.meta.devices.some(d=>d.sessions>0);renderDevices();$('source-status').innerHTML=`<span class="live-dot"></span>最近归档 ${esc(fmtStamp(state.meta.last_run))} · ${state.meta.apps.length} 个应用标识`;
 renderLatestDeviceStatus();
 const s=state.meta.settings;$('boundary-note').textContent=`生活日 ${hh(s.boundary)}:00 分界 · 特殊时段 ${hh(s.special_start)}:00–${hh(s.special_end)}:00 · 北京时间`;
 $('metric-special-note').textContent=`${hh(s.special_start)}:00 – ${hh(s.special_end)}:00 · App 累计时长`;
 if(state.meta.android_sync?.ok===false)error(new Error('Android 最近同步失败，当前显示上次成功同步的数据'));
 if(state.meta.errors.length)error(new Error('最近归档存在错误：'+state.meta.errors.join('；')));
 if(state.meta.sync_error)error(new Error(state.meta.sync_error));
 renderApps();renderCategories();renderSettings();
}
function renderLatestDeviceStatus(){const all=state.view==='device-timeline';const selected=state.meta.devices.filter(d=>all?d.sessions>0:state.devices.has(d.device_id));const latest=Math.max(0,...selected.map(d=>d.latest||0));$('latest-data').textContent=(all?'全部设备最新记录：':'所选设备最新记录：')+fmtStamp(latest);}
async function loadMeta(){state.meta=await api('/api/meta');if(!state.devices.size&&state.meta.default_device)state.devices.add(state.meta.default_device);renderMeta();}
async function loadStats(){const id=++state.request;const p=period();$('loading').hidden=false;$('error').hidden=!(state.meta.errors.length||state.meta.sync_error);try{const result=await api('/api/stats?'+query(p));if(id!==state.request)return;state.stats=result;renderOverview();syncLocation();}finally{if(id===state.request)$('loading').hidden=true;}}
function entries(){return state.stats[state.dimension].map(d=>({...d,color:state.dimension==='categories'?d.color:appColor(d.bundle)}));}
function renderOverview(){const s=state.stats;if(!s)return;$('metric-total').innerHTML=metric(s.total);$('metric-active').innerHTML=metric(s.active);$('metric-average').innerHTML=metric(s.days.length?s.total/s.days.length:0);$('metric-special').innerHTML=metric(s.days.reduce((a,d)=>a+d.special_seconds,0));$('metric-period').textContent=`${$('start-date').value} → ${$('end-date').value}`;$('metric-days').textContent=`按范围覆盖的 ${s.days.length} 个生活日计算（含零记录日）`;
 $('ranking-description').textContent=state.dimension==='categories'?'按分类查看时间分布':'跨所选设备合计相同应用标识';renderDistribution();renderTrend();renderDaily();$('footer-status').textContent=`${s.sessions.toLocaleString()} 条相交会话 · 原始记录未修改`;}
function renderDistribution(){let all=entries();if(!all.length){$('distribution').innerHTML='<div class="empty">这个时间范围还没有记录。<br>可尝试更早日期或其他设备。</div>';$('ranking').innerHTML='<div class="empty">暂无用时排行</div>';return;}let values=all.slice(0,6);if(all.length>6)values.push({name:'其余应用',seconds:all.slice(6).reduce((a,d)=>a+d.seconds,0),color:'#d6dde8'});let offset=0;const circles=values.map(d=>{const percentage=d.seconds/state.stats.total*100;const circle=`<circle cx="100" cy="100" r="80" fill="none" stroke="${esc(d.color)}" stroke-width="22" pathLength="100" stroke-dasharray="${percentage} ${100-percentage}" stroke-dashoffset="${-offset}"><title>${esc(d.name)} · ${esc(fmtDuration(d.seconds))} · ${percentage.toFixed(1)}%</title></circle>`;offset+=percentage;return circle;}).join('');
 $('distribution').innerHTML=`<div class="donut"><svg viewBox="0 0 200 200" role="img" aria-label="${state.dimension==='categories'?'分类':'应用'}用时占比"><circle cx="100" cy="100" r="80" fill="none" stroke="#f2f5f9" stroke-width="22"/>${circles}</svg><div class="donut-center">${(state.stats.total/3600).toFixed(1)}h<small>累计使用</small></div></div><div class="distribution-legend">${values.map(d=>`<div class="legend-item" title="${esc(d.name)}"><span class="swatch" style="background:${esc(d.color)}"></span><span class="legend-name">${esc(d.name)}</span><span class="legend-percent">${(d.seconds/state.stats.total*100).toFixed(1)}%</span></div>`).join('')}</div>`;
 $('ranking').innerHTML=all.map((d,i)=>`<div class="rank-row"><div class="rank-info"><span class="rank-label"><span class="rank-number">${hh(i+1)}</span><span class="rank-name" title="${esc(d.bundle||d.id)}">${esc(d.name)}</span>${state.dimension==='apps' && (d.category==='other'||!state.meta.categories.some(c=>c.id===d.category))?'<span class="uncategorized-badge">未分类</span>':''}</span><span class="rank-time">${esc(fmtDuration(d.seconds))} · ${(d.share*100).toFixed(1)}%</span></div><div class="rank-track"><div class="rank-fill" style="width:${d.seconds/all[0].seconds*100}%;background:${esc(d.color)}"></div></div></div>`).join('');
}
function renderTrend(){const buckets=state.stats.buckets;const previous=$('trend-series').value;const all=entries();$('trend-series').innerHTML='<option value="top">前六项 + 其余</option>'+all.map(x=>`<option value="${esc(x.bundle||x.id)}">${esc(x.name)}</option>`).join('');if(all.some(x=>(x.bundle||x.id)===previous))$('trend-series').value=previous;const selected=$('trend-series').value;let series=(selected==='top'?all.slice(0,6):all.filter(x=>(x.bundle||x.id)===selected)).map(x=>({...x,key:x.bundle||x.id}));if(selected==='top'&&all.length>6)series.push({key:'__rest',name:'其余',color:'#d6dde8'});$('trend-legend').innerHTML=series.map(s=>`<span><i class="swatch" style="background:${esc(s.color)}"></i>${esc(s.name)}</span>`).join('');if(!state.stats.total){$('trend').innerHTML='<div class="empty">暂无趋势数据</div>';return;}
 const width=Math.max(660,buckets.length*40),height=235,top=18,left=43,bottom=34,plot=height-top-bottom;const rawMax=Math.max(...buckets.map(b=>(selected==='top'?b.seconds:(b[state.dimension][selected]||0))/3600),1);const step=rawMax>20?5:rawMax>8?2:rawMax>3?1:.5;const max=Math.ceil(rawMax/step)*step;
 let svg=`<svg viewBox="0 0 ${width} ${height}" style="min-width:${width}px" role="img" aria-label="用时变化堆叠柱状图">`;
 for(let i=0;i<=4;i++){const value=max*i/4,y=height-bottom-value/max*plot;svg+=`<line x1="${left}" x2="${width-10}" y1="${y}" y2="${y}" stroke="#edf1f6"/><text class="chart-text" x="${left-10}" y="${y+3}" text-anchor="end">${Number(value.toFixed(1))}h</text>`;}
 const stride=(width-left-14)/buckets.length,bar=Math.min(34,stride*.55);buckets.forEach((b,i)=>{let cumulative=0;const x=left+stride*(i+.5)-bar/2;series.forEach(s=>{const source=b[state.dimension];const value=s.key==='__rest'?Math.max(0,b.seconds-series.filter(x=>x.key!=='__rest').reduce((a,x)=>a+(source[x.key]||0),0)):(source[s.key]||0);const h=value/3600/max*plot;const y=height-bottom-cumulative/3600/max*plot-h;svg+=`<rect x="${x}" y="${y}" width="${bar}" height="${h}" rx="2" fill="${esc(s.color)}"><title>${esc(b.date+' · '+s.name+' · '+fmtDuration(value))}</title></rect>`;cumulative+=value;});const label=$('group').value==='month'?b.date:b.date.slice(5).replace('-','/');if(buckets.length<=18||i%Math.ceil(buckets.length/16)===0)svg+=`<text class="chart-text" x="${x+bar/2}" y="${height-11}" text-anchor="middle">${label}</text>`;});$('trend').innerHTML=svg+'</svg>';}
function renderDaily(){$('daily').innerHTML=[...state.stats.days].reverse().map(d=>`<tr><td>${esc(d.date)}<span class="detail-bundle">${new Intl.DateTimeFormat('zh-CN',{weekday:'long',timeZone:'Asia/Shanghai'}).format(new Date(d.date+'T12:00:00+08:00'))}</span></td><td>${dayClock(d.first,d.date)}</td><td>${dayClock(d.last,d.date)}</td><td>${d.seconds?fmtDuration(d.seconds):'—'}</td><td>${d.special_seconds?`<span class="special-badge">${fmtDuration(d.special_seconds)}</span>`:'—'}</td><td><button class="table-link" data-day="${d.date}">查看时间线 ↗</button></td></tr>`).join('');}
const viewInfo={overview:['把时间，看得更清楚','从应用到习惯，回看你的每一天。'],'device-timeline':['让设备，在同一条时间刻度上相遇','每台设备一行，看清同时发生的使用记录。'],timeline:['每天的时间，都有迹可循','哪一刻打开，哪一刻离开，让记录自己说话。'],sources:['让每台设备，按自己的节奏同步','局域网或 frpc 接入，公共策略或独立配置。'],apps:['给记录，添上你的理解','熟悉的名称、清楚的分类，历史数据也随之更新。'],settings:['让一天，按你的节奏开始','定义生活日的边界，保留原始记录的完整。']};
async function showView(view){state.view=view;renderLatestDeviceStatus();$('filters').classList.toggle('timeline-mode',view==='timeline');document.querySelectorAll('.view').forEach(el=>el.hidden=el.id!=='view-'+view);document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));$('page-title').textContent=viewInfo[view][0]+'。';$('page-subtitle').textContent=viewInfo[view][1];$('filters').hidden=['apps','settings','device-timeline','sources'].includes(view);if(view==='timeline')await loadTimeline();if(view==='device-timeline')await loadDeviceTimeline();if(view==='sources')await loadSources();syncLocation();}
async function loadTimeline(){if(!state.devices.size)throw new Error('请至少选择一个设备');const id=++state.timelineRequest;const day=$('timeline-date').value||today();$('timeline-date').value=day;const b=state.meta.settings.boundary;const p={start:dtInput(day,b),end:dtInput(shiftDate(day,1),b),devices:[...state.devices].join(',')};const data=await api('/api/timeline?'+query(p));if(id!==state.timelineRequest)return;state.timeline=data;state.sessionLimit=200;renderTimeline();syncLocation();}
function renderTimeline(){const t=state.timeline;if(!t)return;const items=filteredSessions();const intervals={};for(const item of t.items){(intervals[item.device]??=[]).push([item.start,item.end]);}const union=rows=>{let total=0,range=null;for(const [a,b]of rows.sort((a,b)=>a[0]-b[0])){if(!range)range=[a,b];else if(a<=range[1])range[1]=Math.max(range[1],b);else{total+=range[1]-range[0];range=[a,b];}}return total+(range?range[1]-range[0]:0);};const sum=t.items.reduce((a,i)=>a+i.seconds,0),active=Object.values(intervals).reduce((a,r)=>a+union(r),0);$('timeline-summary').innerHTML=`<span>App 累计<strong>${esc(fmtDuration(sum))}</strong></span><span>设备内去重<strong>${esc(fmtDuration(active))}</strong></span><span>会话<strong>${t.items.length}</strong></span>`;
 const groups=new Map();for(const item of items){const key=item.device+'|'+item.bundle;if(!groups.has(key))groups.set(key,{...item,items:[]});groups.get(key).items.push(item);}
 let axis='<div class="timeline-axis">';for(let i=0;i<=24;i+=3)axis+=`<span style="left:${i/24*100}%">${hh((state.meta.settings.boundary+i)%24)}:00</span>`;axis+='</div>';
 $('timeline-chart').innerHTML=items.length?axis+[...groups.values()].map(g=>{const device=state.meta.devices.find(d=>d.device_id===g.device);return `<div class="timeline-lane"><span class="lane-label" title="${esc(g.name+' · '+device?.label)}">${esc(g.name)}</span><div class="lane-track">${g.items.map(i=>`<span class="session-block" style="left:${(i.start-t.start)/(t.end-t.start)*100}%;width:${i.seconds/(t.end-t.start)*100}%;background:${cat(i.category).color}" title="${esc(i.name+' · '+device?.label+' · '+fmtTime(i.start)+'–'+fmtTime(i.end)+' · '+fmtDuration(i.seconds))}"></span>`).join('')}</div></div>`;}).join(''):'<div class="empty">这一天没有符合筛选的会话记录。</div>';
 renderSessionRows();}
function filteredSessions(){const s=$('session-search').value.toLowerCase();return (state.timeline?.items||[]).filter(i=>(i.name+' '+i.bundle).toLowerCase().includes(s));}
function renderSessionRows(){const items=filteredSessions(),day=$('timeline-date').value;$('session-count').textContent=`${items.length} 条记录 · 已显示 ${Math.min(state.sessionLimit,items.length)} 条`;$('sessions').innerHTML=items.slice(0,state.sessionLimit).map(i=>{const device=state.meta.devices.find(d=>d.device_id===i.device);return `<tr><td>${dayClock(i.start,day)}</td><td>${dayClock(i.end,day)}</td><td><div class="cell-app"><i class="swatch" style="background:${cat(i.category).color}"></i>${esc(i.name)}</div><span class="detail-bundle">${esc(i.bundle)}</span></td><td class="timeline-device" title="${esc(i.device)}">${esc(device?.label)}<span class="detail-bundle">${esc(device?.source_label)}</span></td><td>${fmtDuration(i.seconds)}</td><td>${i.special?'<span class="special-badge">深夜时段</span>':''}${i.start!==i.original_start||i.end!==i.original_end?'<span class="detail-bundle">跨边界已裁切</span>':''}</td></tr>`;}).join('')||'<tr><td colspan="6" class="empty">暂无会话记录</td></tr>';$('more-sessions').hidden=items.length<=state.sessionLimit;}
function renderCategories(){$('categories').innerHTML=state.meta.categories.map(c=>`<button class="category-tag" data-category="${esc(c.id)}" title="点击修改名称和颜色"><span class="swatch" style="background:${esc(c.color)}"></span>${esc(c.name)} <span class="muted">✎</span></button>`).join('');}
function renderApps(){const q=$('app-search').value.toLowerCase();const apps=state.meta.apps.filter(a=>(a.name+' '+a.bundle).toLowerCase().includes(q));$('app-list').innerHTML=apps.map(a=>`<tr data-bundle="${esc(a.bundle)}"><td class="bundle-id">${esc(a.bundle)}</td><td><input class="app-name" value="${esc(a.name)}" maxlength="100" aria-label="${esc(a.name)}的显示名称"></td><td><select class="app-category" aria-label="${esc(a.name)}的分类">${state.meta.categories.map(c=>`<option value="${esc(c.id)}" ${a.category===c.id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></td><td><button class="table-link save-app">保存</button></td></tr>`).join('')||'<tr><td colspan="4" class="empty">没有找到这个应用</td></tr>';}
function renderSettings(){const s=state.meta.settings;for(const [id,key] of [['setting-boundary','boundary'],['setting-special-start','special_start'],['setting-special-end','special_end']]){$(id).innerHTML=Array.from({length:13},(_,h)=>`<option value="${h}" ${s[key]===h?'selected':''}>${hh(h)}:00</option>`).join('');}}
function deviceTimeLabel(ts) {
 return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(ts*1000));
}
async function loadDeviceTimeline() {
 const start=$('device-start').value,end=$('device-end').value;
 const a=new Date(start+':00+08:00').getTime(), b=new Date(end+':00+08:00').getTime();
 if(!Number.isFinite(a+b)||b<=a||b-a>366*86400000)throw new Error('请选择有效的开始、结束日期时间，最多 366 天');
 const id=++state.deviceTimelineRequest;
 const button=$('device-time-form').querySelector('button');button.disabled=true;
 $('device-time-status').textContent='正在读取所有设备的使用区间…';
 try {
  const data=await api('/api/device-timeline?'+query({start:start+':00+08:00',end:end+':00+08:00'}));
  if(id!==state.deviceTimelineRequest)return;
  state.deviceTimeline=data;renderDeviceTimeline();syncLocation();
 } catch(e) {if(id===state.deviceTimelineRequest)$('device-time-status').textContent='读取失败，已保留上次成功显示的时间轴。';throw e;} finally {if(id===state.deviceTimelineRequest)button.disabled=false;}
}
function showDeviceSession(index) {
 const item=state.deviceTimeline?.items[index];if(!item)return;
 const device=state.meta.devices.find(d=>d.device_id===item.device);
 $('device-time-detail').innerHTML=`<strong>${esc(device?.label||item.device)} · ${esc(item.name)}</strong><span>${esc(deviceTimeLabel(item.start))} → ${esc(deviceTimeLabel(item.end))} · ${esc(fmtDuration(item.seconds))}</span><span class="muted">${esc(cat(item.category).name)} · ${esc(item.bundle)}${item.start!==item.original_start||item.end!==item.original_end?' · 已按筛选边界裁切':''}</span>`;
}
function renderDeviceTimeline() {
 const data=state.deviceTimeline;if(!data)return;
 const devices=state.meta.devices.filter(d=>d.sessions>0);
 const used=new Set(data.items.map(i=>i.category));
 $('device-time-legend').innerHTML=state.meta.categories.filter(c=>used.has(c.id)).map(c=>`<span><i class="swatch" style="background:${esc(c.color)}"></i>${esc(c.name)}</span>`).join('');
 $('device-time-status').textContent=`${devices.length} 台设备 · ${data.items.length.toLocaleString()} 条会话 · ${deviceTimeLabel(data.start)} 至 ${deviceTimeLabel(data.end)}`;
 $('device-time-detail').textContent='点击任意色块查看这段记录。';
 const available=$('device-time-chart').clientWidth-180;
 const width=Math.max(700,available,Math.min(8000,(data.end-data.start)/3600*9));
 let axis='<div class="device-time-axis" style="width:'+width+'px">';
 for(let i=0;i<=8;i++){const ts=data.start+(data.end-data.start)*i/8;axis+=`<span style="left:${i/8*100}%">${esc(deviceTimeLabel(ts).replace(/:\d{2}$/,''))}</span>`;}
 axis+='</div>';
 const lanes=devices.map(device=>{
  const items=data.items.map((item,index)=>({...item,index})).filter(i=>i.device===device.device_id);
  const seconds=items.reduce((total,i)=>total+i.seconds,0);
  const blocks=items.map(i=>{
   const x=(i.start-data.start)/(data.end-data.start)*width,w=(i.end-i.start)/(data.end-data.start)*width;
   const label=w>80?`<text x="${x+5}" y="30" font-size="10" fill="#fff" pointer-events="none" textLength="${Math.min(w-10,i.name.length*10)}" lengthAdjust="spacingAndGlyphs">${esc(i.name)}</text>`:'';
   return `<g data-session="${i.index}" tabindex="0" role="button" aria-label="${esc(i.name+' '+deviceTimeLabel(i.start)+' 至 '+deviceTimeLabel(i.end))}"><title>${esc(i.name+' · '+deviceTimeLabel(i.start)+' → '+deviceTimeLabel(i.end)+' · '+fmtDuration(i.seconds))}</title><rect x="${x}" y="8" width="${Math.max(.8,w)}" height="36" rx="2" fill="${esc(cat(i.category).color)}"/>${label}</g>`;
  }).join('');
  return `<div class="device-time-row"><div class="device-time-label"><strong>${esc(device.label)}</strong><span>${esc(device.source_label)} · ${esc(compact(seconds))}</span></div><div class="device-time-track" style="width:${width}px">${items.length?`<svg viewBox="0 0 ${width} 52" width="${width}" height="52" role="group" aria-label="${esc(device.label)}应用记录">${blocks}</svg>`:'<span class="device-no-data">该范围暂无记录</span>'}</div></div>`;
 }).join('');
 $('device-time-chart').innerHTML=`<div class="device-time-plot" style="width:${width+180}px"><div class="device-axis-wrap">${axis}</div>${lanes}</div>`;
}
let syncConfig=null;
function policyFields(prefix,p) {
 return `<label class="setting-label"><input id="${prefix}-enabled" type="checkbox" ${p.enabled?'checked':''}>自动拉取</label><div class="source-fields"><label>执行方式<select id="${prefix}-mode"><option value="interval" ${p.mode==='interval'?'selected':''}>按间隔</option><option value="daily" ${p.mode==='daily'?'selected':''}>每天固定时刻</option><option value="combined" ${p.mode==='combined'?'selected':''}>间隔 + 固定时刻</option></select></label><label>间隔（分钟）<input id="${prefix}-interval" type="number" min="1" max="10080" value="${p.interval_minutes}" required></label><label>固定时刻（逗号分隔）<input id="${prefix}-times" value="${esc(p.times.join(', '))}" placeholder="08:00, 12:30, 23:00"></label><label>IANA 时区<input id="${prefix}-timezone" value="${esc(p.timezone)}" required placeholder="Asia/Shanghai"></label></div><label class="setting-label"><input id="${prefix}-startup" type="checkbox" ${p.run_on_start?'checked':''}>服务启动时执行一次</label>`;
}
function readPolicy(prefix) {
 return {enabled:$(prefix+'-enabled').checked,mode:$(prefix+'-mode').value,
 interval_minutes:Number($(prefix+'-interval').value),times:$(prefix+'-times').value.split(/[,，]/).map(s=>s.trim()).filter(Boolean),
 timezone:$(prefix+'-timezone').value.trim(),run_on_start:$(prefix+'-startup').checked};
}
function sourceSummary(p) {
 if(!p.enabled)return '自动同步已关闭';
 const interval='每 '+p.interval_minutes+' 分钟';
 const daily='每天 '+p.times.join('、');
 return (p.mode==='interval'?interval:p.mode==='daily'?daily:interval+' + '+daily)+' · '+p.timezone;
}
async function loadSources(reset=false) {
 syncConfig=await api('/api/sync-config');
 $('shared-policy-fields').innerHTML=policyFields('shared',syncConfig.shared);
 renderSourceCards();
 if(reset||!$('source-policy-fields').children.length)editSource(null);
}
function renderSourceCards(){
 $('source-list').innerHTML=syncConfig.sources.map(s=>{const status=s.status||{};return `<div class="source-card"><div class="source-card-top"><strong>${esc(s.name)}</strong><span class="pill">${s.type==='apple'?'Apple':s.transport==='frpc'?'frpc':'局域网'}</span></div><p>${esc(sourceSummary(s.effective_schedule))}<br>${s.schedule_mode==='inherit'?'继承公共配置':'独立配置'}</p><p class="muted">最近成功：${fmtStamp(status.last_success)}<br>下次计划：${s.effective_schedule.enabled?fmtStamp(status.next_at):'已关闭'}${status.running?' · 同步中':''}</p>${status.error?`<p class="source-error">${esc(status.error)}</p>`:''}<button class="table-link" data-edit-source="${esc(s.id)}">编辑配置</button><button class="table-link" data-run-source="${esc(s.id)}">立即同步</button></div>`;}).join('')||'<div class="empty">尚无数据源，填写下面的接入信息即可开始。</div>';
}
function editSource(id) {
 const s=syncConfig.sources.find(s=>s.id===id);
 $('source-editor-title').textContent=s?'编辑：'+s.name:'新增数据源';
 $('source-id').value=s?.id||'';$('source-type').value=s?.type||'activitywatch';$('source-type').disabled=!!s;
 $('source-name').value=s?.name||'';$('source-transport').value=s?.transport||'lan';$('source-url').value=s?.url||'';
 $('source-token').value='';$('source-token').placeholder=s?.has_token?'已保存 Token；留空保持原值':'AW 接口 Token（旧版无鉴权可留空）';
 $('source-bucket').value=s?.bucket||'';$('source-hostname').value=s?.hostname||'';
 $('source-schedule-mode').value=s?.schedule_mode||'inherit';
 $('source-policy-fields').innerHTML=policyFields('source-policy',s?.schedule||syncConfig.shared);
 $('source-policy-fields').disabled=$('source-schedule-mode').value==='inherit';
 $('source-test-result').textContent='';updateSourceKind();
}
function updateSourceKind() {
 const apple=$('source-type').value==='apple';$('aw-source-fields').hidden=apple;$('apple-source-note').hidden=!apple;
 $('source-url').required=!apple;
 if(apple&&!$('source-name').value)$('source-name').value='Apple 归档（本机与 iCloud 设备）';
}
async function saveSource() {
 const source={id:$('source-id').value||undefined,name:$('source-name').value,type:$('source-type').value,
 transport:$('source-transport').value,url:$('source-url').value,token:$('source-token').value,
 bucket:$('source-bucket').value,hostname:$('source-hostname').value,
 schedule_mode:$('source-schedule-mode').value,schedule:readPolicy('source-policy')};
 const result=await api('/api/sync-config',{action:'source',source});
 await loadSources();editSource(result.id);return result.id;
}
setInterval(run(async()=>{if(state.view!=='sources'||document.hidden)return;const before=Math.max(0,...(syncConfig?.sources||[]).map(s=>s.status?.last_success||0));syncConfig=await api('/api/sync-config');renderSourceCards();const after=Math.max(0,...syncConfig.sources.map(s=>s.status?.last_success||0));if(after>before){await loadMeta();await loadStats();}}),5000);
$('shared-policy-form').addEventListener('submit',run(async e=>{e.preventDefault();await api('/api/sync-config',{action:'shared',policy:readPolicy('shared')});await loadSources();toast('公共策略已保存，继承的数据源将自动应用');}));
$('source-editor').addEventListener('submit',run(async e=>{e.preventDefault();await saveSource();toast('数据源已保存');}));
$('new-source').addEventListener('click',()=>{editSource(null);$('source-editor').scrollIntoView({behavior:'smooth',block:'start'});});
$('source-type').addEventListener('change',updateSourceKind);
$('source-schedule-mode').addEventListener('change',()=>$('source-policy-fields').disabled=$('source-schedule-mode').value==='inherit');
$('source-test').addEventListener('click',run(async()=>{if(!$('source-editor').reportValidity())return;const button=$('source-test');button.disabled=true;try{const id=await saveSource();const result=await api('/api/source-test',{id});$('source-test-result').textContent='连接成功。可用桶：'+result.buckets.map(b=>b.id+'（'+b.hostname+'）').join('，');if(result.buckets.length===1){$('source-bucket').value=result.buckets[0].id;$('source-hostname').value=result.buckets[0].hostname;await saveSource();$('source-test-result').textContent='连接成功，已保存唯一 Android 前台应用桶。';}}finally{button.disabled=false;}}));
$('source-list').addEventListener('click',run(async e=>{const edit=e.target.closest('[data-edit-source]'),runButton=e.target.closest('[data-run-source]');if(edit)editSource(edit.dataset.editSource);if(runButton){runButton.disabled=true;try{await api('/api/sync',{sources:[runButton.dataset.runSource]});toast('已提交同步任务');await loadSources();}finally{runButton.disabled=false;}}}));

$('device-time-form').addEventListener('submit',run(async e=>{e.preventDefault();$('error').hidden=true;await loadDeviceTimeline();}));
$('device-time-chart').addEventListener('click',e=>{const item=e.target.closest('[data-session]');if(item)showDeviceSession(Number(item.dataset.session));});
$('device-time-chart').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){const item=e.target.closest('[data-session]');if(item){e.preventDefault();showDeviceSession(Number(item.dataset.session));}}});

$('devices').addEventListener('click',run(async e=>{const b=e.target.closest('[data-device]');if(!b)return;const id=b.dataset.device;if(state.devices.has(id)){if(state.devices.size===1)return toast('至少保留一个设备');state.devices.delete(id);}else state.devices.add(id);rememberDevices();renderMeta();await loadStats();if(state.view==='timeline')await loadTimeline();}));
$('show-empty').addEventListener('change',()=>{renderDevices();syncLocation();});
$('apply').addEventListener('click',run(async()=>{await loadStats();if(state.view==='timeline')await loadTimeline();}));
for(const b of document.querySelectorAll('[data-days]'))b.addEventListener('click',run(async()=>{preset(Number(b.dataset.days));await loadStats();}));
for(const b of document.querySelectorAll('[data-view]'))b.addEventListener('click',run(()=>showView(b.dataset.view)));
$('exact').addEventListener('change',()=>$('exact-fields').hidden=!$('exact').checked);
for(const id of ['start-date','end-date'])$(id).addEventListener('change',()=>document.querySelectorAll('[data-days]').forEach(b=>b.classList.remove('selected')));
$('dimension').addEventListener('click',e=>{const b=e.target.closest('[data-dim]');if(!b)return;state.dimension=b.dataset.dim;document.querySelectorAll('[data-dim]').forEach(el=>el.classList.toggle('active',el===b));$('trend-series').value='top';renderOverview();syncLocation();});
$('group').addEventListener('change',run(loadStats));
$('trend-series').addEventListener('change',()=>{renderTrend();syncLocation();});
$('daily').addEventListener('click',run(async e=>{const b=e.target.closest('[data-day]');if(!b)return;$('timeline-date').value=b.dataset.day;await showView('timeline');window.scrollTo({top:0,behavior:'smooth'});}));
$('timeline-date').addEventListener('change',run(loadTimeline));
$('session-search').addEventListener('input',()=>{state.sessionLimit=200;renderTimeline();syncLocation('replace');});
$('more-sessions').addEventListener('click',()=>{state.sessionLimit+=200;renderSessionRows();});
$('app-search').addEventListener('input',()=>{renderApps();syncLocation('replace');});
$('app-list').addEventListener('click',run(async e=>{const button=e.target.closest('.save-app');if(!button)return;const row=button.closest('tr');button.disabled=true;try{await api('/api/app',{bundle:row.dataset.bundle,name:row.querySelector('.app-name').value,category:row.querySelector('.app-category').value});await loadMeta();await loadStats();toast('应用名称与分类已保存');}finally{button.disabled=false;}}));
$('category-form').addEventListener('submit',run(async e=>{e.preventDefault();const f=new FormData(e.target);await api('/api/category',Object.fromEntries(f));e.target.reset();await loadMeta();toast('分类已创建');}));
$('categories').addEventListener('click',run(async e=>{const b=e.target.closest('[data-category]');if(!b)return;const c=cat(b.dataset.category);const name=prompt('修改分类名称',c.name);if(!name)return;const color=prompt('分类颜色（例如 #5473e8）',c.color);if(!color)return;await api('/api/category',{id:c.id,name,color});await loadMeta();await loadStats();toast('分类已更新');}));
$('settings-form').addEventListener('submit',run(async e=>{e.preventDefault();await api('/api/settings',Object.fromEntries(new FormData(e.target)));await loadMeta();await loadStats();toast('生活日偏好已保存');}));
$('sync').addEventListener('click',run(async()=>{const button=$('sync');button.disabled=true;button.textContent='归档中…';try{const before=state.meta.last_run;await api('/api/sync',{});let finished=false;for(let i=0;i<12;i++){await new Promise(r=>setTimeout(r,1500));await loadMeta();if(!state.meta.sync_running){finished=true;break;}}await loadStats();if(state.view==='timeline')await loadTimeline();if(state.view==='device-timeline')await loadDeviceTimeline();if(!finished)toast('归档仍在后台执行，稍后可再刷新');else if(state.meta.sync_error)throw new Error(state.meta.sync_error);else if(state.meta.errors.length)throw new Error('归档任务执行过，但有数据源读取失败：'+state.meta.errors.join('；'));else toast(state.meta.last_run>before?'归档完成，统计已更新':'已发起归档；暂无更新，请检查归档状态');}finally{button.disabled=false;button.innerHTML='<span>↻</span> 立即归档';}}));
$('logout').addEventListener('click',run(async()=>{await api('/api/logout',{});location.href='/';}));
run(async()=>{state.meta=await api('/api/meta');await restoreLocation();})();
