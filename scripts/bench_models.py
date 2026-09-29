"""Week-1 model benchmark. Thin wrapper; the logic lives in helpmate.eval.bench.

Run from backend/ on the GPU machine, with Ollama running:
    uv run python ../scripts/bench_models.py --models llama3.2:3b qwen3:4b
(equivalently: uv run helpmate-bench ...)
"""

from helpmate.eval.bench import main

if __name__ == "__main__":
    main()
