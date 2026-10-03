import React, {useEffect,useMemo,useRef,useState} from 'react';
import {Search,Globe,BookBookmark,ArrowUpRight,ArrowRotateCw,ChevronUpDown} from '@openai/apps-sdk-ui/components/Icon';
import {CSS} from './theme.js';
import {orderReports,usdAmount} from './feed-order.mjs';

const dateText = value => value ? new Date(value).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}) : 'Not available';
const timeText = value => value ? new Date(value).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : 'Not checked yet';
const store = () => window.mobius.storage;
function safeLink(url){try{const u=new URL(url);return ['https:','http:'].includes(u.protocol)?u.href:null}catch{return null}}
function amountLabel(value){return value?.replace(/\s*million/i,'M').replace(/\s*billion/i,'B').replace(/\s*thousand/i,'K').replace(/\s+([MBK])$/i,'$1') || 'Undisclosed';}

export default function App({appId,token}){
  const [feed,setFeed]=useState(null),[saved,setSaved]=useState({}),[loaded,setLoaded]=useState(false);
  const [query,setQuery]=useState(''),[region,setRegion]=useState('All regions'),[stage,setStage]=useState('All stages'),[sector,setSector]=useState('All sectors');
  const [onlySaved,setOnlySaved]=useState(false),[limit,setLimit]=useState(30),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[saving,setSaving]=useState(false),[refreshState,setRefreshState]=useState(null);
  const [order,setOrder]=useState('latest'),[fx,setFx]=useState(null),[history,setHistory]=useState(null),[historical,setHistorical]=useState([]);
  const ready=useRef(false);
  useEffect(()=>{
    let alive=true;
    const fail=e=>{if(alive){setError('Could not load your feed. Reopen the app to try again.');window.mobius.signal('error',{message:e.message,source:'load'})}};
    store().get('feed.json').then(v=>{if(alive){setFeed(v);if(!ready.current){ready.current=true;window.mobius.signal('app_ready',{item_count:v?.records?.length||0})}}}).catch(fail);
    store().get('saved.json').then(v=>{if(alive){setSaved(v||{});setLoaded(true)}}).catch(fail);
    const unfeed=store().subscribe('feed.json',v=>{if(alive)setFeed(v)});
    const unsaved=store().subscribe('saved.json',v=>{if(alive)setSaved(v||{})});
    const unrefresh=store().subscribe('refresh-state.json',v=>{if(alive)setRefreshState(v)});
    const unfx=store().subscribe('fx.json',v=>{if(alive)setFx(v)});
    const unhistory=store().subscribe('history.json',v=>{if(alive)setHistory(v)});
    const unhistorical=store().subscribe('history-reports.json',v=>{if(alive)setHistorical(v?.records||[])});
    return()=>{alive=false;unfeed();unsaved();unrefresh();unfx();unhistory();unhistorical()};
  },[]);
  useEffect(()=>{setLimit(30)},[query,region,stage,sector,onlySaved,order]);
  useEffect(()=>{
    if(['complete','unchanged'].includes(refreshState?.phase))
      setNotice(current=>current==='Refresh requested. Reports update after source review finishes.'?'':current);
  },[refreshState?.phase,refreshState?.finished_at]);
  const records=feed?.records||[];
  const combined=useMemo(()=>{
    const map=new Map(records.map(r=>[r.id,r]));
    historical.forEach(r=>{if(!map.has(r.id))map.set(r.id,r)});
    if(onlySaved)Object.values(saved).forEach(r=>{if(r?.id&&!map.has(r.id))map.set(r.id,r)});
    return [...map.values()].sort((a,b)=>b.published_at.localeCompare(a.published_at));
  },[records,historical,saved,onlySaved]);
  const filtered=useMemo(()=>combined.filter(r=>(!onlySaved||!!saved[r.company_key])&&(region==='All regions'||r.region===region)&&(stage==='All stages'||r.stage===stage)&&(sector==='All sectors'||r.sector===sector)&&(`${r.company} ${r.backers||''} ${r.description||''} ${r.title||''}`).toLowerCase().includes(query.toLowerCase().trim())),[combined,saved,onlySaved,region,stage,sector,query]);
  const ordered=useMemo(()=>orderReports(filtered,order,fx),[filtered,order,fx]);
  const unranked=filtered.filter(r=>usdAmount(r,fx)===null).length;
  const active=!!query||region!=='All regions'||stage!=='All stages'||sector!=='All sectors';
  const clear=()=>{setQuery('');setRegion('All regions');setStage('All stages');setSector('All sectors')};
  async function saveCompany(record){
    setSaving(true);setError('');
    try{
      // Merge the single company intent against the authoritative document;
      // a second device's saved companies must not be silently overwritten.
      const remove=!!saved[record.company_key];
      for(let attempt=0;attempt<3;attempt++){
        const {value,version}=await store().getWithVersion('saved.json');
        const next={...(value||{})};if(remove)delete next[record.company_key];else next[record.company_key]=record;
        try{
          await store().durableWrite('saved.json',next,version?{ifMatch:version}:{ifNoneMatch:true});
          setSaved(next);setNotice(remove?`${record.company} removed from saved companies.`:`${record.company} saved.`);window.mobius.signal(remove?'item_deleted':'item_created',{type:'saved_company'});break;
        }catch(e){if(e.code!=='conflict'||attempt===2)throw e}
      }
    }catch(e){setError('Could not save that change. Your previous saved companies are safe; try again when connected.');window.mobius.signal('error',{message:e.message,source:'save'})}
    finally{setSaving(false)}
  }
  async function refresh(){
    setError('');setBusy(true);
    try{
      const response=await fetch(`/api/apps/${appId}/run-job`,{method:'POST',headers:{Authorization:`Bearer ${token}`}});
      if(!response.ok)throw new Error(`Refresh request failed (${response.status})`);
      setNotice('Refresh requested. Reports update after source review finishes.');
    }catch(e){setError('Could not start a refresh. Your existing reports are still available. Try again later.');window.mobius.signal('error',{message:e.message,source:'refresh'})}
    finally{setBusy(false)}
  }
  const failed=(feed?.sources||[]).filter(s=>!s.ok);
  const lastChecked=refreshState?.phase==='unchanged'?refreshState.finished_at:feed?.checked_at;
  const stale=lastChecked&&Date.now()-new Date(lastChecked).getTime()>172800000;
  return <main className="fw"><style>{CSS}</style><div className="fw-inner">
    <header className="fw-head"><div><div className="fw-brand"><Globe aria-hidden="true"/><h1>Funding Wire</h1></div><p className="fw-sub">Who raised. Who backed them. Worldwide.</p></div>{feed?.refresh_enabled&&<button className="fw-btn" aria-label="Refresh funding reports" title="Refresh funding reports" onClick={refresh} disabled={busy}><ArrowRotateCw className={`fw-icon ${busy?'fw-spin':''}`}/></button>}</header>
    <div className="fw-update"><span><i className="fw-statusdot"/>{refreshState?.phase==='collecting'?'Collecting sources…':refreshState?.phase==='reviewing'?'Reviewing new reports…':feed?.cadence?`${feed.cadence} source checks`:'Source-linked funding reports'}</span><span>Checked {timeText(lastChecked)}</span></div>
    <div className="fw-controls"><label className="fw-search"><Search className="fw-icon" aria-hidden="true"/><input aria-label="Search companies or investors" placeholder="Company or investor" type="search" value={query} onChange={e=>setQuery(e.target.value)}/></label><label className="fw-sort" title={`Sort reports: ${order==='latest'?'Latest':'Highest raise'}`}><ChevronUpDown className="fw-icon" aria-hidden="true"/><select aria-label="Sort reports" value={order} onChange={e=>setOrder(e.target.value)}><option value="latest">Latest</option><option value="highest">Highest raise</option></select></label><button className="fw-btn fw-saved-toggle" title="Saved companies" aria-label={`Saved companies${Object.keys(saved).length?': '+Object.keys(saved).length:''}`} aria-pressed={onlySaved} onClick={()=>setOnlySaved(!onlySaved)}><BookBookmark className="fw-icon" aria-hidden="true"/><span>Saved {Object.keys(saved).length||''}</span></button></div>
    <div className="fw-fields">{[['Region',region,setRegion,'All regions','region'],['Stage',stage,setStage,'All stages','stage'],['Sector',sector,setSector,'All sectors','sector']].map(([label,value,set,all,key])=><label key={key}><span className="fw-sr-only">{label}</span><select aria-label={label} value={value} onChange={e=>set(e.target.value)}><option>{all}</option>{[...new Set(combined.map(r=>r[key]).filter(Boolean))].sort().map(v=><option key={v}>{v}</option>)}</select></label>)}</div>
    {notice&&<div className="fw-toast" role="status">{notice}</div>}
    {error&&<div className="fw-notice fw-error" role="alert">{error}</div>}
    {refreshState?.error&&<div className="fw-notice" role="alert">Refresh could not finish: {refreshState.error} Existing reports are kept. Try Refresh again.</div>}
    {(failed.length>0||stale)&&<div className="fw-notice">{stale?'These reports have not been checked in over two days. ':''}{failed.length>0?`${failed.map(s=>s.name).join(', ')} could not be checked. Existing reports are kept.`:''}</div>}
    {order==='highest'&&<p className="fw-sortnote">Compared in approximate US dollars{fx?.date?` using ${dateText(fx.date)} reference rates`:'. Currency rates are unavailable'}. Original amounts stay visible.{unranked>0?` ${unranked} ${unranked===1?'report cannot':'reports cannot'} be ranked (unknown amount, currency or rate, or a facility limit) and appear last.`:''}</p>}
    <div className="fw-results"><span><strong>{filtered.length} {filtered.length===1?'report':'reports'}</strong> · {onlySaved?'Saved companies':order==='highest'?'Highest raise first':'Latest first'}</span><div className="fw-result-actions">{active&&<button className="fw-clear" onClick={clear}>Clear filters</button>}<span>{history?.phase==='reviewing'?'History review underway':'Reported dates'}</span></div></div>
    {!feed?<section className="fw-empty"><h2>Your funding feed is getting ready</h2><p>Source-linked reports will appear here once the first collection is complete.</p></section>:filtered.length===0?<section className="fw-empty"><h2>{onlySaved&&!Object.keys(saved).length?'Keep an eye on a company':'No matching reports'}</h2><p>{onlySaved&&!Object.keys(saved).length?'Save a company from the feed to keep its report here and find future rounds.':'Try another company or investor, or clear your filters.'}</p><button className="fw-btn" onClick={()=>{clear();setOnlySaved(false)}}>Show all reports</button></section>:<ol className="fw-list">{ordered.slice(0,limit).map(r=><li className="fw-record" key={r.id}>
      <div className="fw-meta"><span className="fw-sector">{r.sector||'Other'}</span><span className="fw-dot">{r.region||'Not stated'}</span><time dateTime={r.published_at}>{dateText(r.published_at)}</time></div>
      <div className="fw-row"><h2 className="fw-company">{r.company}</h2><div className={`fw-money ${r.amount?'':'fw-unknown'}`}>{amountLabel(r.amount)}<small>{r.stage==='Not stated'?'Stage not stated':r.stage}</small></div></div>
      <p className="fw-description">{r.description}</p>
      {r.amount_kind==='Facility ceiling'&&<p className="fw-equivalent">Credit-line limit; amount drawn not disclosed. Not ranked as cash raised.</p>}
      {order==='highest'&&r.amount_currency!=='USD'&&usdAmount(r,fx)!==null&&<p className="fw-equivalent">Approx. {new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',notation:'compact',maximumFractionDigits:1}).format(usdAmount(r,fx))} USD for comparison</p>}
      <p className={`fw-valuation ${r.valuation?'':'fw-missing'}`}><span>Valuation</span> {r.valuation?`${amountLabel(r.valuation)} · ${r.valuation_basis==='Pre-money'?'pre-money':r.valuation_basis==='Post-money'?'post-money':'basis not stated'}`:'Not disclosed in available sources'}</p>
      <p className={`fw-backers ${r.backers?'':'fw-missing'}`}><span>Reported backers</span> {r.backers||'Not stated in the available report'}</p>
      <div className="fw-foot"><div className="fw-links">{[...new Map([...(r.sources||[]),...(r.amount_sources||[]),...(r.valuation_sources||[])].filter(s=>safeLink(s.url)).map(s=>[s.url,s])).values()].map(s=><a className="fw-source" key={s.url} href={safeLink(s.url)} target="_blank" rel="noopener noreferrer">{s.name}<ArrowUpRight className="fw-icon"/></a>)}</div><button className="fw-save" disabled={!loaded||saving} aria-pressed={!!saved[r.company_key]} aria-label={`${saved[r.company_key]?'Unsave':'Save'} ${r.company}`} onClick={()=>saveCompany(r)}><BookBookmark className="fw-icon"/>{saved[r.company_key]?'Saved':'Save'}</button></div>
    </li>)}</ol>}
    {filtered.length>limit&&<button className="fw-btn fw-loadmore" onClick={()=>setLimit(limit+30)}>Show more reports</button>}
    <details className="fw-method"><summary>Sources & coverage</summary>{history&&<p className="fw-sortnote" role="status">History: {dateText(history.window_start)}–{dateText(history.window_end)}. {history.phase==='complete'?'Public archive review finished; coverage is partial.':history.phase==='reviewing'?'Older reports are being verified before they appear.':history.phase==='error'?'Historical review paused after a problem; existing reports are kept.':'Collecting older public reports for review.'}{history.phase==='reviewing'&&Number.isFinite(history.reviewed)?` ${history.reviewed} of ${history.candidates} candidate stories reviewed.`:''}</p>}<p>Publicly reported funding, not a complete database of every deal. Amounts stay in their reported currency. Dates are publication dates, not necessarily the day funding closed. “Not stated” means the available source did not establish it.</p><p>Round totals are not valuations or individual investor contributions. Valuations are only shown when disclosed for this financing, with pre-money or post-money basis when stated. Debt is labelled separately. Saved companies retain a copy of the report. Coverage varies by publisher and region.</p><p>Highest raise compares source-reviewed amounts in approximate US dollars at the latest available reference rates, not rates on the funding date. Unknown amounts or currencies come last; approximate reported amounts stay approximate. Exchange rates: <a href="https://frankfurter.dev/" target="_blank" rel="noopener noreferrer">ECB via Frankfurter</a>{fx?.date?` (${dateText(fx.date)})`:''}. If a rate check fails, the last successful rates are kept.</p>{feed?.refresh_note&&<p>{feed.refresh_note}</p>}{refreshState&&<p>Latest refresh: {refreshState.phase==='reviewing'?'AI review requested':refreshState.phase==='collecting'?'Source collection requested':refreshState.phase}. {timeText(refreshState.finished_at||refreshState.started_at)}</p>}{(feed?.sources||[]).map(s=><div className="fw-sourcehealth" key={s.id}><a href={safeLink(s.url)||undefined} target="_blank" rel="noopener noreferrer">{s.name}</a><span>{s.ok?`${s.count??0} candidate stories`:'Unavailable this check'}</span></div>)}</details>
  </div></main>
}
