# LintEval: Benchmarking LLMs on Linter-Guided File Refactoring

🎉 🎉 🎉  **Accepted at EMNLP 2026 Findings.** · [Paper](https://arxiv.org/abs/2610.20027) · [Dataset](https://huggingface.co/datasets/deepbreath7/LintEval)

## Abstract

Linters are widely used in code maintenance and real-time IDE editing to surface lint alerts related to performance, style, error-prone, and other patterns in source files. However, existing code benchmarks do not explicitly evaluate linter-guided file refactoring, where models must reduce lint alerts in source files with correct initial functionality while satisfying functionality preservation. We introduce LintEval, a multilingual benchmark for linter-guided file refactoring across C++, Python, and Java, comprising 13,061 programs with correct initial functionality and 171,662 lint alerts extracted using language-specific linters. LintEval jointly evaluates functionality preservation, lint alert reduction, new alert avoidance, and edit minimality. Experiments reveal a persistent trade-off: closed-source commercial models reach up to 90.4% Reduction@P but achieve only 67.1%-68.3% Pass@1, while several open-source small models show low or negative Reduction@P. A controlled fine-tuning study further shows that supervision format matters: refactoring-oriented SFT raises Qwen2.5-Coder-7B Reduction@P from 24.7% to 76.0%. LintEval enables controlled evaluation of models that improve source files under functionality preservation.

## Resources

- **Paper** — [arXiv:2610.20027](https://arxiv.org/abs/2610.20027) (EMNLP 2026 Findings)
- **Dataset** — [deepbreath7/LintEval](https://huggingface.co/datasets/deepbreath7/LintEval) on Hugging Face: `lite`, `demo` and `full` splits, released per-sample results and paper tables
- **Code** — [github.com/6643789wsx/LintEval](https://github.com/6643789wsx/LintEval)
- **Setup** — [SETUP.md](SETUP.md): environment, dependencies, API configuration, running commands
- **Data format** — [docs/DATA.md](docs/DATA.md): file layout, record schema, loading instructions
- **Evaluation & reproduction** — [docs/REPRODUCE.md](docs/REPRODUCE.md): metrics and the released paper numbers

## Citation

If you use LintEval, please cite the paper:

```bibtex
@misc{deng2026lintevalbenchmarkingllmslinterguided,
      title={LintEval: Benchmarking LLMs on Linter-Guided File Refactoring},
      author={Tongwei Deng and Jinyu Zhu and Yue Cao and Chenxu Wang and Yanzhen Zou and Bing Xie},
      year={2026},
      eprint={2610.20027},
      archivePrefix={arXiv},
      primaryClass={cs.SE},
      url={https://arxiv.org/abs/2610.20027}
}
```

Paper: <https://arxiv.org/abs/2610.20027> (accepted at Findings of EMNLP 2026; the proceedings
entry will supersede the arXiv preprint once available).
