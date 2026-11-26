# Reproducing CampusPilot

Everything here is run from the repo root. Versions are pinned: Python 3.12 (`.python-version`), Node (`.nvmrc`), `apps/api/uv.lock` and `package-lock.json`.

## (a) The local app

1. Install `uv` and Node.
2. Install dependencies:

   ```bash
   make setup
   ```

3. Create your settings file and edit it. Never commit it.

   ```bash
   cp .env.example .env
   ```

4. Start the model tunnel (local mode uses Ollama through an SSH tunnel; the host alias is in your SSH config) and check it:

   ```bash
   ssh -fN passpoli-llm
   make tunnel-check
   ```

   No tunnel? `make mock-dev` runs with the scripted fake model.
5. Run the API (127.0.0.1:8000) and web UI (127.0.0.1:3000):

   ```bash
   make dev
   ```

6. Run the offline tests and linters:

   ```bash
   make test
   ```

## (b) The hosted API with Docker

```bash
make docker-build
make docker-run
```

`docker-run` serves the API on `127.0.0.1:8001` in hosted mode (`INDEX_SOURCE=release`, 5 s download timeout, CORS for `http://localhost:3000`). If the release download fails it uses the fixture demo index. Check it:

```bash
curl -s http://127.0.0.1:8001/v1/status
```

To smoke-test it with your own test key (`TEST_LLM_PROVIDER` and `TEST_LLM_KEY` in `.env`):

```bash
make smoke-hosted URL=http://127.0.0.1:8001
```

## (c) The index from the registry

Sources are listed in `data/sources/registry.csv`. Only approved sources are fetched.

Locally:

```bash
make ingest-dry   # show what would be fetched
make ingest       # fetch and index (slow on purpose)
```

On GitHub: **Actions** -> **Build index** -> **Run workflow**. The workflow runs `scripts/ingest.py --all-approved`, then `scripts/release_index.py`, which writes:

- `campuspilot.db`: the index.
- `manifest.json`: per source and document, its URL, fetch time and SHA-256, plus totals.
- `SHA256SUMS`: checksums of `campuspilot.db` and `manifest.json`.

It refuses to publish fewer than 100 chunks and uploads the three files to a release named `index-YYYY-MM-DD`. Nothing is committed to Git.

Verify a release (needs the GitHub CLI):

```bash
mkdir index-check && cd index-check
gh release download <INDEX_TAG> --repo biprabhanu/iitb-campus-assistant
sha256sum -c SHA256SUMS      # macOS: shasum -a 256 -c SHA256SUMS
```

Both lines should end in `OK`. `<INDEX_TAG>` is TBD (for example `index-YYYY-MM-DD`; see the Releases page).

Page content changes over time, so an index built on another day can differ.

## (d) The evaluation numbers

Outputs of language models vary between runs and between providers. Expect small differences, not identical numbers. Always report the provider, model, index version and date with a result.

Local Gemma (needs the tunnel and a running API):

```bash
make acceptance
```

It asks every question in `data/eval/questions.jsonl` and writes `data/eval/results-<date>.json` (not tracked).

Hosted run: command TBD in Phase 4.

| Run | Provider | Model | Index version | Date | Result |
|---|---|---|---|---|---|
| Local | Ollama (Passpoli) | `gemma4:26b-a4b-it-q4_K_M` (default in `.env.example`) | `<INDEX_VERSION>` | `<DATE>` | see `docs/EVAL.md` |
| Hosted | `<PROVIDER>` | `<MODEL_IDS>` | `<INDEX_VERSION>` | `<DATE>` | TBD after Phase 4 |
