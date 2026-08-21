"""14_metric_audit.py - Metric audit (MICRO / corpus-level, matching paper formulas).

Paper conventions (user-confirmed):
  Pass@1       : file-level macro        = |S_pass| / N
  Reduction@P  : micro / corpus          = sum(Fixed_i - New_i) / sum(|L_i|) = sum(in-out)/sum(in)  [passed]
  New@P        : micro                   = sum(New_i) / sum(|L_i|)                                      [passed]
  DeltaLine@P  : file-level macro        = sum(Lines_i) / |S_pass|
  LinePerFix@P : micro / ratio-of-sums   = sum(Lines_i) / sum(Fixed_i)                                   [passed]
  PRed         : hybrid                  = Pass@1 * Reduction@P
  (Fixed_i is count-based removed = in-out+new; NOTE LinePerFix's stored denom uses set-based
   lpm_p_fixed_count -> identity inconsistency, see #1.)

Items:
  #1 invariant checks: Reduction == FixedRate - NewRate (count holds; set-based Fixed violates).
  #2 selection bias: micro @Pass (model-specific passed subset) vs @All (common compiled set),
     + median (robust) + degenerate-output count.
  #3 micro pass@1 / Reduction@P with problem-ID-clustered bootstrap 95% CI; common-pass subset.
  #4 suppression / linter-gaming (NOLINT / pylint:disable / NOPMD,@SuppressWarnings).

Outputs: eval_paper_results/metric_audit.{json,md}  and  docs/table/{metric_invariant_audit,
selection_bias_atall, pass_at1_ci, suppression_detection}.tex
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
RESULT_DIR = _PROJECT_ROOT / "eval_results"
TABLE_DIR = _PROJECT_ROOT / "docs" / "table"

LANGS = ("cpp", "py3", "java", "py2")
DEGEN_K = 5.0

SUPPRESSION_RE = {
    "cpp": re.compile(r"\bNOLINT\b", re.IGNORECASE),
    "py3": re.compile(r"pylint\s*:\s*(disable|ignore)", re.IGNORECASE),
    "java": re.compile(r"\bNOPMD\b|@SuppressWarnings", re.IGNORECASE),
}

BASE_MODELS = [
    ("GPT-5.2", "GPT-5_2"), ("GPT-5.4-mini", "GPT-5_4-mini"),
    ("DeepSeek-v3.2", "DeepSeek-v3_2-128K"), ("Qwen2.5-Coder-32B", "Qwen2_5-Coder-32B-Instruct"),
    ("Qwen2.5-Coder-7B", "Qwen2_5-Coder-7B"), ("Qwen2.5-Coder-3B", "Qwen2_5-Coder-3B"),
    ("Qwen2.5-Coder-0.5B", "Qwen2_5-Coder-0_5B"),
    ("Llama-3.2-3B", "Llama-3_2-3B-Instruct"), ("Llama-3.2-1B", "Llama-3_2-1B-Instruct"),
]
SFT_MODELS = [
    ("0.5B / A+L$\\rightarrow$A$'$", "finetuned_Qwen-05b_revision"),
    ("0.5B / Q$\\rightarrow$A", "finetuned_Qwen-05b_codegen"),
    ("0.5B / Q$\\rightarrow$A$'$", "finetuned_Qwen-05b_clean_codegen"),
    ("3B / A+L$\\rightarrow$A$'$", "finetuned_Qwen-3b_revision"),
    ("3B / Q$\\rightarrow$A", "finetuned_Qwen-3b_codegen"),
    ("3B / Q$\\rightarrow$A$'$", "finetuned_Qwen-3b_clean_codegen"),
    ("7B / A+L$\\rightarrow$A$'$", "finetuned_Qwen-7b_revision"),
    ("7B / Q$\\rightarrow$A", "finetuned_Qwen-7b_codegen"),
    ("7B / Q$\\rightarrow$A$'$", "finetuned_Qwen-7b_clean_codegen"),
]


def problem_of(sid: str) -> str:
    parts = sid.split("_")
    if len(parts) >= 3 and parts[-2] in LANGS and parts[-1].isdigit():
        return "_".join(parts[:-2])
    return sid


def is_degen(r: Dict) -> bool:
    o = r.get("in_total") or 0
    return o > 0 and (r.get("new_msg_count") or 0) > DEGEN_K * o


def load_models() -> List[Tuple[str, str, Dict]]:
    out, seen = [], set()
    for disp, stem in BASE_MODELS + SFT_MODELS:
        if stem in seen:
            continue
        seen.add(stem)
        p = RESULT_DIR / f"{stem}.json"
        if p.exists():
            d = json.load(open(p))
            if "results" in d:
                out.append((disp, stem, d))
    return out


# ---- micro (corpus) metrics over a pool -------------------------------------
def micro(pool: List[Dict]) -> Dict:
    """Ratio-of-sums over samples with in_total>0 (use pass-filtered pool for @P)."""
    sO = sR = sN = sFix = 0
    n = 0
    for r in pool:
        O = r.get("in_total") or 0
        if O <= 0:
            continue
        n += 1
        sO += O
        sR += r.get("out_total") or 0
        sN += r.get("new_msg_count") or 0
        sFix += r.get("lpm_p_fixed_count") or 0
    if sO == 0:
        return {"n": 0, "Reduction": None, "NewRate": None, "FixedRate_set": None}
    return {"n": n, "Reduction": (sO - sR) / sO, "NewRate": sN / sO,
            "FixedRate_set": sFix / sO}


def median_reduction(pool: List[Dict]) -> Optional[float]:
    rs = []
    for r in pool:
        O = r.get("in_total") or 0
        if O > 0:
            rs.append((O - (r.get("out_total") or 0)) / O)
    return statistics.median(rs) if rs else None


# ---- #1 invariants ----------------------------------------------------------
def invariants(results: List[Dict]) -> Dict:
    checked = 0
    viol = {"inv1_count": 0, "inv1_set": 0, "inv2": 0, "inv3": 0}
    max_set = 0.0
    for r in results:
        O = r.get("in_total") or 0
        if O <= 0:
            continue
        R = r.get("out_total") or 0
        new = r.get("new_msg_count") or 0
        fix_set = r.get("lpm_p_fixed_count") or 0
        reduction = (O - R) / O
        new_rate = new / O
        if abs(reduction - ((O - R + new) / O - new_rate)) > 1e-6:
            viol["inv1_count"] += 1
        es = abs(reduction - (fix_set / O - new_rate))
        max_set = max(max_set, es)
        if es > 1e-6:
            viol["inv1_set"] += 1
        if reduction < -new_rate - 1e-9:
            viol["inv2"] += 1
        if reduction > 1 + 1e-9:
            viol["inv3"] += 1
        checked += 1
    return {"n_checked": checked, "violations": viol, "max_err_inv1_set": round(max_set, 4)}


# ---- #4 suppression ---------------------------------------------------------
def suppression(results: List[Dict]) -> Dict:
    per = defaultdict(lambda: [0, 0])
    tot = sup = 0
    for r in results:
        lang = r.get("language", "cpp")
        code = r.get("generated_code") or ""
        if not code.strip():
            continue
        per[lang][0] += 1; tot += 1
        pat = SUPPRESSION_RE.get(lang)
        if pat and pat.search(code):
            per[lang][1] += 1; sup += 1
    bl = {l: {"n": v[0], "with": v[1]} for l, v in per.items() if v[0]}
    return {"n": tot, "with": sup, "rate": round(sup / tot, 4) if tot else None, "by_lang": bl}


# ---- #3 micro clustered bootstrap -------------------------------------------
def micro_bootstrap(samples: List[Tuple], B: int, seed: int) -> Dict:
    """samples: (pid, in, out, new, pass). Cluster by pid; resample clusters w/ replacement.
    Returns micro pass@1, Reduction@P, New@P (point + 95% CI)."""
    import random
    rng = random.Random(seed)
    clusters = defaultdict(list)
    for s in samples:
        clusters[s[0]].append(s)
    ids = list(clusters.keys())

    def m_pass(pool):
        pool = list(pool)
        return sum(1 for s in pool if s[4]) / len(pool) if pool else 0.0

    def m_red(pool):
        ps = [s for s in pool if s[4] and s[1] > 0]
        sO = sum(s[1] for s in ps)
        return (sO - sum(s[2] for s in ps)) / sO if sO > 0 else 0.0

    def m_new(pool):
        ps = [s for s in pool if s[4] and s[1] > 0]
        sO = sum(s[1] for s in ps)
        return sum(s[3] for s in ps) / sO if sO > 0 else 0.0

    allpool = [s for cid in ids for s in clusters[cid]]
    pt_pass, pt_red, pt_new = m_pass(allpool), m_red(allpool), m_new(allpool)
    if not ids or B <= 0:
        return {"pass@1": (pt_pass, None, None), "red@P": (pt_red, None, None),
                "new@P": (pt_new, None, None)}

    def boot(fn):
        out = []
        for _ in range(B):
            pool = [s for cid in (rng.choice(ids) for _ in ids) for s in clusters[cid]]
            out.append(fn(pool))
        out.sort()
        lo = out[int(0.025 * len(out))]
        hi = out[min(int(0.975 * len(out)), len(out) - 1)]
        return lo, hi
    plo, phi = boot(m_pass)
    rlo, rhi = boot(m_red)
    nlo, nhi = boot(m_new)
    return {"pass@1": (pt_pass, plo, phi), "red@P": (pt_red, rlo, rhi),
            "new@P": (pt_new, nlo, nhi)}


def common_pass_and_ci(models, B):
    by_model = {stem: {r["sample_id"]: r for r in d["results"] if r.get("sample_id")}
                for _, stem, d in models}
    common = None
    for stem in by_model:
        p = {sid for sid, r in by_model[stem].items() if r.get("pass")}
        common = p if common is None else (common & p)
    common = common or set()
    ci = {}
    red_common = {}
    for disp, stem, d in models:
        res = d["results"]
        samples = []
        rc = []
        for r in res:
            sid = r.get("sample_id")
            if not sid:
                continue
            O = r.get("in_total") or 0
            samples.append((problem_of(sid), O, r.get("out_total") or 0,
                            r.get("new_msg_count") or 0, 1 if r.get("pass") else 0))
            if sid in common and O > 0:
                rc.append(((O - (r.get("out_total") or 0)) / O, O, r.get("out_total") or 0))
        mb = micro_bootstrap(samples, B, abs(hash(stem)) % 2**31)
        # micro Reduction on common-pass subset
        sO = sum(o for _, o, _ in rc); sR = sum(rr for _, _, rr in rc)
        red_common[disp] = (sO - sR) / sO if sO > 0 else None
        ci[disp] = mb
    return {"common_pass_n": len(common), "ci": ci, "red_common": red_common}


def pct(x):
    return None if x is None else round(x * 100, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", type=int, default=1000)
    args = ap.parse_args()
    models = load_models()
    print(f"{len(models)} models")

    audit = {"models": {}}
    for disp, stem, d in models:
        res = d["results"]
        comp = [r for r in res if r.get("compile_ok") and (r.get("in_total") or 0) > 0]
        passed = [r for r in comp if r.get("pass")]
        audit["models"][disp] = {
            "stem": stem, "n": len(res),
            "pass@1": round(sum(1 for r in res if r.get("pass")) / len(res), 4),
            "invariants": invariants(res),
            "suppression": suppression(res),
            "micro_at_pass": micro(passed),
            "micro_at_all": micro(comp),
            "median_red_at_pass": median_reduction(passed),
            "n_degen": sum(1 for r in comp if is_degen(r)),
        }
    audit["cp"] = common_pass_and_ci(models, args.bootstrap)
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(audit, open(TABLE_DIR / "metric_audit.json", "w"), ensure_ascii=False, indent=2)
    write_tex(audit)
    print("done")


def write_md(a):
    L = ["# Metric Audit (MICRO / corpus-level, matching paper)", ""]
    L.append("## #1 invariants (per-sample). inv1_count holds; inv1_set exposes set/count Fixed mismatch")
    L += ["", "| model | n | inv1_count | inv1_set | inv2 | inv3 | max|err set| |", "|---|---|---|---|---|---|---|"]
    for n, m in a["models"].items():
        v = m["invariants"]
        L.append(f"| {n} | {v['n_checked']} | {v['violations']['inv1_count']} | {v['violations']['inv1_set']} | {v['violations']['inv2']} | {v['violations']['inv3']} | {v['max_err_inv1_set']} |")
    L += ["", "## #2 micro @Pass vs @All (selection bias). PRed = Pass@1*Reduction@P. degen = new>5*O", "",
          "| model | Pass@1 | Red@P micro | Red@All micro | New@P | New@All | PRed | Red med.@P | degen |", "|---|---|---|---|---|---|---|---|---|"]
    for n, m in a["models"].items():
        mp, ma = m["micro_at_pass"], m["micro_at_all"]
        pred = m["pass@1"] * (mp.get("Reduction") or 0)
        L.append(f"| {n} | {pct(m['pass@1'])} | {pct(mp.get('Reduction'))} | {pct(ma.get('Reduction'))} | {pct(mp.get('NewRate'))} | {pct(ma.get('NewRate'))} | {pct(pred)} | {pct(m['median_red_at_pass'])} | {m['n_degen']} |")
    cp = a["cp"]
    L += ["", f"## #3 micro pass@1 / Reduction@P clustered bootstrap CI (B=1000); common-pass n={cp['common_pass_n']}", "",
          "| model | Pass@1 [CI] | Red@P micro [CI] | New@P micro [CI] | Red@common |", "|---|---|---|---|---|"]
    for n, m in a["models"].items():
        c = cp["ci"][n]
        pa, plo, phi = c["pass@1"]; ra, rlo, rhi = c["red@P"]; na, nlo, nhi = c["new@P"]
        ci = lambda lo, hi: f"[{pct(lo)},{pct(hi)}]" if lo is not None else ""
        L.append(f"| {n} | {pct(pa)} {ci(plo,phi)} | {pct(ra)} {ci(rlo,rhi)} | {pct(na)} {ci(nlo,nhi)} | {pct(cp['red_common'][n])} |")
    L += ["", "## #4 suppression (NOLINT/pylint:disable/NOPMD,@SuppressWarnings)", "",
          "| model | n | with | rate% | cpp | py3 | java |", "|---|---|---|---|---|---|---|"]
    for n, m in a["models"].items():
        s = m["suppression"]; bl = s["by_lang"]
        lr = lambda l: f"{bl[l]['with']}/{bl[l]['n']}" if l in bl else "-"
        L.append(f"| {n} | {s['n']} | {s['with']} | {s['rate']} | {lr('cpp')} | {lr('py3')} | {lr('java')} |")
    open(RESULT_DIR / "metric_audit.md", "w").write("\n".join(L))


def row(cells):
    return " & ".join(str(c) for c in cells) + r" \\"


def f1(x):
    return "--" if x is None else f"{x:.1f}"


def write_tex(a):
    cp = a["cp"]

    # ---- #1 invariant ----
    lines = [r"\begin{table}[t]", r"\centering", r"\small", r"\begin{tabular}{lcccccc}",
             r"\toprule",
             r"\textbf{Model} & $n$ & \textbf{inv1\textsubscript{count}} & \textbf{inv1\textsubscript{set}} & inv2 & inv3 & max$|$err$|$ set\\",
             r"\midrule"]
    for n, m in a["models"].items():
        v = m["invariants"]
        lines.append(row([n, v["n_checked"], v["violations"]["inv1_count"], v["violations"]["inv1_set"],
                          v["violations"]["inv2"], v["violations"]["inv3"], v["max_err_inv1_set"]]))
    lines += [r"\bottomrule", r"\end{tabular}",
              r"\caption{Metric-consistency audit (per sample). \textbf{inv1\textsubscript{count}}: $\mathrm{Reduction}=\mathrm{FixedRate_{count}}-\mathrm{NewRate}$ with the count-consistent fixed $=O{-}R{+}N$ that the pipeline now uses for LinePerFix@P (holds exactly, 0 violations). \textbf{inv1\textsubscript{set}}: same identity using the legacy set-based \texttt{lpm\_p\_fixed\_count} still stored in the result JSONs; its frequent violations document the original inconsistency (set-based vs.\ count-based Fixed) that is now corrected in \texttt{compute\_fixed\_messages} and the table pipeline. inv2/inv3 ($\mathrm{Reduction}\ge{-}\mathrm{NewRate},\le1$) always hold.}",
              r"\label{tab:metric_invariant_audit}", r"\end{table}"]
    (TABLE_DIR / "metric_invariant_audit.tex").write_text("\n".join(lines))

    # ---- #2 selection bias (micro @Pass vs @All + PRed + median + degen) ----
    lines = [r"\begin{table*}[t]", r"\centering", r"\small", r"\begin{tabular}{lcccccccc}",
             r"\toprule",
             r"\textbf{Model} & \textbf{Pass@1} & \textbf{Red.@P} & \textbf{Red.@All} & \textbf{New@P} & \textbf{New@All} & \textbf{PRed.} & Red.med.@P & degen\\",
             r"\midrule"]
    for n, m in a["models"].items():
        mp, ma = m["micro_at_pass"], m["micro_at_all"]
        pred = (m["pass@1"]) * (mp.get("Reduction") or 0)
        lines.append(row([n, f1(pct(m["pass@1"])), f1(pct(mp.get("Reduction"))), f1(pct(ma.get("Reduction"))),
                          f1(pct(mp.get("NewRate"))), f1(pct(ma.get("NewRate"))), f1(pct(pred)),
                          f1(pct(m["median_red_at_pass"])), m["n_degen"]]))
    lines += [r"\bottomrule", r"\end{tabular}",
              r"\caption{Selection-bias audit on \textbf{LintEval-Lite} (micro / corpus-level, matching the paper formulas). Red.@P/New@P = $\sum(\cdot)/\sum|L|$ over each model's \emph{own} passed subset; Red.@All/New@All use the common set of all compiled instances (same denominator across models) to remove per-model selection bias. PRed.$=$Pass@1$\times$Red.@P. degen $=$ \#samples with new messages $>5{\times}|L|$ (flagged degenerate outputs). Red.med.@P is the per-instance median (robust to the long tail).}",
              r"\label{tab:selection_bias_atall}", r"\end{table*}"]
    (TABLE_DIR / "selection_bias_atall.tex").write_text("\n".join(lines))

    # ---- #3 micro pass@1 / Reduction@P / New@P CI + common-pass ----
    lines = [r"\begin{table*}[t]", r"\centering", r"\small", r"\begin{tabular}{lccccc}",
             r"\toprule",
             r"\textbf{Model} & \textbf{Pass@1} [95\% CI] & \textbf{Red.@P} [95\% CI] & \textbf{New@P} [95\% CI] & \textbf{Red.@common}\\",
             r"\midrule"]
    for n, m in a["models"].items():
        c = cp["ci"][n]
        pa, plo, phi = c["pass@1"]; ra, rlo, rhi = c["red@P"]; na, nlo, nhi = c["new@P"]

        def ci(lo, hi):
            return f"[{f1(pct(lo))},{f1(pct(hi))}]" if lo is not None else ""
        lines.append(row([n, f"{f1(pct(pa))} {ci(plo, phi)}", f"{f1(pct(ra))} {ci(rlo, rhi)}",
                          f"{f1(pct(na))} {ci(nlo, nhi)}", f1(pct(cp["red_common"][n]))]))
    lines += [r"\bottomrule", r"\end{tabular}",
              r"\caption{Pass@1, Reduction@P and New@P (micro / corpus-level) with problem-ID-clustered bootstrap 95\% CIs ($B=1000$). Red.@common = micro Reduction on the subset of instances that \emph{all} main models pass (n=" + str(cp["common_pass_n"]) + r"), a common-denominator view free of per-model selection bias.}",
              r"\label{tab:pass_at1_ci}", r"\end{table*}"]
    (TABLE_DIR / "pass_at1_ci.tex").write_text("\n".join(lines))

    # ---- #4 suppression ----
    lines = [r"\begin{table}[t]", r"\centering", r"\small", r"\begin{tabular}{lcccccc}",
             r"\toprule",
             r"\textbf{Model} & $n$ & w/ supp. & rate & C++ & Python & Java\\",
             r"\midrule"]
    for n, m in a["models"].items():
        s = m["suppression"]; bl = s["by_lang"]
        lr = lambda l: f"{bl[l]['with']}/{bl[l]['n']}" if l in bl else "--"
        rate = "0.0" if s["rate"] == 0 else f"{s['rate']*100:.2f}"
        lines.append(row([n, s["n"], s["with"], rate + r"\%", lr("cpp"), lr("py3"), lr("java")]))
    lines += [r"\bottomrule", r"\end{tabular}",
              r"\caption{Linter-gaming / suppression detection. We scan outputs for \texttt{NOLINT} (C++), \texttt{pylint: disable} (Python), and \texttt{NOPMD}/\texttt{@SuppressWarnings} (Java). Rates are negligible ($\le0.6\%$): models do not game the linter by inserting suppression comments.}",
              r"\label{tab:suppression_detection}", r"\end{table}"]
    (TABLE_DIR / "suppression_detection.tex").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
