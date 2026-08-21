"""
generate_all_tables.py - Generate all LaTeX tables for the paper.

Usage:
    python scripts/gen_tab/generate_all_tables.py

Output:
    docs/table/*.tex
"""

from gen_tab._shared import (
    LATEX_TABLE_DIR,
    ALL_BASE_MODELS,
    load_baseline,
    load_model_results,
)
from gen_tab.t1_dataset import generate_dataset_statistics_tex
from gen_tab.t1b_taxonomy import generate_cross_language_mapping_tex
from gen_tab.t2_overall import generate_overall_performance_tex
from gen_tab.t3_language import (
    compute_language_metrics,
    generate_language_performance_main_tex,
    generate_language_performance_appendix_tex,
)
from gen_tab.t5_alert_count import (
    compute_alert_count_metrics,
    generate_alert_count_appendix_tex,
)
from gen_tab.t6_sft import generate_sft_results_tex
from gen_tab.t7_ablation import generate_ablation_tex
from gen_tab.t7b_grounding_ablation import generate_grounding_ablation_tex
from gen_tab.t8_failure import generate_failure_analysis_tex
from gen_tab.t8b_failure_categories import generate_failure_categories_tex
from gen_tab.t4_category import generate_category_performance_full_tex
from gen_tab.t_config import generate_model_decoding_config_tex
from gen_tab.t_sft_cat import generate_sft_alert_category_breakdown_tex


def main() -> None:
    print("=" * 60)
    print("Generating LaTeX Tables for Paper")
    print("=" * 60)

    LATEX_TABLE_DIR.mkdir(parents=True, exist_ok=True)

    baselines = load_baseline()
    print(f"\nLoaded baseline: {len(baselines)} entries")

    print("\n" + "=" * 60)
    print("Main Text Tables")
    print("=" * 60)

    print("\n  Generating T1: Dataset Statistics...")
    t1_path = LATEX_TABLE_DIR / "dataset_statistics.tex"
    with open(t1_path, "w") as f:
        f.write(generate_dataset_statistics_tex())
    print(f"    Saved: {t1_path}")

    print("  Generating T1b: Cross-language Mapping...")
    t1b_path = LATEX_TABLE_DIR / "cross_language_mapping.tex"
    with open(t1b_path, "w") as f:
        f.write(generate_cross_language_mapping_tex())
    print(f"    Saved: {t1b_path}")

    print("  Generating T2: Overall Performance...")
    t2_path = LATEX_TABLE_DIR / "overall_performance.tex"
    with open(t2_path, "w") as f:
        f.write(generate_overall_performance_tex())
    print(f"    Saved: {t2_path}")

    print("  Computing language and alert count metrics...")
    all_lang_metrics = {}
    all_alert_metrics = {}
    for model_display, model_name in ALL_BASE_MODELS:
        model_results = load_model_results(model_name)
        if model_results:
            all_lang_metrics[model_display] = compute_language_metrics(baselines, model_results)
            all_alert_metrics[model_display] = compute_alert_count_metrics(baselines, model_results)

    print("  Generating T3: Language-wise Performance (Main)...")
    t3_path = LATEX_TABLE_DIR / "language_performance.tex"
    with open(t3_path, "w") as f:
        f.write(generate_language_performance_main_tex(all_lang_metrics))
    print(f"    Saved: {t3_path}")

    print("  Skipping T4: Category-wise Performance (now Figure 3)")
    print("    See: scripts/gen_fig_tab/gen_fig3_category_mr_p.py")

    print("  Generating T6: SFT Results...")
    t6_path = LATEX_TABLE_DIR / "sft_results.tex"
    with open(t6_path, "w") as f:
        f.write(generate_sft_results_tex())
    print(f"    Saved: {t6_path}")

    print("  Generating T7: Ablation (With/Without Alerts)...")
    t7_path = LATEX_TABLE_DIR / "ablation_no_message.tex"
    with open(t7_path, "w") as f:
        f.write(generate_ablation_tex())
    print(f"    Saved: {t7_path}")

    print("  Generating T7b: Grounding Ablation...")
    t7b_path = LATEX_TABLE_DIR / "grounding_ablation.tex"
    with open(t7b_path, "w") as f:
        f.write(generate_grounding_ablation_tex())
    print(f"    Saved: {t7b_path}")

    print("  Generating T8: Failure Case Analysis...")
    t8_path = LATEX_TABLE_DIR / "failure_analysis_detailed.tex"
    with open(t8_path, "w") as f:
        f.write(generate_failure_analysis_tex())
    print(f"    Saved: {t8_path}")

    print("  Generating T8b: Failure Categories...")
    t8b_path = LATEX_TABLE_DIR / "failure_categories.tex"
    with open(t8b_path, "w") as f:
        f.write(generate_failure_categories_tex())
    print(f"    Saved: {t8b_path}")

    print("\n" + "=" * 60)
    print("Appendix Tables")
    print("=" * 60)

    print("\n  Generating A1: Full Language-wise Performance...")
    a1_path = LATEX_TABLE_DIR / "language_performance_full.tex"
    with open(a1_path, "w") as f:
        f.write(generate_language_performance_appendix_tex(all_lang_metrics))
    print(f"    Saved: {a1_path}")

    print("  Generating A2: Full Alert Count Impact...")
    a2_path = LATEX_TABLE_DIR / "alert_count_full.tex"
    with open(a2_path, "w") as f:
        f.write(generate_alert_count_appendix_tex(all_alert_metrics))
    print(f"    Saved: {a2_path}")

    print("  Generating A3: Model Decoding Configuration...")
    a3_path = LATEX_TABLE_DIR / "model_decoding_config.tex"
    with open(a3_path, "w") as f:
        f.write(generate_model_decoding_config_tex())
    print(f"    Saved: {a3_path}")

    print("  Generating A4: SFT Alert Category Breakdown...")
    a4_path = LATEX_TABLE_DIR / "sft_alert_category_breakdown.tex"
    with open(a4_path, "w") as f:
        f.write(generate_sft_alert_category_breakdown_tex())
    print(f"    Saved: {a4_path}")

    print("  Generating A5: Full Category-wise Performance...")
    a5_path = LATEX_TABLE_DIR / "category_performance_full.tex"
    with open(a5_path, "w") as f:
        f.write(generate_category_performance_full_tex())
    print(f"    Saved: {a5_path}")

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
