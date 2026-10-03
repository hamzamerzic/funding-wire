export const CSS = `
.fw { --fw-ink:var(--text); --fw-line:var(--border); color:var(--fw-ink); background:var(--bg); min-height:100vh; font-family:var(--font); padding:24px 22px 60px; font-size:15px; line-height:1.5; color-scheme:light dark; }
.fw * {box-sizing:border-box} .fw ::selection {background:var(--accent);color:var(--bg)}
.fw-inner{max-width:1000px;margin:auto} .fw button,.fw input,.fw select{font:inherit; color:inherit}
.fw button,.fw select,.fw summary,.fw a{touch-action:manipulation} .fw button{cursor:pointer}
.fw button:disabled{opacity:.5;cursor:wait} .fw :focus-visible{outline:2px solid var(--accent);outline-offset:4px}
.fw a{color:inherit;text-underline-offset:4px} .fw a:hover{color:var(--accent)}
.fw-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:14px}
.fw-brand{display:flex;align-items:center;gap:12px} .fw-brand svg{width:30px;height:30px;color:var(--accent)}
.fw h1{font-size:28px;line-height:1.1;letter-spacing:-.035em;margin:0;font-weight:650}
.fw-sub{color:var(--muted);margin:7px 0 0;font-size:14px} .fw-icon{width:18px;height:18px;flex-shrink:0}
.fw-btn{border:1px solid var(--border);border-radius:8px;min-height:44px;background:var(--surface);padding:9px 12px;display:inline-flex;gap:7px;align-items:center;justify-content:center}
.fw-btn:hover{background:var(--surface-2)} .fw-btn[aria-pressed=true]{border-color:var(--accent);color:var(--accent);background:color-mix(in srgb,var(--accent) 9%,var(--bg))}
.fw-update{border-top:1px solid var(--border);border-bottom:1px solid var(--border);padding:9px 0;color:var(--muted);font-size:12px;display:flex;justify-content:space-between;gap:12px;align-items:center}
.fw-update span{display:flex;gap:7px;align-items:center}.fw-statusdot{width:6px;height:6px;border-radius:50%;background:var(--accent);display:inline-block;flex-shrink:0}
.fw-controls{margin-top:16px;display:flex;gap:8px;align-items:center}.fw-search{display:flex;align-items:center;gap:10px;flex:1;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:0 12px;min-width:0;height:46px;color:var(--muted)}
.fw-search:focus-within{border-color:var(--accent)}.fw-search input{width:100%;min-width:0;border:0;outline:0;background:transparent;height:44px;font-size:15px;caret-color:var(--accent)}.fw-search input::placeholder{color:var(--muted)}
 .fw-sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0}
.fw-sort{position:relative;display:flex;align-items:center;justify-content:center;flex:0 0 44px;width:44px;height:46px;background:var(--surface);border:1px solid var(--border);border-radius:8px;cursor:pointer}.fw-sort:hover{background:var(--surface-2)}.fw-sort:focus-within{outline:2px solid var(--accent);outline-offset:4px}.fw-sort select{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}.fw-sort svg{pointer-events:none}
.fw-fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:8px 0 4px}.fw-fields label{min-width:0}.fw-fields select{border:1px solid var(--border);border-radius:8px;background:var(--surface);width:100%;min-height:44px;padding:8px;font-size:13px;color:var(--text)}
.fw-results{display:flex;justify-content:space-between;align-items:center;padding:12px 0;color:var(--muted);font-size:12px;border-bottom:1px solid var(--border);gap:12px}.fw-results strong{color:var(--text);font-weight:600}
.fw-sortnote{color:var(--muted);font-size:12px;line-height:1.6;max-width:75ch;margin:8px 0 16px}
.fw-result-actions{display:flex;align-items:center;gap:12px}.fw-clear{background:none;border:none;color:var(--accent)!important;min-height:44px;padding:4px 0;font-size:13px!important}
.fw-list{margin:0;padding:0;list-style:none}.fw-record{padding:18px 0;border-bottom:1px solid var(--border)}
.fw-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-bottom:6px}.fw-meta time{margin-left:auto;font-variant-numeric:tabular-nums}.fw-sector{color:var(--accent);font-weight:600}.fw-dot::before{content:'·';margin-right:8px}
.fw-row{display:flex;gap:16px;justify-content:space-between;align-items:baseline}.fw-company{flex:1;min-width:0;font-size:23px;line-height:1.2;font-weight:600;letter-spacing:-.025em;margin:0;overflow-wrap:anywhere}.fw-money{text-align:right;flex:0 1 auto;max-width:46%;min-width:0;overflow-wrap:anywhere;line-height:1.25;font-size:23px;font-weight:600;letter-spacing:-.035em;font-variant-numeric:tabular-nums}.fw-money small{font-size:11px;letter-spacing:0;font-weight:400;color:var(--muted);display:block;margin-top:4px}.fw-money.fw-unknown{font-size:15px;max-width:105px}
.fw-description{font-size:14px;margin:8px 0;color:var(--text);max-width:68ch;line-height:1.6}
.fw-valuation{font-size:13px;margin:6px 0;line-height:1.6}.fw-valuation span{color:var(--muted);margin-right:8px}.fw-equivalent{font-size:12px;color:var(--muted);margin:8px 0}
.fw-backers{margin:0;font-size:13px;line-height:1.6;max-width:75ch;overflow-wrap:anywhere}.fw-backers span{color:var(--muted);font-size:12px;margin-right:8px}.fw-missing{color:var(--muted)}
.fw-foot{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:8px}.fw .fw-source{display:inline-flex;align-items:center;gap:4px;min-height:44px;font-size:13px;font-weight:500;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:4px;color:var(--accent);border-radius:4px}.fw .fw-source:hover{color:var(--text);text-decoration-thickness:2px}.fw-links{display:flex;column-gap:16px;row-gap:0;flex-wrap:wrap}.fw-save{min-width:44px;min-height:44px;background:transparent;border:1px solid transparent;border-radius:8px;display:flex;align-items:center;gap:6px;padding:8px;font-size:12px!important;color:var(--muted)!important}.fw-save:hover{background:var(--surface)}.fw-save[aria-pressed=true]{color:var(--accent)!important;background:color-mix(in srgb,var(--accent) 8%,var(--bg))}
.fw-empty{padding:50px 16px;text-align:center}.fw-empty h2{font-size:22px;font-weight:600;margin:0 0 10px}.fw-empty p{color:var(--muted);font-size:14px;max-width:360px;margin:0 auto 12px}
.fw-notice{margin:16px 0;padding:12px 14px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:var(--surface);line-height:1.6}.fw-error{border-color:var(--accent)}
.fw-method{font-size:12px;color:var(--muted);margin-top:24px}.fw-method summary{cursor:pointer;min-height:44px;padding:10px 0;color:var(--text)}.fw-method p{max-width:75ch;line-height:1.7}.fw-sourcehealth{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)}
.fw-loadmore{display:block;margin:24px auto 0}.fw-toast{font-size:12px;color:var(--muted);margin:8px 0 0}
@media(min-width:700px){.fw{padding:30px 40px 80px}.fw h1{font-size:32px}.fw-company,.fw-money{font-size:26px}.fw-record{padding:20px 0}.fw-controls{max-width:760px}.fw-fields{max-width:760px}}
@media(max-width:520px){.fw-saved-toggle{width:44px;flex-shrink:0;padding:8px}.fw-saved-toggle span{display:none}.fw-update{flex-wrap:wrap;column-gap:12px;row-gap:4px}.fw-result-actions>span{display:none}.fw-results{min-height:44px;padding:8px 0}.fw-search{padding:0 10px;gap:6px}.fw-search input{font-size:14px}}
@media(max-width:360px){.fw{padding:22px 16px}.fw h1{font-size:26px}.fw-brand{gap:8px}.fw-brand svg{width:24px}.fw-fields{gap:5px}.fw-fields select{padding:8px 3px;font-size:12px}.fw-company,.fw-money{font-size:20px}}
@media(prefers-reduced-motion:no-preference){.fw-save{transition:background-color .18s ease,color .18s ease}.fw-spin{animation:fw-spin 1.5s linear infinite}@keyframes fw-spin{to{transform:rotate(360deg)}}}
`;
