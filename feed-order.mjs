// Structured amounts are source-reviewed; a bare dollar sign is not a currency.
export function usdAmount(record, fx) {
  if(record.amount_kind==='Facility ceiling')return null;
  const value=record.amount_value, currency=record.amount_currency;
  if(typeof value!=='number'||!Number.isFinite(value)||value<=0||!currency)return null;
  const rate=currency==='USD'?1:fx?.usd_per_unit?.[currency];
  return typeof rate==='number'&&Number.isFinite(rate)&&rate>0?value*rate:null;
}

export function orderReports(records, order, fx) {
  return [...records].sort((a,b)=>{
    if(order==='highest'){
      const av=usdAmount(a,fx), bv=usdAmount(b,fx);
      if(av!==null&&bv!==null&&av!==bv)return bv-av;
      if(av===null&&bv!==null)return 1;
      if(av!==null&&bv===null)return -1;
    }
    return (b.published_at||'').localeCompare(a.published_at||'')||a.id.localeCompare(b.id);
  });
}
