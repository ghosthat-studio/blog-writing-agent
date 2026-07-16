"""Model interface. Talks to Ollama or any OpenAI-compatible server, stdlib only.

The model is config, not code: swap Ollama for LM Studio, llama.cpp's server, vLLM,
or a hosted key by editing config.json. Two tiers — a small fast model for utility
work (queries, lists, judging), the good model for prose. Same code, one config
block apart.

Skeleton — implementation lands with the agent core.
"""
