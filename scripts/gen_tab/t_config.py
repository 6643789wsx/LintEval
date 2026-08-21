"""Model and decoding configuration table (appendix)."""


def generate_model_decoding_config_tex() -> str:
    lines = [
        "% ============================================================",
        "% Placement: Appendix (Experimental Setup reproducibility)",
        "% ============================================================",
        "\\begin{table}[t]",
        "\\centering",
        "\\small",
        "\\begin{adjustbox}{max width=\\columnwidth}",
        "\\begin{tabular}{llccc}",
        "\\toprule",
        "\\textbf{Model} & \\textbf{Access} & \\textbf{Temp.} & \\textbf{Top-$p$} & \\textbf{Max Tokens} \\\\",
        "\\midrule",
        "GPT-5.2 & API & 0.0 & 1.0 & 4,096 \\\\",
        "GPT-5.4-mini & API & 0.0 & 1.0 & 4,096 \\\\",
        "\\midrule",
        "DeepSeek-v3.2 & API & 0.0 & 1.0 & 4,096 \\\\",
        "Qwen2.5-Coder-32B-Instruct & local (vLLM) & 0.0 & 1.0 & 4,096 \\\\",
        "Qwen2.5-Coder-7B-Instruct & local (vLLM) & 0.0 & 1.0 & 4,096 \\\\",
        "Qwen2.5-Coder-3B-Instruct & local (vLLM) & 0.0 & 1.0 & 4,096 \\\\",
        "Qwen2.5-Coder-0.5B-Instruct & local (vLLM) & 0.0 & 1.0 & 4,096 \\\\",
        "Llama-3.2-3B-Instruct & local (vLLM) & 0.0 & 1.0 & 4,096 \\\\",
        "Llama-3.2-1B-Instruct & local (vLLM) & 0.0 & 1.0 & 4,096 \\\\",
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{adjustbox}",
        "\\caption{Decoding configurations for all evaluated models. All models use greedy decoding. Local models are served via vLLM.}",
        "\\label{app:model_decoding_config}",
        "\\end{table}",
    ]
    return "\n".join(lines)
