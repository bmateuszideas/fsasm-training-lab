# fsasm-first — kod i uruchomienie

To eksperymentalna implementacja runtime'u FS-ASM. Główne [README repozytorium](../README.md) służy nawigacji; [root AGENTS](../AGENTS.md) jest **jedynym repozytoryjnym protokołem wejścia agenta**. Status i handoff: [`.vibe/skills/fsasm-vibe-coding/references/repository-handoff.md`](../.vibe/skills/fsasm-vibe-coding/references/repository-handoff.md). Cel: [pełna architektura v1](docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md).

## Struktura

`src/fsasm/` — domena i obecne komponenty demonstratora; `src/workflows/` — przebiegi Workflows, w tym historyczne M1–M4; `src/entrypoints/` — uruchomienie; `tests/` — testy; `src/examples/` — przykłady SDK, nie wykonawca FS-ASM; `.agents/skills/workflows/` — referencje SDK dostawcy.

## Środowisko i kontrole

Z katalogu `fsasm-first/` w izolowanym checkoutcie, nie na katalogu z cennymi danymi `runtime/`:

```bash
uv sync --frozen
uv run pytest -q
make check
```

Worker i demonstracyjne `hello-world` (drugi terminal dla komendy execute):

```bash
make start-worker
make execute workflow=hello-world input='{"name":"World"}'
```

Testy z rzeczywistym API są opt-in. Wynik stuba nie dowodzi wykonania zadania z prawdziwym modelem. Reguły dla Vibe i SDK są w podlinkowanych skillach; brak odrębnego lokalnego `AGENTS.md` jest zamierzony.
