import test from 'node:test';
import assert from 'node:assert/strict';
import {orderReports,usdAmount} from './feed-order.mjs';

const fx={usd_per_unit:{EUR:1.2,GBP:1.4}};
const record=(id,date,value,currency)=>({id,published_at:date,amount_value:value,amount_currency:currency});
test('highest raise compares currencies rather than their printed numbers',()=>{
  const a=record('usd','2026-10-01',10e6,'USD'),b=record('eur','2026-09-01',9e6,'EUR');
  assert.deepEqual(orderReports([a,b],'highest',fx).map(r=>r.id),['eur','usd']);
  assert.deepEqual(orderReports([b,a],'latest',fx).map(r=>r.id),['usd','eur']);
});
test('unknown amounts currencies and rates come last, then latest',()=>{
  const records=[record('unknown','2026-10-02',null,null),record('ranked','2026-09-01',1,'USD'),record('no-rate','2026-10-01',100,'XYZ')];
  assert.deepEqual(orderReports(records,'highest',fx).map(r=>r.id),['ranked','unknown','no-rate']);
  assert.equal(usdAmount({amount:'$2M',amount_value:2e6},fx),null);
  assert.equal(usdAmount(record('bad','',NaN,'USD'),fx),null);
  assert.equal(usdAmount(record('bad','',-1,'USD'),fx),null);
});
test('ties use latest and sorting does not mutate the saved or feed records',()=>{
  const records=[record('a','2026-09-01',10,'USD'),record('b','2026-10-01',10,'USD')];
  assert.deepEqual(orderReports(records,'highest',fx).map(r=>r.id),['b','a']);
  assert.equal(records[0].id,'a');
});
test('a facility limit is not treated as confirmed cash raised',()=>{
  const r={...record('facility','2026-10-01',1e9,'USD'),amount_kind:'Facility ceiling'};
  assert.equal(usdAmount(r,fx),null);
});
