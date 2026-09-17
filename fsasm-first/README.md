# fsasm-first — eksperymentalna implementacja FS-ASM

Ten katalog zawiera kod, testy i zależności obecnego poligonu, nie całą historię projektu. **Jedyna architektura docelowa:** [pełny dokument v1](docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md). Decyzje późniejsze: [profil wdrożenia](docs/DEPLOYMENT_DECISIONS.md). Stan implementacji: [PROJECT_STATUS](PROJECT_STATUS.md). Protokół dla agenta: root [`../AGENTS.md`](../AGENTS.md), lokalny [`AGENTS.md`](AGENTS.md), [mapa dokumentacji](docs/DOCUMENTATION_MAP.md) oraz zadanie jawnie zaakceptowane przez użytkownika.

## Obecny zakres (nie mylić z celem v1)

M1–M3 były zamknięte. M4 testuje pojedynczy Child Task (`TASK-001`) za pomocą deterministycznego stuba, retry, stan i Human Gate. PR #20 został scalony, ale sam merge nie zamyka M4. Raport z 17.09 wskazuje G3–G5 wymagające osobnego sprawdzenia/korekty; nie wolno z góry nazywać ich naprawionymi. Wciąż brak rzeczywistej pętli model→tool→observation, pełnego schedulera, Context Buildera, Model Gateway, Broker/Verifiera artefaktów i operacyjnego resume. Szczegóły w [statusie](PROJECT_STATUS.md).

## Instalacja i testy

Polecenia wykonuj z `fsasm-first/`, na izolowanym checkoutcie lub katalogu bez wartościowych danych `./runtime`:

```bash
uv sync --frozen
uv run pytest -q
make check
```

Testy live Mistral API są opt-in i nie były podstawą deklaracji gotowego 7B. Historyczny przykład SDK można uruchomić przez:

```bash
make start-worker
# osobny terminal
make execute workflow=hello-world input='{"name":"World"}'
```

`src/fsasm/` to modele, przejścia, stub, persistence i obecna demonstracyjna weryfikacja; `src/workflows/` to starsze przebiegi M1–M4, `src/entrypoints/` to wejścia, `tests/` do testów. `src/examples/` zawiera cookbook SDK, nie kod docelowego Executora. Przed zmianą Workflows przeczytaj [.agents/skills/workflows/SKILL.md](.agents/skills/workflows/SKILL.md).

**Dalsze prace:** po akceptacji ograniczony task, branch od aktualnego `Fsasm-experimental`, osobny PR i review. Nie traktuj starego „M5 następne”, trzytaskowego planu Plannera ani wcześniejszego AGENTS jako nakazu dla v1. [Kolejka migracji](docs/MIGRATION_BACKLOG_V1.md) jest propozycją do zatwierdzania etapami.
