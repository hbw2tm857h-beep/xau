"""Build lab_output/dashboard.html: a single self-contained research dashboard."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import OUTPUT
from .stats import jsonable
from .taxonomy import explain, M as MISTAKES
from .counterfactual import VARIANTS

INSPECT_COLS = ["trade_id", "setup", "family", "direction", "split", "regime", "session", "tc", "fill_time",
                "exit_time", "entry", "exit", "stop_px", "target_px", "r", "r_gross", "cost_r", "exit_reason",
                "mfe_r", "mae_r", "stop_atr", "rel_mom6", "rel_mom24", "rel_d_ext", "adx", "er30", "atr_pct",
                "rel_rsi", "room_in_r", "rel_mtf_votes", "with_daily", "rel_structure", "rel_h4_structure",
                "bb_width_pct", "rel_pos50", "ml_p", "post_hit_target", "post_mae_r", "post_mfe_r"]


def _sample_trades(lab, R, per_cell: int = 4) -> pd.DataFrame:
    T = lab.trades
    pool = T[T["split"].isin(["discovery", "validation", "holdout"])]
    picks = []
    for (s, d), g in pool.groupby(["setup", "direction"]):
        for win in (1, 0):
            gg = g[g["win"] == win]
            picks.append(gg.sample(min(per_cell, len(gg)), random_state=7))
    ids = set(pd.concat(picks)["trade_id"])
    for dsc in R.get("discoveries", [])[:12]:
        ids |= set(dsc.get("examples", [])[:3]) | set(dsc.get("counterexamples", [])[:3])
    return T[T["trade_id"].isin(ids)].drop_duplicates("trade_id")


def _decision_quality(T: pd.DataFrame) -> pd.Series:
    if "ml_p" not in T:
        return np.full(len(T), "unscored")
    med = T.groupby("year")["ml_p"].transform("median")
    return np.where(T["ml_p"].isna(), "unscored", np.where(T["ml_p"] >= med, "above", "below"))


def _inspect_payload(lab, R) -> list[dict]:
    T = lab.trades.copy()
    T["quality"] = _decision_quality(T)
    S = _sample_trades(lab, R)
    S = T.loc[T["trade_id"].isin(S["trade_id"])]
    f = lab.f
    cfi = lab.cf.set_index("trade_id")
    tax = {r["id"]: r for r in R["taxonomy"]}
    tc = f["tc"].values
    out = []
    for i, row in S.iterrows():
        a = int(row["idx"])
        e = int(np.searchsorted(tc, np.datetime64(row["exit_time"]), side="left"))
        lo, hi = max(0, a - 48), min(len(f), max(e, a) + 14)
        hi = min(hi, lo + 170)
        w = f.iloc[lo:hi]
        bars = [[str(t)[:16], round(o, 2), round(h, 2), round(l, 2), round(c, 2)]
                for t, o, h, l, c in zip(w["t"], w["open"], w["high"], w["low"], w["close"])]
        flags = lab.flags.loc[i] if i in lab.flags.index else pd.Series(dtype=bool)
        ex = explain(row, flags)
        for x in ex:
            st = tax.get(x["id"], {})
            x["verdict"] = st.get("verdict"); x["delta_r"] = st.get("delta_r"); x["replicated"] = st.get("replicated")
        cfr = cfi.loc[row["trade_id"]].to_dict() if row["trade_id"] in cfi.index else {}
        rec = {k: row.get(k) for k in INSPECT_COLS if k in row}
        rec.update({"quality": row["quality"], "bars": bars, "flags": ex, "cf": cfr,
                    "ema20": [None if np.isnan(x) else round(x, 2) for x in w["ema20"]],
                    "bb_up": [None if np.isnan(x) else round(x, 2) for x in w["bb_up"]],
                    "bb_lo": [None if np.isnan(x) else round(x, 2) for x in w["bb_lo"]]})
        out.append(rec)
    return out


def _regime_series(lab) -> dict:
    f = lab.f
    d = f.groupby(f["tc"].dt.floor("D")).agg(close=("close", "last"), regime=("regime_trend", "last"))
    d = d.iloc[::2]
    return {"t": [str(x)[:10] for x in d.index], "close": d["close"].round(2).tolist(), "regime": d["regime"].tolist()}


def _distributions(lab) -> dict:
    T = lab.trades
    T = T[T["split"] != "archive"]
    bins = np.arange(-2.0, 4.01, 0.25)
    out = {"bins": bins.tolist()}
    for s, g in T.groupby("setup"):
        out[s] = np.histogram(g["r"].clip(-2, 3.99), bins)[0].tolist()
    out["ALL"] = np.histogram(T["r"].clip(-2, 3.99), bins)[0].tolist()
    eq = {}
    for (s, d), g in T.sort_values("tc").groupby(["setup", "direction"]):
        c = g["r"].cumsum().values
        st = max(1, len(c) // 150)
        eq[f"{s}|{d}"] = {"t": [str(x)[:10] for x in g["tc"].values[::st]], "r": np.round(c[::st], 2).tolist()}
    out["equity"] = eq
    return out


def build(R: dict, lab) -> str:
    payload = {k: R[k] for k in R}
    payload["inspect"] = _inspect_payload(lab, R)
    payload["regime_series"] = _regime_series(lab)
    payload["dist"] = _distributions(lab)
    payload["variants"] = VARIANTS
    payload["mistake_defs"] = [{"id": m.id, "name": m.name, "family": m.family, "phase": m.phase,
                               "definition": m.definition} for m in MISTAKES]
    payload["ledger"] = R.get("ledger", [])[-1500:]
    data = json.dumps(jsonable(payload), default=str, separators=(",", ":"))
    html = TEMPLATE.replace("/*__DATA__*/null", data)
    OUTPUT.mkdir(exist_ok=True)
    p = OUTPUT / "dashboard.html"
    p.write_text(html)
    print(f"[dashboard] {p} ({len(html)/1e6:.1f} MB, {len(payload['inspect'])} inspectable trades)")
    return str(p)


TEMPLATE = r"""<title>The Edge Lab</title>
<meta name="claude:viewport-fit-sides" content="cover">
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Fraunces:opsz,wght@9..144,600&display=swap">
<style>
/* Layout: a bullion-desk research console. Sticky tab rail, dense panels, numbers in mono. */
:root{
  --bg:#f6f5f1; --panel:#ffffff; --ink:#1d1b16; --muted:#6b675c; --line:#e3dfd4; --gold:#a67c00; --gold-soft:#f3e6bf;
  --pos:#257de0; --neg:#ec4647; --long:#257de0; --short:#f47230; --mid:#b9b5aa;
  --good:#0b7d3b; --warn:#b26b00; --crit:#c0322f;
  --f-display:"Fraunces",Georgia,serif; --f-body:"IBM Plex Sans",system-ui,sans-serif; --f-mono:"IBM Plex Mono",ui-monospace,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#14130f; --panel:#1d1c17; --ink:#efece3; --muted:#a19c8f; --line:#34322a; --gold:#e0b84a; --gold-soft:#3a3220;
  --pos:#338ced; --neg:#eb6263; --long:#338ced; --short:#e76624; --mid:#5a574e; --good:#3fbf6e; --warn:#e0a03a; --crit:#f06a66; color-scheme:dark}}
:root[data-theme="dark"]{--bg:#14130f; --panel:#1d1c17; --ink:#efece3; --muted:#a19c8f; --line:#34322a; --gold:#e0b84a; --gold-soft:#3a3220;
  --pos:#338ced; --neg:#eb6263; --long:#338ced; --short:#e76624; --mid:#5a574e; --good:#3fbf6e; --warn:#e0a03a; --crit:#f06a66; color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--f-body);font-size:14px;line-height:1.5;margin:0}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--panel)}
.wrap{padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));max-width:1400px;margin:0 auto}
header{background:var(--panel);border-bottom:1px solid var(--line)}
header .wrap{padding-block:18px 0;display:flex;flex-direction:column;gap:6px}
h1{font-family:var(--f-display);font-size:28px;margin:0;letter-spacing:-.01em}
h1 span{color:var(--gold)}
.sub{color:var(--muted);max-width:75ch;margin:0}
nav{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--panel);border-bottom:1px solid var(--line)}
nav .wrap{display:flex;gap:2px;overflow-x:auto;scrollbar-width:thin}
nav a{padding:10px 12px;color:var(--muted);text-decoration:none;white-space:nowrap;border-bottom:2px solid transparent;font-weight:500}
nav a.on{color:var(--ink);border-bottom-color:var(--gold)}
nav a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--gold);outline-offset:2px}
main .wrap{padding-block:20px 60px;display:flex;flex-direction:column;gap:18px}
section[hidden]{display:none!important}
section{display:flex;flex-direction:column;gap:16px}
h2{font-family:var(--f-display);font-size:22px;margin:0;text-wrap:balance}
h3{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0;font-weight:600}
.lead{color:var(--muted);max-width:80ch;margin:0}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
.grid > *{min-width:0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px 16px;display:flex;flex-direction:column;gap:10px;min-width:0}
.kpis{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px 14px}
.kpi b{display:block;font-family:var(--f-mono);font-size:22px;font-weight:500}
.kpi small{color:var(--muted);font-size:12px}
.tbl{overflow-x:auto;max-height:560px;overflow-y:auto}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{position:sticky;top:0;background:var(--panel);color:var(--muted);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;cursor:pointer}
td.n{font-family:var(--f-mono);font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
tr.click{cursor:pointer} tr.click:hover td{background:var(--gold-soft)}
.pos{color:var(--good)} .neg{color:var(--crit)}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:11.5px;border:1px solid var(--line);white-space:nowrap}
.pill.good{color:var(--good);border-color:currentColor} .pill.crit{color:var(--crit);border-color:currentColor}
.pill.warn{color:var(--warn);border-color:currentColor} .pill.muted{color:var(--muted)}
.chart{width:100%;min-height:320px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
select,input{font:inherit;padding:5px 8px;border:1px solid var(--line);border-radius:4px;background:var(--panel);color:var(--ink);max-width:100%}
.note{font-size:12.5px;color:var(--muted);max-width:90ch}
.callout{border-left:3px solid var(--gold);padding:8px 12px;background:var(--gold-soft);border-radius:0 4px 4px 0;max-width:100ch}
.mono{font-family:var(--f-mono);font-size:12.5px}
.disc{border:1px solid var(--line);border-radius:6px;background:var(--panel);padding:14px 16px;display:flex;flex-direction:column;gap:8px}
.disc header{all:unset;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.disc .def{font-family:var(--f-mono);font-size:13px}
dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:2px 14px;margin:0;font-size:12.5px}
dl.kv dt{color:var(--muted)} dl.kv dd{margin:0;font-family:var(--f-mono)}
.flag{border-left:3px solid var(--mid);padding:4px 10px}
.flag.crit{border-color:var(--crit)} .flag.good{border-color:var(--good)} .flag.post{border-color:var(--gold)}
@media (prefers-reduced-motion: reduce){*{transition:none!important}}
</style>
<header><div class="wrap">
  <h1>The <span>Edge</span> Lab</h1>
  <p class="sub" id="subtitle">XAUUSD decision reconstruction, mistake taxonomy and hypothesis testing. Research only: no live trading, no broker connection.</p>
  <div style="height:8px"></div>
</div></header>
<nav><div class="wrap" id="tabs"></div></nav>
<main><div class="wrap" id="main"></div></main>

<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
<script>
const D = /*__DATA__*/null;
const $ = (s, r=document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const num = (x, d=3) => (x===null||x===undefined||Number.isNaN(x)) ? "–" : (+x).toFixed(d);
const sgn = (x, d=3) => (x===null||x===undefined) ? "–" : ((x>0?"+":"") + (+x).toFixed(d));
const pct = x => (x===null||x===undefined) ? "–" : (100*x).toFixed(1)+"%";
const cls = x => x>0 ? "pos" : (x<0 ? "neg" : "");
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const dirName = d => +d>0 ? "Long" : "Short";

function layout(extra={}) {
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: {family: "IBM Plex Sans, system-ui, sans-serif", size: 12, color: css("--ink")},
    margin: {l: 52, r: 16, t: 28, b: 44},
    xaxis: {gridcolor: css("--line"), zerolinecolor: css("--mid"), linecolor: css("--line"), tickfont:{color:css("--muted")}},
    yaxis: {gridcolor: css("--line"), zerolinecolor: css("--mid"), linecolor: css("--line"), tickfont:{color:css("--muted")}},
    legend: {orientation: "h", y: 1.12, x: 0, font:{color:css("--muted")}},
    hoverlabel: {bgcolor: css("--panel"), bordercolor: css("--line"), font:{color: css("--ink"), family:"IBM Plex Mono, monospace"}},
  }, extra);
}
const CFG = {displaylogo:false, responsive:true, modeBarButtonsToRemove:["lasso2d","select2d","autoScale2d"]};
function plot(id, data, lay) { const el = document.getElementById(id); if (!el || !window.Plotly) return; Plotly.react(el, data, layout(lay), CFG); }

function table(rows, cols, opts={}) {
  const id = "t" + Math.random().toString(36).slice(2,8);
  const head = cols.map((c,i) => `<th data-i="${i}" scope="col">${esc(c.label)}</th>`).join("");
  const body = rows.map((r,ri) => `<tr ${opts.click?`class="click" data-ri="${ri}"`:""}>` + cols.map(c => {
      const v = c.f ? c.f(r) : r[c.k];
      return `<td class="${c.num?'n ':''}${c.cls?c.cls(r):''}">${c.html ? v : esc(v)}</td>`; }).join("") + "</tr>").join("");
  setTimeout(() => {
    const t = document.getElementById(id); if (!t) return;
    if (opts.click) t.querySelectorAll("tr.click").forEach(tr => tr.onclick = () => opts.click(rows[+tr.dataset.ri]));
    t.querySelectorAll("th").forEach(th => th.onclick = () => {
      const c = cols[+th.dataset.i]; const key = r => c.sort ? c.sort(r) : (c.k ? r[c.k] : 0);
      const asc = th.dataset.asc !== "1"; th.dataset.asc = asc ? "1" : "0";
      rows.sort((a,b) => { const x = key(a), y = key(b); return (x>y?1:x<y?-1:0) * (asc?1:-1); });
      t.parentElement.outerHTML = table(rows, cols, opts);
    });
  });
  return `<div class="tbl"><table id="${id}"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

const verdictPill = v => {
  if (!v) return "";
  if (v.startsWith("confirmed")) return `<span class="pill crit">${esc(v)}</span>`;
  if (v.startsWith("CONTRA")) return `<span class="pill good">${esc(v)}</span>`;
  if (v.startsWith("SUPPORTED")) return `<span class="pill good">${esc(v)}</span>`;
  if (v.startsWith("diag")) return `<span class="pill warn">${esc(v)}</span>`;
  return `<span class="pill muted">${esc(v)}</span>`;
};
const statusPill = s => {
  const m = {validated:"good", weak_holdout:"warn", passed_validation:"warn", contradicted_holdout:"crit",
             failed_validation:"crit", negative_edge:"crit", rejected_discovery:"muted", passed_discovery:"warn",
             robustness_check:"muted"};
  return `<span class="pill ${m[s]||'muted'}">${esc(s)}</span>`;
};

/* ------------------------------------------------------------------ tabs */
const TABS = [
  ["overview","Overview"],["setups","Setups"],["mistakes","Mistake taxonomy"],["counterfactuals","Counterfactuals"],
  ["lookalikes","Look-alikes"],["events","Event studies"],["behaviour","Market behaviour"],["discoveries","Discoveries"],
  ["experiments","Experiments"],["profile","Edge profile"],["inspector","Trade inspector"]];
const R = {};

function overview() {
  const ex = D.experiments, sc = D.scan, ml = D.ml;
  const val = (D.discoveries||[]).filter(d => d.status==="validated").length;
  const audit = D.audit;
  return `<h2>Where the evidence stands</h2>
  <p class="lead">Every number below is after spread and slippage, measured in R (multiples of initial risk). The lab is built to disprove ideas; most fail, and every failure is kept in the ledger.</p>
  <div class="kpis">
    <div class="kpi"><small>H1 bars (M15 for fills)</small><b>${D.data.h1_bars.toLocaleString()}</b><small>${D.data.h1_from.slice(0,10)} → ${D.data.h1_to.slice(0,10)}</small></div>
    <div class="kpi"><small>Reconstructed decisions</small><b>${D.data.trades.toLocaleString()}</b><small>16 setups × long/short</small></div>
    <div class="kpi"><small>Trials counted (incl. legacy)</small><b>${ex.n_trials_total.toLocaleString()}</b><small>${ex.legacy_trials} legacy · ${ex.scan_trials} scan · ledger</small></div>
    <div class="kpi"><small>Scan cells p&lt;0.05 vs chance</small><b>${sc.observed_p05} / ${Math.round(sc.expected_false_at_p05)}</b><small>FDR survivors: ${sc.fdr_survivors}</small></div>
    <div class="kpi"><small>Reality Check (best of family)</small><b>p=${D.reality_check&&D.reality_check.p_studentised!=null?num(D.reality_check.p_studentised,3):"–"}</b><small>${D.reality_check?D.reality_check.n_hypotheses+" hypotheses · "+(D.reality_check.rw_survivors||[]).length+" survive FWER":""}</small></div>
    <div class="kpi"><small>Validated discoveries</small><b>${val}</b><small>of ${ex.n_hypotheses} hypotheses tested</small></div>
    <div class="kpi"><small>Look-ahead audit</small><b>${audit ? (audit.feature_mismatches + audit.mismatches === 0 ? "clean" : "LEAK") : "not run"}</b><small>${audit ? audit.feature_checks+" feature + "+audit.decisions_checked+" decision checks" : "python -m edgelab audit"}</small></div>
  </div>
  <div class="grid">
    <div class="panel"><h3>Headline findings</h3><div id="headlines"></div></div>
    <div class="panel"><h3>ML meta-filter, walk-forward (out-of-sample every year)</h3><div id="ml_chart" class="chart"></div>
      <p class="note">AUC ${Object.entries(ml.auc||{}).map(([k,v])=>k+" "+num(v,3)).join(" · ")}. Bars: average R of all trades vs the top 20% the model (trained only on earlier years) preferred.</p>
      <h3>Model-selected trades under each exit (base R; holdout hidden on purpose)</h3>${mlExits()}</div>
  </div>
  <div class="panel"><h3>Data splits</h3><p class="note">${Object.entries(D.splits).map(([k,v])=>`<b>${k}</b> ${v[0]} → ${v[1].slice(0,10)}`).join(" · ")}. Holdout is out-of-sample for this lab, but earlier research rounds in <span class="mono">research/</span> viewed all years; their ${ex.legacy_trials} logged trials are added to the multiple-testing count.</p></div>`;
}
function overviewAfter() {
  const py = D.ml.per_year || [];
  plot("ml_chart", [
    {type:"bar", name:"All trades", x:py.map(r=>r.year), y:py.map(r=>r.all_avg_r), marker:{color:css("--mid")}},
    {type:"bar", name:"Model top 20%", x:py.map(r=>r.year), y:py.map(r=>r.sel_avg_r), marker:{color:css("--gold")}},
  ], {barmode:"group", yaxis:{title:"avg R / trade", gridcolor:css("--line"), zerolinecolor:css("--muted")}});
  $("#headlines").innerHTML = headlines();
}
function mlExits() {
  const e = D.ml.selected_by_exit || {}; const sp = ["discovery","validation","holdout"].filter(k=>e[k]);
  if (!sp.length) return "";
  const vs = Object.keys(D.variants).filter(v => e[sp[0]][v] !== undefined && v !== "skip");
  return table(vs.map(v => ({v, ...Object.fromEntries(sp.map(k=>[k, e[k][v]]))})),
    [{label:"Exit",k:"v"}, ...sp.map(k => ({label:k, num:1, f:r=>sgn(r[k]), cls:r=>cls(r[k]), sort:r=>r[k]}))]);
}
function headlines() {
  const h = [];
  const conv = D.conventional || [];
  const anyGross = conv.filter(c => c.oos_gross_t > 2).length;
  h.push(`<b>${conv.length - anyGross} of ${conv.length}</b> textbook setups show no out-of-sample edge even <i>before</i> costs. After costs, every one is ≤ ${sgn(Math.max(...conv.map(c=>c.net_holdout||-9)),2)}R on the holdout.`);
  const tx = D.taxonomy || [];
  const contra = tx.filter(t => (t.verdict||"").startsWith("CONTRA") && t.replicated).map(t=>t.name);
  const conf = tx.filter(t => (t.verdict||"").startsWith("confirmed") && t.replicated).map(t=>t.name);
  if (contra.length) h.push(`"Mistakes" that <b>replicated as advantages</b>: ${contra.map(esc).join("; ")}.`);
  if (conf.length) h.push(`Mistakes <b>confirmed</b> in discovery and later data: ${conf.map(esc).join("; ")}.`);
  const ob = D.oaxaca; if (ob) h.push(`Shorts trail longs by ${sgn(ob.total_gap,3)}R per trade; only ${sgn(ob.composition_effect,3)}R of that is the regime mix — the rest happens within the same regimes.`);
  const sel = D.ml.oos_selected||{}, all = D.ml.oos_all||{};
  if (sel.holdout) h.push(`The walk-forward model lifts holdout expectancy from ${sgn(all.holdout.avg_r,3)}R to ${sgn(sel.holdout.avg_r,3)}R: a real but small signal that does not clear costs.`);
  const rc = D.reality_check; if (rc && rc.n_hypotheses) h.push(`White's Reality Check over ${rc.n_hypotheses} hypotheses: the best one (<span class="mono">${esc(rc.best)}</span>) has studentised p = ${num(rc.p_studentised,3)}; <b>${(rc.rw_survivors||[]).length}</b> survive family-wise correction.`);
  const hs = D.hindsight_best_alt||{}; const top = Object.entries(hs)[0];
  if (top) h.push(`In hindsight, "${esc(top[0])}" would have rescued ${pct(top[1])} of losers — yet as a rule it adds nothing. Hindsight fixes are not edges.`);
  return "<ul style='margin:0;padding-left:18px;display:flex;flex-direction:column;gap:6px'>" + h.map(x=>`<li>${x}</li>`).join("") + "</ul>";
}

function setups() {
  return `<h2>Setup performance</h2>
  <p class="lead">Each setup is a conventional chart idea, reconstructed bar by bar and executed with a structural stop, a 2R target and a 48h time stop. Gross = before costs.</p>
  <div class="row"><label for="sp_split">Split</label><select id="sp_split">${["discovery","validation","holdout","archive"].map(s=>`<option>${s}</option>`).join("")}</select></div>
  <div class="panel" id="sp_tbl"></div>
  <div class="grid">
    <div class="panel"><h3>Cumulative R by setup</h3><div class="row"><select id="eq_sel"></select></div><div id="eq_chart" class="chart"></div></div>
    <div class="panel"><h3>R-multiple distribution</h3><div class="row"><select id="dist_sel"></select></div><div id="dist_chart" class="chart"></div></div>
  </div>
  <div class="panel"><h3>Conventional claims scoreboard</h3>${table(D.conventional.slice(), [
    {label:"Setup",k:"setup"},{label:"Claim",k:"claim"},
    {label:"Gross disc",num:1,f:r=>sgn(r.gross_discovery),cls:r=>cls(r.gross_discovery)},
    {label:"Gross valid",num:1,f:r=>sgn(r.gross_validation),cls:r=>cls(r.gross_validation)},
    {label:"Gross hold",num:1,f:r=>sgn(r.gross_holdout),cls:r=>cls(r.gross_holdout)},
    {label:"Net hold",num:1,f:r=>sgn(r.net_holdout),cls:r=>cls(r.net_holdout)},
    {label:"OOS gross t",num:1,f:r=>num(r.oos_gross_t,2)},{label:"Verdict",html:1,f:r=>verdictPill(r.verdict)}])}</div>`;
}
function setupsAfter() {
  const draw = () => {
    const sp = $("#sp_split").value;
    const rows = D.setup_perf.filter(r => r.split === sp);
    $("#sp_tbl").innerHTML = table(rows, [
      {label:"Setup",k:"setup"},{label:"Side",f:r=>dirName(r.direction)},{label:"n",num:1,k:"n"},
      {label:"Win",num:1,f:r=>pct(r.win)},{label:"Gross R",num:1,f:r=>sgn(r.gross),cls:r=>cls(r.gross)},
      {label:"Cost R",num:1,f:r=>num(r.cost)},{label:"Net R (EV)",num:1,f:r=>sgn(r.avg_r),cls:r=>cls(r.avg_r),sort:r=>r.avg_r},
      {label:"PF",num:1,f:r=>num(r.pf,2)},{label:"Max DD R",num:1,f:r=>num(r.max_dd,1)},{label:"t",num:1,f:r=>num(r.t,2)}]);
  };
  $("#sp_split").onchange = draw; draw();
  const keys = Object.keys(D.dist.equity);
  $("#eq_sel").innerHTML = [...new Set(keys.map(k=>k.split("|")[0]))].map(s=>`<option>${s}</option>`).join("");
  const eq = () => { const s = $("#eq_sel").value;
    plot("eq_chart", [1,-1].map(d => { const e = D.dist.equity[s+"|"+d]; return e ? {type:"scatter",mode:"lines",name:dirName(d),x:e.t,y:e.r,line:{width:2,color:css(d>0?"--long":"--short")}} : null; }).filter(Boolean),
      {yaxis:{title:"cumulative R", gridcolor:css("--line"), zerolinecolor:css("--muted")}}); };
  $("#eq_sel").onchange = eq; eq();
  $("#dist_sel").innerHTML = ["ALL", ...Object.keys(D.dist).filter(k=>!["bins","equity","ALL"].includes(k))].map(s=>`<option>${s}</option>`).join("");
  const ds = () => { const s = $("#dist_sel").value, b = D.dist.bins, c = D.dist[s];
    const x = c.map((_,i)=> (b[i]+b[i+1])/2);
    plot("dist_chart", [{type:"bar", x, y:c, marker:{color:x.map(v=>v>0?css("--pos"):css("--neg"))}, hovertemplate:"R≈%{x:.2f}: %{y} trades<extra></extra>"}],
      {bargap:0.08, xaxis:{title:"R (clipped −2…4)", gridcolor:css("--line")}, yaxis:{title:"trades", gridcolor:css("--line")}}); };
  $("#dist_sel").onchange = ds; ds();
}

function mistakes() {
  const tx = D.taxonomy;
  return `<h2>Mistake taxonomy</h2>
  <p class="lead">${tx.length} categories. <b>Ex-ante</b> mistakes are visible before entry and are tested: a "mistake" that does not lower expectancy is folklore, and one where flagged trades do better is contradicted. <b>Ex-post</b> categories diagnose what went wrong and cannot be used as filters.</p>
  <div class="row"><label for="tx_phase">Phase</label><select id="tx_phase"><option value="">all</option><option>ex_ante</option><option>ex_post</option><option>execution</option></select></div>
  <div class="panel" id="tx_tbl"></div>
  <div class="grid">
    <div class="panel"><h3>Losing trades: share flagged, by setup × category</h3><div id="tx_heat" class="chart" style="min-height:520px"></div></div>
    <div class="panel"><h3>Failed setups by hour (UTC) × weekday: average R</h3><div id="hd_heat" class="chart" style="min-height:360px"></div>
      <p class="note">All setups, discovery to holdout. Red = worse than zero after costs.</p></div>
  </div>`;
}
function mistakesAfter() {
  const draw = () => {
    const ph = $("#tx_phase").value;
    const rows = D.taxonomy.filter(r => !ph || r.phase === ph);
    $("#tx_tbl").innerHTML = table(rows, [
      {label:"ID",k:"id"},{label:"Category",f:r=>`<b>${esc(r.name)}</b><br><span class="note">${esc(r.definition)}</span>`,html:1},
      {label:"Family",k:"family"},{label:"Phase",k:"phase"},{label:"n",num:1,k:"n_flagged"},
      {label:"% losers",num:1,f:r=>pct(r.freq_losers)},{label:"% winners",num:1,f:r=>pct(r.freq_winners)},
      {label:"ΔR disc",num:1,f:r=>sgn(r.delta_r),cls:r=>cls(r.delta_r),sort:r=>r.delta_r},
      {label:"q",num:1,f:r=>num(r.q_value,3)},{label:"Verdict (disc)",html:1,f:r=>verdictPill(r.verdict)},
      {label:"ΔR OOS",num:1,f:r=>sgn(r.delta_r_oos),cls:r=>cls(r.delta_r_oos)},{label:"Verdict (OOS)",html:1,f:r=>verdictPill(r.verdict_oos)}]);
  };
  $("#tx_phase").onchange = draw; draw();
  const mb = D.mistake_by_setup; const ids = D.mistake_defs.map(m=>m.id);
  plot("tx_heat", [{type:"heatmap", x:ids, y:mb.map(r=>r.setup), z:mb.map(r=>ids.map(i=>r[i])),
      colorscale:[[0,css("--panel")],[1,css("--neg")]], hovertemplate:"%{y} · %{x}: %{z:.0%} of losers<extra></extra>", colorbar:{tickformat:".0%"}}],
      {margin:{l:130,r:10,t:10,b:40}, xaxis:{tickangle:-60, tickfont:{size:9,color:css("--muted")}}});
  const hd = D.heat_hour_dow; const days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
  const z = [0,1,2,3,4,6].map(d => Array.from({length:24},(_,h)=>{ const r = hd.find(x=>x.dow===d && x.hour===h); return r && r.size>=30 ? r.mean : null; }));
  plot("hd_heat", [{type:"heatmap", x:[...Array(24).keys()], y:[0,1,2,3,4,6].map(d=>days[d]), z, zmid:0,
      colorscale:[[0,css("--neg")],[0.5,css("--panel")],[1,css("--pos")]], hovertemplate:"%{y} %{x}:00 · avg %{z:.3f}R<extra></extra>"}],
      {margin:{l:44,r:10,t:10,b:36}, xaxis:{title:"hour UTC", dtick:2}});
}

function counterfactuals() {
  return `<h2>Counterfactual replay</h2>
  <p class="lead">Every trade was re-run 17 ways. The <b>policy</b> view applies one alternative to all trades of a setup, winners included. That is the only view that could become a rule. The <b>hindsight</b> view picks the best alternative after the fact and is shown only to demonstrate how misleading it is.</p>
  <div class="row"><label for="cf_split">Data</label><select id="cf_split"><option value="discovery">discovery</option><option value="oos">validation + holdout</option></select></div>
  <div class="panel"><h3>Change in expectancy vs. base (R per trade, in original-risk units)</h3><div id="cf_heat" class="chart" style="min-height:620px"></div></div>
  <div class="grid">
    <div class="panel"><h3>Hindsight: best alternative for each loser</h3><div id="hs_chart" class="chart"></div></div>
    <div class="panel"><h3>Alternatives</h3>${table(Object.entries(D.variants).map(([k,v])=>({k,v})),[{label:"Variant",k:"k"},{label:"Definition",k:"v"}])}
      <p class="note">"enter_earlier_1" needs knowledge of the signal before it existed. It measures how much of the move happens inside the signal candle, and is not actionable.</p></div>
  </div>`;
}
function counterfactualsAfter() {
  const draw = () => {
    const rows = D.policy[$("#cf_split").value];
    const vs = Object.keys(D.variants).filter(v => v!=="base");
    plot("cf_heat", [{type:"heatmap", x:vs, y:rows.map(r=>r.setup+" "+(r.direction>0?"L":"S")),
      z:rows.map(r=>vs.map(v=>r[v]-r.base)), zmid:0, zmin:-0.3, zmax:0.3,
      colorscale:[[0,css("--neg")],[0.5,css("--panel")],[1,css("--pos")]],
      hovertemplate:"%{y} · %{x}: %{z:+.3f}R vs base<extra></extra>"}], {margin:{l:150,r:10,t:10,b:90}, xaxis:{tickangle:-40}});
  };
  $("#cf_split").onchange = draw; draw();
  const hs = Object.entries(D.hindsight_best_alt);
  plot("hs_chart", [{type:"bar", orientation:"h", y:hs.map(x=>x[0]).reverse(), x:hs.map(x=>x[1]).reverse(), marker:{color:css("--gold")},
     hovertemplate:"%{y}: %{x:.1%} of losers<extra></extra>"}], {margin:{l:120,r:10,t:10,b:36}, xaxis:{tickformat:".0%"}});
}

function lookalikes() {
  const rows = D.lookalike || [];
  return `<h2>Winners vs. look-alike losers</h2>
  <p class="lead">${D.lookalike_pairs.toLocaleString()} loser→winner pairs matched on what the chart showed at the signal candle (candle shape, wicks, stop size, short-term move). The table lists hidden context features that differ inside pairs. "Replicates" requires the same sign with q&lt;0.05 in discovery and p&lt;0.05 in later data.</p>
  <div class="callout note">Effect sizes are tiny (a few hundredths of a standard deviation, and winners are "higher" in only ~48–50% of pairs). At the one-hour scale, setups that look the same mostly diverge on noise. Any edge built on these differences will be thin.</div>
  <div class="panel">${table(rows, [
    {label:"Feature",k:"feature"},{label:"Group",k:"group"},{label:"Winner mean",num:1,f:r=>num(r.winner_mean)},
    {label:"Loser mean",num:1,f:r=>num(r.loser_mean)},{label:"Effect (sd)",num:1,f:r=>sgn(r.effect),cls:r=>cls(r.effect)},
    {label:"Pairs winner higher",num:1,f:r=>pct(r.consistency)},{label:"q disc",num:1,f:r=>num(r.q_value,4)},
    {label:"Effect later",num:1,f:r=>sgn(r.effect_later),cls:r=>cls(r.effect_later)},{label:"p later",num:1,f:r=>num(r.p_value_later,4)},
    {label:"Replicates",html:1,f:r=>r.replicates?'<span class="pill good">yes</span>':'<span class="pill muted">no</span>'}])}</div>
  <div class="panel"><h3>By setup family (q &lt; 0.01)</h3>${table(D.lookalike_by_family||[], [
    {label:"Family",k:"fam"},{label:"Feature",k:"feature"},{label:"Effect",num:1,f:r=>sgn(r.effect),cls:r=>cls(r.effect)},
    {label:"Pairs",num:1,k:"n_pairs"},{label:"q",num:1,f:r=>num(r.q_value,4)}])}</div>`;
}

function events() {
  const P = D.event_paths.paths, keys = Object.keys(P).sort();
  const rows = keys.map(k => ({k, setup:k.split("|")[0], dir:+k.split("|")[1], ...P[k]}));
  return `<h2>Event studies: the average path around each setup</h2>
  <p class="lead">Price relative to the trade direction, in ATR at the decision, from 24 hours before to 48 hours after the trigger (hour 0). Above zero = the move the setup expects. The dashed line is gold's unconditional drift, so a setup has to beat it, not zero.</p>
  <div class="row"><label for="ev_sel">Setup</label><select id="ev_sel">${keys.map(k=>`<option value="${k}">${k.split("|")[0]} ${+k.split("|")[1]>0?"long":"short"}</option>`).join("")}</select></div>
  <div class="grid"><div class="panel"><h3>Average path, interquartile band</h3><div id="ev_chart" class="chart" style="min-height:380px"></div></div>
  <div class="panel"><h3>Winners vs losers (descriptive, outcome-labelled)</h3><div id="ev_wl" class="chart" style="min-height:380px"></div></div></div>
  <div class="panel"><h3>Where every setup's average path ends up</h3>${table(rows, [{label:"Setup",k:"setup"},{label:"Side",f:r=>dirName(r.dir)},{label:"n",num:1,k:"n"},
    {label:"Move into trigger (−24h→0)",num:1,f:r=>sgn(-r.mean[0],2),cls:r=>cls(-r.mean[0]),sort:r=>-r.mean[0]},
    {label:"+12h",num:1,f:r=>sgn(r.fwd12,3)},{label:"+48h",num:1,f:r=>sgn(r.fwd48,3)},
    {label:"+12h vs drift",num:1,f:r=>sgn(r.excess12,3),cls:r=>cls(r.excess12),sort:r=>r.excess12},
    {label:"+48h vs drift",num:1,f:r=>sgn(r.excess48,3),cls:r=>cls(r.excess48),sort:r=>r.excess48}])}
  <p class="note">"Move into trigger" is how far price had already travelled in the trade direction during the 24h before the signal. "vs drift" subtracts gold's average move over the same horizon (positive drift helps every long and hurts every short).</p></div>`;
}
function eventsAfter() {
  const E = D.event_paths;
  const draw = () => { const k = $("#ev_sel").value, p = E.paths[k], d = +k.split("|")[1];
    const drift = E.drift_long.map(v => v * d);
    plot("ev_chart", [
      {type:"scatter", mode:"lines", x:E.k, y:p.q75, line:{width:0}, showlegend:false, hoverinfo:"skip"},
      {type:"scatter", mode:"lines", x:E.k, y:p.q25, line:{width:0}, fill:"tonexty", fillcolor:"rgba(166,124,0,0.15)", name:"25–75%", hoverinfo:"skip"},
      {type:"scatter", mode:"lines", x:E.k, y:p.mean, name:"mean", line:{width:2.5, color:css("--gold")}, hovertemplate:"h %{x}: %{y:+.2f} ATR<extra></extra>"},
      {type:"scatter", mode:"lines", x:E.k, y:drift, name:"drift", line:{width:1.5, dash:"dash", color:css("--muted")}}],
      {xaxis:{title:"hours from decision"}, yaxis:{title:"ATR in trade direction", zerolinecolor:css("--muted")},
       shapes:[{type:"line", x0:0, x1:0, yref:"paper", y0:0, y1:1, line:{color:css("--ink"), width:1, dash:"dot"}}]});
    plot("ev_wl", [p.win?{type:"scatter", mode:"lines", x:E.k, y:p.win, name:"winners", line:{width:2, color:css("--pos")}}:null,
      p.loss?{type:"scatter", mode:"lines", x:E.k, y:p.loss, name:"losers", line:{width:2, color:css("--neg")}}:null].filter(Boolean),
      {xaxis:{title:"hours from decision"}, yaxis:{title:"ATR in trade direction", zerolinecolor:css("--muted")},
       shapes:[{type:"line", x0:0, x1:0, yref:"paper", y0:0, y1:1, line:{color:css("--ink"), width:1, dash:"dot"}}]}); };
  $("#ev_sel").onchange = draw; draw();
}

function behaviour() {
  const a = D.asymmetry;
  return `<h2>Why price behaves this way</h2>
  <p class="lead">Market-level measurements that explain the setup results. Forward moves are in H1 ATR. "Excess" removes gold's average upward drift over the same horizon.</p>
  <div class="grid">
    <div class="panel"><h3>Momentum persistence: next 12h vs. last 6h</h3><div class="row"><select id="mom_sel"><option>mom6</option><option>mom1</option><option>mom24</option></select></div><div id="mom_chart" class="chart"></div>
      <p class="note">Bars above zero mean the past move continued (beyond drift); below zero mean it reverted.</p></div>
    <div class="panel"><h3>Up-moves vs. down-moves</h3>${table(a.after_strong_moves, [
      {label:"Move > ATR",num:1,k:"threshold_atr"},{label:"Side",k:"side"},{label:"n",num:1,k:"n"},
      {label:"Excess cont.",num:1,f:r=>sgn(r.excess_continuation_atr),cls:r=>cls(r.excess_continuation_atr)},
      {label:"P(continue)",num:1,f:r=>pct(r.p_continue)},{label:"Fwd adverse",num:1,f:r=>num(r.fwd_adverse12,2)},{label:"Fwd favourable",num:1,f:r=>num(r.fwd_favourable12,2)}])}
      <p class="note">Avg up-bar body ${num(a.avg_up_bar_atr,3)} ATR vs down-bar ${num(a.avg_down_bar_atr,3)} ATR; ${pct(a.share_big_bars_down)} of >2 ATR bars are down bars.</p>
      <h3>Exhaustion states (RSI extreme + 2.5 ATR from EMA20)</h3>${table(a.exhaustion, [
      {label:"State",k:"state"},{label:"n",num:1,k:"n"},{label:"Reversion (ATR)",num:1,f:r=>sgn(r.reversion_atr),cls:r=>cls(r.reversion_atr)},{label:"P(revert)",num:1,f:r=>pct(r.p_revert)}])}</div>
  </div>
  <div class="panel"><h3>Market regimes (daily, causal classification)</h3><div id="reg_chart" class="chart" style="min-height:360px"></div></div>
  <div class="panel"><h3>Setup expectancy by daily trend regime</h3><div id="sr_heat" class="chart" style="min-height:440px"></div></div>`;
}
function behaviourAfter() {
  const m = () => { const rows = D.momentum[$("#mom_sel").value];
    plot("mom_chart", [{type:"bar", x:rows.map(r=>r.bin), y:rows.map(r=>r.excess_continuation), marker:{color:rows.map(r=>r.excess_continuation>0?css("--pos"):css("--neg"))},
      customdata:rows.map(r=>[r.n, r.p_continue]), hovertemplate:"past %{x}: %{y:+.3f} ATR excess · n=%{customdata[0]}<extra></extra>"}],
      {xaxis:{title:"past move (ATR)"}, yaxis:{title:"excess continuation (ATR)", gridcolor:css("--line"), zerolinecolor:css("--muted")}}); };
  $("#mom_sel").onchange = m; m();
  const rs = D.regime_series, colors = {bull:css("--pos"), bear:css("--neg"), neutral:css("--mid"), unknown:css("--line")};
  const traces = ["bull","bear","neutral"].map(g => ({type:"scattergl", mode:"markers", name:g, x:rs.t, y:rs.close.map((c,i)=>rs.regime[i]===g?c:null), marker:{size:3,color:colors[g]}}));
  plot("reg_chart", traces, {yaxis:{type:"log", title:"XAUUSD (log)", gridcolor:css("--line")}});
  const sr = D.setup_regime, setups = [...new Set(sr.map(r=>r.setup))], regs = ["bull","neutral","bear"];
  plot("sr_heat", [{type:"heatmap", x:regs, y:setups, z:setups.map(s=>regs.map(g=>{const r=sr.find(x=>x.setup===s&&x.regime_trend===g); return r?r.mean:null;})), zmid:0,
    colorscale:[[0,css("--neg")],[0.5,css("--panel")],[1,css("--pos")]], hovertemplate:"%{y} in %{x}: %{z:+.3f}R<extra></extra>"}], {margin:{l:150,r:10,t:10,b:36}});
}

function discoveries() {
  const ds = D.discoveries || [];
  if (!ds.length) return `<h2>Discoveries</h2><p class="lead">No hypothesis has survived discovery and validation yet. Run more experiments: <span class="mono">python -m edgelab experiment --budget 200</span>.</p>`;
  return `<h2>Discoveries</h2><p class="lead">Hypotheses that survived the discovery gate and were scored on validation, and on holdout only if validation passed. Each card carries the ten required fields. Status and evidence score (0–100) weigh in-sample strength, replication, regime stability and the deflated Sharpe ratio, which accounts for ${D.experiments.n_trials_total.toLocaleString()} trials.</p>
  ${ds.map((d,i) => {
    const s = d.by_split, o = d.out_of_sample;
    return `<article class="disc"><header>${statusPill(d.status)}<b class="mono">${esc(d.hyp_id)}</b><span class="pill">evidence ${num(d.evidence_score,0)}</span><span class="note">origin: ${esc(d.spec.origin)}</span></header>
    <div class="def">1 · ${esc(d.definition)}</div>
    ${(d.caveats||[]).map(c=>`<div class="callout note"><b>Caveat:</b> ${esc(c)}</div>`).join("")}<p class="note" style="margin:0">${esc(d.spec.rationale||"")}</p>
    ${d.holdout_revealed?"":'<p class="note" style="margin:0">Holdout withheld: this hypothesis did not pass validation, so it never earned its one look at 2022–2026.</p>'}
    ${table(["archive","discovery","validation","holdout"].filter(k=>s[k]).map(k=>({k, ...(s[k]||{})})), [
      {label:"Split",k:"k"},{label:"4 · n",num:1,k:"n"},{label:"5 · Win",num:1,f:r=>pct(r.win)},{label:"6 · Avg R",num:1,f:r=>sgn(r.avg_r),cls:r=>cls(r.avg_r)},
      {label:"7 · EV R",num:1,f:r=>sgn(r.ev)},{label:"8 · Max DD R",num:1,f:r=>num(r.max_dd,1)},{label:"t",num:1,f:r=>num(r.t,2)},
      {label:"Lift vs base",num:1,f:r=>sgn(r.lift_r)},{label:"DSR",num:1,f:r=>num(r.dsr,2)}])}
    <div class="grid"><div><h3>9 · Regimes</h3>${table((d.regimes||[]).filter(r=>r.dimension!=="session"), [{label:"Dim",k:"dimension"},{label:"Regime",k:"regime"},{label:"n",num:1,k:"n"},{label:"Avg R",num:1,f:r=>sgn(r.avg_r),cls:r=>cls(r.avg_r)}])}</div>
    <div><h3>10 · Out-of-sample (${d.holdout_revealed?"validation + holdout":"validation only"})</h3><dl class="kv"><dt>n</dt><dd>${o.n}</dd><dt>avg R</dt><dd class="${cls(o.avg_r)}">${sgn(o.avg_r)}</dd><dt>block-bootstrap 95% CI</dt><dd>[${num(d.oos_bootstrap_ci[0])}, ${num(d.oos_bootstrap_ci[1])}]</dd><dt>max DD</dt><dd>${num(o.max_dd,1)}R</dd><dt>trials at test</dt><dd>${d.n_trials_at_test}</dd></dl>
    <h3 style="margin-top:10px">2 · Examples / 3 · counterexamples</h3><p class="mono">${(d.examples||[]).map(x=>`<a href="#inspector" data-tid="${x}">${x}</a>`).join(" ")}</p><p class="mono">${(d.counterexamples||[]).map(x=>`<a href="#inspector" data-tid="${x}">${x}</a>`).join(" ")}</p>
    ${stressHtml(d.stress)}
    ${(d.relations||[]).map(r=>`<p class="note">⟂ ${esc(r.type)}${r.with?" with "+esc(r.with):""}: ${esc(r.note)}</p>`).join("")}</div>
    <div><h3>Equity (R)</h3><div id="deq${i}" style="min-height:200px"></div></div></div></article>`;}).join("")}`;
}
function stressHtml(st) {
  if (!st || st.error) return "";
  const pill = st.robust ? '<span class="pill good">passes stress tests</span>' : st.flags.map(f=>`<span class="pill crit">${esc(f)}</span>`).join(" ");
  return `<h3 style="margin-top:10px">Stress (${esc(st.allowed_splits.join(" + "))})</h3><div class="row">${pill}</div>
   <dl class="kv"><dt>threshold shifts still positive</dt><dd>${st.neighbourhood_positive_share==null?"n/a (no thresholds)":pct(st.neighbourhood_positive_share)}</dd>
   <dt>break-even cost multiple</dt><dd>${num(st.breakeven_cost_mult,2)}x</dd><dt>years positive</dt><dd>${pct(st.years_positive_share)} of ${st.n_years}</dd>
   <dt>95% reshuffled max DD</dt><dd>${num(st.mc_dd_95,1)}R</dd>
   <dt>excess vs same-month benchmark</dt><dd>${sgn(st.month_matched_excess)}R (${Object.entries(st.month_matched_excess_by_split||{}).map(([k,v])=>k+" "+sgn(v)).join(", ")})</dd>
   <dt>by daily trend regime</dt><dd>${Object.entries(st.by_trend_regime||{}).map(([k,v])=>k+" "+sgn(v)).join(" · ")}</dd></dl>`;
}
function discoveriesAfter() {
  (D.discoveries||[]).forEach((d,i) => plot("deq"+i, [{type:"scatter",mode:"lines",x:d.equity.map(e=>e.t),y:d.equity.map(e=>e.r),line:{color:css("--gold"),width:2}}], {margin:{l:40,r:8,t:8,b:30}, showlegend:false}));
  document.querySelectorAll("a[data-tid]").forEach(a => a.onclick = () => { R.pendingTrade = a.dataset.tid; });
}

function experiments() {
  const e = D.experiments;
  return `<h2>Experiment ledger</h2>
  <p class="lead">Append-only. ${e.n_records} records over ${e.n_hypotheses} hypotheses. Nothing is deleted; failed hypotheses count toward the ${e.n_trials_total.toLocaleString()}-trial multiple-testing denominator.</p>
  <div class="kpis">${Object.entries(e.status_counts).map(([k,v])=>`<div class="kpi"><small>${statusPill(k)}</small><b>${v}</b></div>`).join("")}</div>
  ${rcPanel()}
  <div class="panel"><h3>Forward test (data after each hypothesis was frozen)</h3>${(D.forward||[]).length ? table(D.forward, [
    {label:"Hypothesis",k:"definition"},{label:"Frozen at",f:r=>String(r.frozen_at).slice(0,16)},{label:"n",num:1,f:r=>r.forward?r.forward.n:"–"},
    {label:"Avg R",num:1,f:r=>r.forward?sgn(r.forward.avg_r):"–",cls:r=>r.forward?cls(r.forward.avg_r):""}]) : '<p class="note">Nothing frozen yet.</p>'}
    <p class="note">The only truly unseen data. Hypotheses are frozen at the last bar of the current data; refresh the price files and rerun to score them.</p></div>
  <div class="panel"><h3>Next experiments proposed by the engine</h3>${table(e.next, [{label:"Priority",num:1,f:r=>num(r.priority,0)},{label:"Origin",k:"origin"},{label:"Hypothesis",k:"description"},{label:"Why",k:"rationale"}])}</div>
  <div class="row"><label for="lg_q">Filter</label><input id="lg_q" placeholder="setup, status, feature…" size="30"></div>
  <div class="panel" id="lg_tbl"></div>`;
}
function rcPanel() {
  const rc = D.reality_check; if (!rc || !rc.n_hypotheses) return "";
  const sp = D.scan_pairs || {};
  return `<div class="panel"><h3>Data-snooping controls</h3><dl class="kv">
    <dt>White's Reality Check (family)</dt><dd>${rc.n_hypotheses} hypotheses × ${rc.n_days} discovery days · p = ${num(rc.p_reality_check,3)} (raw), ${num(rc.p_studentised,3)} (studentised)</dd>
    <dt>Best hypothesis in family</dt><dd>${esc(rc.best)} · t = ${num(rc.best_t,2)} vs 95% luck threshold ${num(rc.boot_tmax_95,2)}</dd>
    <dt>Romano-Wolf survivors (FWER 5%)</dt><dd>${(rc.rw_survivors||[]).length ? rc.rw_survivors.map(esc).join("<br>") : "none"}</dd>
    <dt>Single-feature scan</dt><dd>${D.scan.cells} cells · ${D.scan.observed_p05} at p&lt;0.05 vs ${Math.round(D.scan.expected_false_at_p05)} expected by chance</dd>
    <dt>Two-feature interaction scan</dt><dd>${sp.cells||0} cells · ${sp.observed_p05||0} at p&lt;0.05 · FDR survivors ${sp.fdr_survivors||0}. Pairs are built from the best single cells on the same data, so a chance baseline does not apply; they are counted as trials and judged by the Reality Check and later splits.</dd></dl>
    <p class="note">Stationary block bootstrap of daily R (mean block 10 days), centred under "no edge". It asks whether the best result is better than the best of the same number of zero-edge strategies would be by luck.</p></div>`;
}
function experimentsAfter() {
  const draw = () => { const q = $("#lg_q").value.toLowerCase();
    const rows = D.ledger.filter(r => !q || JSON.stringify(r).toLowerCase().includes(q)).slice().reverse();
    $("#lg_tbl").innerHTML = table(rows, [{label:"Hyp",k:"hyp_id"},{label:"Split",k:"split"},{label:"Status",html:1,f:r=>statusPill(r.status)},
      {label:"Origin",k:"origin"},{label:"Hypothesis",k:"description"},{label:"n",num:1,k:"n"},{label:"Win",num:1,f:r=>pct(r.win)},
      {label:"Avg R",num:1,f:r=>sgn(r.avg_r),cls:r=>cls(r.avg_r),sort:r=>r.avg_r},{label:"t",num:1,f:r=>num(r.t,2)},{label:"Lift",num:1,f:r=>sgn(r.lift_r)},{label:"DSR",num:1,f:r=>num(r.dsr,2)}]); };
  $("#lg_q").oninput = draw; draw();
}

function profile() {
  const P = D.profile;
  const src = P.source === "personal" ? `<p class="lead">Profile built from ${P.n} of your own trades.</p>` :
   `<div class="callout"><b>No personal trade file found.</b> These tests run on the lab's ${P.n.toLocaleString()} mechanical trades. That makes them a <i>market baseline</i>: a personal edge has to beat these numbers to count as skill. Add your history at <span class="mono">edgelab/store/my_trades.csv</span> (template below) and rerun.</div>`;
  return `<h2>Edge profile: testing the self-assessment</h2>${src}
  <div class="panel">${table(P.tests, [{label:"Claim",f:r=>`<b>${esc(r.id)}</b> ${esc(r.claim)}`,html:1},{label:"How it is falsified",k:"test"},
    {label:"Verdict",html:1,f:r=>r.verdict==="supported"?'<span class="pill good">supported</span>':(r.verdict.startsWith("insuff")?'<span class="pill muted">'+r.verdict+'</span>':'<span class="pill crit">'+r.verdict+'</span>')},
    {label:"Key evidence",f:r=>evidence(r),html:1}])}</div>
  <div class="grid">
    <div class="panel"><h3>Long vs. short by setup (all later splits)</h3>${table(D.side_profile, [{label:"Setup",k:"setup"},{label:"Long R",num:1,f:r=>sgn(r.avg_r_long),cls:r=>cls(r.avg_r_long)},
      {label:"Short R",num:1,f:r=>sgn(r.avg_r_short),cls:r=>cls(r.avg_r_short)},{label:"Short−Long",num:1,f:r=>sgn(r.short_minus_long),sort:r=>r.short_minus_long},
      {label:"Min to MFE L/S",num:1,f:r=>num(r.minutes_to_mfe_long,0)+" / "+num(r.minutes_to_mfe_short,0)},{label:"p",num:1,f:r=>num(r.p_value,3)}])}</div>
    <div class="panel"><h3>Why good-looking sells lose</h3>${table(P.why_sells_lose||[], [{label:"Category",f:r=>r.id+" "+r.name},{label:"Phase",k:"phase"},
      {label:"Losing shorts",num:1,f:r=>pct(r.freq_losing_shorts)},{label:"Winning shorts",num:1,f:r=>pct(r.freq_winning_shorts)},{label:"Lift",num:1,f:r=>sgn(r.lift),sort:r=>r.lift}])}
      <p class="note">Ex-post categories describe losers by construction; the ex-ante rows are the ones a filter could use.</p></div>
  </div>
  ${P.template?`<div class="panel"><h3>Personal trades CSV template</h3><pre class="mono" style="overflow-x:auto;margin:0">${esc(P.template)}</pre></div>`:""}`;
}
function evidence(r) {
  const e = r.evidence || {};
  const f = s => s && s.n !== undefined ? `n=${s.n} avg ${sgn(s.avg_r)}R` : "";
  switch (r.id) {
    case "SA1": return `short ${f(e.short)} · long ${f(e.long)} · diff CI [${num(e.ci&&e.ci[0])}, ${num(e.ci&&e.ci[1])}]`;
    case "SA2": return `gap ${sgn(e.total_gap)}R: regime mix ${sgn(e.composition_effect)}R, within-regime ${sgn(e.within_regime_effect)}R`;
    case "SA3": return `with momentum ${f(e.short_with_momentum)} · against ${f(e.short_against_momentum)}`;
    case "SA4": return `fades ${f(e.fades)} · long fades ${f(e.by_side&&e.by_side.long)} · short fades ${f(e.by_side&&e.by_side.short)}`;
    case "SA5": return e.short_timing_alpha!==undefined ? `timing alpha short ${sgn(e.short_timing_alpha)}R, long ${sgn(e.long_timing_alpha)}R` : `MAE short ${num(e.short_mae,2)}R vs long ${num(e.long_mae,2)}R`;
    case "SA6": return `continuation ${f(e.continuation)} · reversal ${f(e.reversal)}`;
  }
  return "";
}

function inspector() {
  const tr = D.inspect;
  const setups = [...new Set(tr.map(t=>t.setup))].sort();
  return `<h2>Trade inspector</h2>
  <p class="lead">${tr.length} sampled trades (winners and losers from every setup, plus discovery examples). Choose one to see the chart as it was, the decision context, every mistake flag with its tested verdict, and all counterfactual outcomes.</p>
  <div class="row">
    <select id="in_setup"><option value="">all setups</option>${setups.map(s=>`<option>${s}</option>`).join("")}</select>
    <select id="in_out"><option value="">wins & losses</option><option value="w">winners</option><option value="l">losers</option></select>
    <select id="in_trade" style="min-width:0;flex:1 1 260px"></select>
  </div>
  <div class="grid" style="grid-template-columns:minmax(0,2fr) minmax(280px,1fr)">
    <div class="panel"><div id="in_chart" class="chart" style="min-height:440px"></div></div>
    <div class="panel" id="in_side"></div>
  </div>
  <div class="grid"><div class="panel" id="in_flags"></div><div class="panel"><h3>Counterfactual outcomes (base R)</h3><div id="in_cf" class="chart" style="min-height:360px"></div></div></div>`;
}
function inspectorAfter() {
  const fill = () => { const s = $("#in_setup").value, o = $("#in_out").value;
    const list = D.inspect.filter(t => (!s || t.setup===s) && (!o || (o==="w" ? t.r>0 : t.r<=0)));
    $("#in_trade").innerHTML = list.map(t => `<option value="${t.trade_id}">${t.trade_id} · ${t.setup} ${dirName(t.direction)} · ${sgn(t.r,2)}R · ${t.split}</option>`).join("");
    if (R.pendingTrade && list.some(t=>t.trade_id===R.pendingTrade)) $("#in_trade").value = R.pendingTrade;
    R.pendingTrade = null; show(); };
  $("#in_setup").onchange = fill; $("#in_out").onchange = fill; $("#in_trade").onchange = show; fill();
}
function grade(t) {
  const good = t.quality === "above", win = t.r > 0;
  if (t.quality === "unscored") return ["Unscored", "muted", "Before the first walk-forward year; no out-of-sample quality score."];
  if (good && win) return ["Good decision, good outcome","good","The model trained only on earlier years rated this above that year's median, and it worked."];
  if (good && !win) return ["Good decision, bad outcome","warn","Above-median ex-ante quality; the loss is consistent with normal variance. Do not 'fix' this trade."];
  if (!good && win) return ["Poor decision, lucky outcome","warn","Below-median ex-ante quality; the win does not validate the decision."];
  return ["Poor decision, bad outcome","crit","Below-median ex-ante quality and it lost: the avoidable kind of loss."];
}
function show() {
  const id = $("#in_trade").value; const t = D.inspect.find(x => x.trade_id === id); if (!t) return;
  const b = t.bars, x = b.map(r=>r[0]);
  const shapes = [], ann = [];
  const hr = v => String(v).slice(0,13) + ":00";   /* snap M15 fill/exit times onto their H1 candle */
  const t0 = hr(t.fill_time), t1 = hr(t.exit_time), dec = hr(t.tc);
  const line = (y, color, dash, name) => { shapes.push({type:"line", xref:"x", x0:t0, x1:t1, y0:y, y1:y, line:{color, width:1.5, dash}}); ann.push({x:t1, y, text:name, showarrow:false, xanchor:"left", font:{size:10,color}}); };
  line(t.entry, css("--ink"), "solid", "entry"); line(t.stop_px, css("--neg"), "dot", "stop"); line(t.target_px, css("--pos"), "dot", "target");
  shapes.push({type:"line", xref:"x", yref:"paper", x0:dec, x1:dec, y0:0, y1:1, line:{color:css("--gold"), width:1, dash:"dash"}});
  ann.push({x:dec, yref:"paper", y:1.02, text:"decision", showarrow:false, font:{size:10,color:css("--gold")}});
  plot("in_chart", [
    {type:"candlestick", x, open:b.map(r=>r[1]), high:b.map(r=>r[2]), low:b.map(r=>r[3]), close:b.map(r=>r[4]), name:"H1",
     increasing:{line:{color:css("--pos")}}, decreasing:{line:{color:css("--neg")}}},
    {type:"scatter", mode:"lines", x, y:t.ema20, name:"EMA20", line:{width:1, color:css("--gold")}},
    {type:"scatter", mode:"lines", x, y:t.bb_up, name:"BB", line:{width:1, color:css("--mid"), dash:"dot"}},
    {type:"scatter", mode:"lines", x, y:t.bb_lo, name:"BB lo", showlegend:false, line:{width:1, color:css("--mid"), dash:"dot"}},
    {type:"scatter", mode:"markers", x:[t0, t1], y:[t.entry, t.exit], name:"fill / exit", marker:{size:10, symbol:[+t.direction>0?"triangle-up":"triangle-down","x"], color:[css("--ink"), t.r>0?css("--pos"):css("--neg")], line:{width:2,color:css("--panel")}}},
  ], {xaxis:{type:"category", rangeslider:{visible:false}, nticks:8, tickfont:{size:10,color:css("--muted")}}, shapes, annotations:ann, margin:{l:56,r:50,t:30,b:40}});
  const g = grade(t);
  $("#in_side").innerHTML = `<h3>${esc(t.trade_id)}</h3>
    <div class="row"><span class="pill ${g[1]}">${g[0]}</span><span class="pill">${esc(t.split)}</span></div><p class="note" style="margin:0">${g[2]}</p>
    <dl class="kv"><dt>Setup</dt><dd>${esc(t.setup)} ${dirName(t.direction)}</dd><dt>Outcome</dt><dd class="${cls(t.r)}">${sgn(t.r,2)}R net (${sgn(t.r_gross,2)} gross, costs ${num(t.cost_r,2)}) · ${esc(t.exit_reason)}</dd>
    <dt>MFE / MAE</dt><dd>${num(t.mfe_r,2)}R / ${num(t.mae_r,2)}R</dd><dt>After exit (24h)</dt><dd>${t.post_hit_target?"reached target":"did not reach target"} · fav ${num(t.post_mfe_r,1)}R · adv ${num(t.post_mae_r,1)}R</dd>
    <dt>ML p(win), OOS</dt><dd>${num(t.ml_p,3)}</dd><dt>Regime / session</dt><dd>${esc(t.regime)} · ${esc(t.session)}</dd>
    <dt>Stop</dt><dd>${num(t.stop_atr,2)} ATR</dd><dt>Momentum 6h / 24h</dt><dd>${sgn(t.rel_mom6,2)} / ${sgn(t.rel_mom24,2)} ATR (trade-relative)</dd>
    <dt>Stretch vs daily EMA50</dt><dd>${sgn(t.rel_d_ext,2)} daily ATR</dd><dt>ADX / ER30</dt><dd>${num(t.adx,1)} / ${num(t.er30,2)}</dd>
    <dt>Vol percentile</dt><dd>${pct(t.atr_pct)}</dd><dt>Room to level</dt><dd>${num(t.room_in_r,2)}R</dd><dt>TF votes (with trade)</dt><dd>${sgn(t.rel_mtf_votes,0)}</dd></dl>`;
  const ex = t.flags.filter(f=>f.phase==="ex_ante"), post = t.flags.filter(f=>f.phase!=="ex_ante");
  const fl = f => { const k = (f.verdict||"").startsWith("confirmed") ? "crit" : ((f.verdict||"").startsWith("CONTRA") ? "good" : (f.phase!=="ex_ante"?"post":""));
    return `<div class="flag ${k}"><b>${esc(f.id)} · ${esc(f.name)}</b> ${f.verdict?verdictPill(f.verdict):""}<br><span class="note">${esc(f.text)}${f.delta_r!=null?` · tested ΔR ${sgn(f.delta_r)}`:""}</span></div>`; };
  $("#in_flags").innerHTML = `<h3>What was visible before entry (${ex.length})</h3>${ex.map(fl).join("")||'<p class="note">No ex-ante flags.</p>'}
    <h3 style="margin-top:8px">What went wrong / right afterwards (${post.length})</h3>${post.map(fl).join("")||'<p class="note">No ex-post diagnoses.</p>'}`;
  const vs = Object.keys(D.variants).filter(v => t.cf[v] !== undefined && t.cf[v] !== null);
  plot("in_cf", [{type:"bar", orientation:"h", y:vs, x:vs.map(v=>t.cf[v]), marker:{color:vs.map(v=>v==="base"?css("--gold"):(t.cf[v]>0?css("--pos"):css("--neg")))},
    hovertemplate:"%{y}: %{x:+.2f}R<extra></extra>"}], {margin:{l:120,r:10,t:10,b:36}, yaxis:{autorange:"reversed"}});
}

const VIEWS = {overview:[overview,overviewAfter], setups:[setups,setupsAfter], mistakes:[mistakes,mistakesAfter],
  counterfactuals:[counterfactuals,counterfactualsAfter], lookalikes:[lookalikes,null], behaviour:[behaviour,behaviourAfter],
  discoveries:[discoveries,discoveriesAfter], experiments:[experiments,experimentsAfter], profile:[profile,null], inspector:[inspector,inspectorAfter]};
function route() {
  const id = (location.hash||"#overview").slice(1); const key = VIEWS[id] ? id : "overview";
  $("#tabs").innerHTML = TABS.map(([k,l]) => `<a href="#${k}" class="${k===key?'on':''}">${l}</a>`).join("");
  $("#main").innerHTML = `<section>${VIEWS[key][0]()}</section>`;
  if (VIEWS[key][1]) VIEWS[key][1]();
  try { localStorage.setItem("edgelab_tab", key); } catch(e) {}
}
window.addEventListener("hashchange", route);
if (window.matchMedia) matchMedia("(prefers-color-scheme: dark)").addEventListener("change", route);
new MutationObserver(route).observe(document.documentElement, {attributes:true, attributeFilter:["data-theme"]});
$("#subtitle").textContent += ` Generated ${D.generated}.`;
route();
</script>
"""
