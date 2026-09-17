---
name: fsasm-vibe-coding
description: Repository workflow for authorized FS-ASM coding, review and persistent handoff. Read canonical runtime v1 and the repository handoff first.
user-invocable: true
---

# FS-ASM Vibe Code Web — procedura pracy

To skill **zewnętrznego programisty** FS-ASM, nie runtime, dodatkowa architektura, status ani zgoda na implementację. Vibe Web czyta Git checkout; dokumenty muszą być w repozytorium, nie w załącznikach czatu.

## Start nowej sesji — bez historii rozmowy

1. Otwórz root [`AGENTS.md`](../../../AGENTS.md) i przeczytaj cały [`fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md`](../../../fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md), również ostatnie rozdziały. Hash SHA-256: `56aeeb60c8c700c71dc3d395659127afbf511e1726e0ffd76270c848fd764808`.
2. Przeczytaj [`DEPLOYMENT_DECISIONS.md`](../../../fsasm-first/docs/DEPLOYMENT_DECISIONS.md) oraz [`references/repository-handoff.md`](references/repository-handoff.md). To **jedyny aktualizowany repozytoryjny handoff**, nie druga architektura. Zestaw jego datowane fakty z bieżącym `Fsasm-experimental`, PR, kodem i CI.
3. Przeczytaj jawnie zlecone, ograniczone zadanie użytkownika, potem tylko potrzebne źródła/testy. Dla Workflows użyj `fsasm-first/.agents/skills/workflows/SKILL.md` i odpowiednich referencji SDK.
4. Jeżeli brakuje kanonu, jest rozbieżny albo zadanie nie jest autoryzowane — zgłoś problem; nie rekonstruuj v1 ze skrótu i nie wybieraj sam kolejnego zadania.

## Wykonanie zadania

Pracuj od aktualnego `Fsasm-experimental` na task branchu, proponuj PR do tego brancha, nie scalaj go samodzielnie. Najpierw odtwórz problem i zaplanuj minimalny zakres, potem koduj, sprawdź diff oraz właściwe testy. Dla zmian runtime'u: testy ukierunkowane, pełny pytest, `make check`, `git diff --check`, chyba że zaakceptowany task wymaga innego zestawu. Dla docs sprawdź odsyłacze i diff; nie udawaj wykonania testów niewykonanych. Nie używaj danych produkcyjnych jako fixture. Nie uruchamiaj lokalnego 7B użytkownika w chmurowym Vibe.

Użytkownik i ChatGPT zatwierdzają architekturę, zadania i review. Nie rozpoczynaj M5, LLMC, integracji `main`, nie zamykaj M4 ani nie zmieniaj architektury bez odrębnej zgody. Profil Workflows jest hybrydowy; użytkownik akceptuje jawne dane i telemetrię Mistrala, co nie znosi ochrony sekretów i egzekwowania uprawnień narzędzi.

## Handoff i referencje

- **[`references/repository-handoff.md`](references/repository-handoff.md)** — jedyny trwały status repo oraz miejsce kolejnego zatwierdzonego kroku; uaktualniaj wyłącznie przy rzeczywistej zmianie stanu i po zweryfikowaniu Git/CI.
- [`references/session-handoff.md`](references/session-handoff.md) — krótkie przekazanie **konkretnego zadania** w PR/branchu przy końcu kontekstu; nigdy drugi globalny status.
- [`references/fsasm-implementation.md`](references/fsasm-implementation.md) — metody i granice implementacji, podporządkowane pełnej v1.
- Pozostałe `references/` — planowanie, debugowanie i code review czytane tylko gdy potrzebne.

Kończ odpowiedź faktami: branch/commit, rzeczywiste testy, zakres i ograniczenia. Self-review nie jest niezależną akceptacją. Skill może być odczytany ręcznie po ścieżce; nie zakładaj automatycznego discovery w Web bez testu.
