# Optional AI mode

Version 1 of this agent is deliberately AI-free. Collection, normalization,
deduplication, classification, scoring and reporting are all deterministic
Python. That keeps the daily run free, fast, reproducible and debuggable — if a
score looks wrong you can point at the exact rule that produced it.

The AI layer is an optional enrichment on top: it adds a short "why it matters"
paragraph to the handful of articles that already scored highest. It never
decides what gets collected, deduplicated or categorised.

## Why only the top articles

Sending every collected article to a model is slow and wasteful. A typical run
looks like this:

    Collected            ~70
    After deduplication  ~40
    Relevant (score ≥ 4) ~20
    High relevance       ~8     <- only these are sent to the model

The cut-off is `ai.max_articles` in `config.yaml`, default 8.

## Running with Ollama locally

[Ollama](https://ollama.com) runs open models on your own machine. No API key,
no per-token cost.

1. Install Ollama and pull a small model:

   ```bash
   ollama pull qwen2.5:1.5b
   ```

2. Confirm it is serving (Ollama listens on `http://localhost:11434`):

   ```bash
   curl http://localhost:11434/api/tags
   ```

3. Enable it in `config.yaml`:

   ```yaml
   ai:
     enabled: true
     provider: ollama
     model: "qwen2.5:1.5b"
     base_url: "http://localhost:11434"
     max_articles: 8
   ```

4. Run the agent as usual:

   ```bash
   python -m src.main
   ```

If Ollama is not reachable, the agent logs a warning and continues without AI.
A model being down is never a reason for the daily report to fail.

Larger models (`qwen2.5:7b`, `llama3.1:8b`, `mistral`) give better summaries at
the cost of speed. For eight articles a day, even a 7B model finishes in under a
minute on a modern laptop.

## Why Ollama is not in the GitHub Actions workflow

GitHub-hosted runners are ephemeral and CPU-only. Pulling a model on every run
would add several gigabytes of download and many minutes of inference to a job
that otherwise finishes in under two minutes. If you want AI summaries on a
schedule, the sensible options are:

- run the agent locally (or on a self-hosted runner) with Ollama enabled, or
- switch `ai.provider` to a hosted provider and supply the key as a GitHub
  Actions secret — see below.

## Using a hosted provider instead

`src/ai/providers/openai_provider.py` implements the same one-method interface
against any OpenAI-compatible endpoint.

```yaml
ai:
  enabled: true
  provider: openai
  model: "gpt-4o-mini"
  base_url: "https://api.openai.com/v1"
  api_key_env: "OPENAI_API_KEY"
  max_articles: 8
```

The key itself never appears in this repository. Only the *name* of the
environment variable is configured. Store the value as a repository secret
(`Settings → Secrets and variables → Actions`) and expose it to the run step:

```yaml
      - name: Run the intelligence agent
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: python -m src.main
```

If the variable is unset, the provider reports itself unavailable and the run
continues without AI.

## Adding another provider

1. Create `src/ai/providers/<name>.py` with a class exposing `name`,
   `available()` and `complete(prompt, system)`.
2. Register it in `src/ai/providers/__init__.py`.
3. Set `ai.provider` in `config.yaml`.

Nothing in the collection pipeline changes.
