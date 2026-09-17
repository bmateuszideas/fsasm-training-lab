# FS-ASM — Training Lab / runtime v1

FS-ASM jest deterministycznym runtime'em organizującym pracę wymiennych modeli językowych nad projektami. Utrzymuje program Child Tasks, kontekst, stan, uprawnienia i zweryfikowane efekty **poza pamięcią modelu**. Model proponuje działania; program kontroluje wykonanie i przyznaje PASS dopiero na podstawie niezależnych dowodów. System automatyzuje pierwotny handoff ChatGPT (Planner) → pliki/TODO → Codex (Executor), nie kopiuje dosłownie wszystkich historycznych instrukcji v7.

**Aktywny branch: `Fsasm-experimental`.** To tutaj odbywa się dalszy rozwój runtime'u. `main` nie jest automatycznie aktualnym wydaniem ani celem scalenia. Katalog [`fsasm-first/`](fsasm-first/) zawiera implementację eksperymentalną; repozytorium jest środowiskiem budowy, nie wymaganym elementem docelowego uruchomienia.

## Jednoznaczny punkt startowy

| Czytaj | Po co |
|---|---|
| [ZATWIERDZONA ARCHITEKTURA RUNTIME V1 — pełny dokument](fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md) | Jedyny normatywny opis docelowego runtime'u; 671 linii. Nie zamieniaj go na skrót. |
| [Decyzje wdrożeniowe](fsasm-first/docs/DEPLOYMENT_DECISIONS.md) | Późniejsze świadome ustalenia o hybrydowym Workflows, jawnych danych i telemetrii. |
| [PROJECT_STATUS](fsasm-first/PROJECT_STATUS.md) | Stan implementacji na datowanym SHA i aktualny problem do rozstrzygnięcia. |
| [AGENTS.md](AGENTS.md), [mapa dokumentacji](fsasm-first/docs/DOCUMENTATION_MAP.md), [polityka branchy](fsasm-first/docs/BRANCH_POLICY.md) | Hierarchia źródeł i praca z Vibe/GitHub. |
| [Plan migracji](fsasm-first/docs/MIGRATION_BACKLOG_V1.md) | Kolejka do zatwierdzenia, nie automatyczne zlecenie. |
| [Audyt Astra, 17.09.2026](fsasm-first/docs/reviews/FSASM_V1_ARCHITECTURE_GAP_ANALYSIS_AND_MIGRATION_PLAN_2026-09-17.md) | Dowody dla badanego SHA i hipotezy do sprawdzenia; nie live status. |

## Model współpracy i wdrożenia

Użytkownik z ChatGPT planują i dokonują review; wyłącznie Mistral Vibe Code Web / GLM-5.2 pisze kod FS-ASM. Vibe Web NIE jest wewnętrznym Executorem. W chmurowym środowisku Vibe budujemy i weryfikujemy kompletny runtime przy użyciu stubów/fixture'ów, bez uruchamiania laptopowego 7B. Dopiero po zakończeniu przenosimy projekt na komputer użytkownika, uruchamiamy lokalny model ok. 7B Q4 i integrujemy dwa modele Mistral API do wsparcia/eskalacji. Konkretne modele i ich progi nie są jeszcze zatwierdzone.

Docelowy profil jest **hybrydowy**: worker, pliki, stan domenowy i model lokalny na komputerze; orkiestracja Workflows i jej techniczna historia mogą działać w usłudze Mistral. Użytkownik akceptuje przekazywanie danych w postaci jawnej i telemetrię. Nie dodawaj szyfrowania/wyłączania telemetry wyłącznie z powodów prywatności; nadal chroń klucze API, uprawnienia narzędzi i integralność stanu.

## Stan kodu — datowana migawka

17.09.2026: [PR #20](https://github.com/bmateuszideas/fsasm-training-lab/pull/20) jest **scalony**, ale M4 nie został automatycznie zaakceptowany. Audyt Astry odtworzył G3–G5 na kandydacie `142db38` i wymaga osobnego przeglądu na bieżącym HEAD. M1–M3 były zamknięte; M5 nie rozpoczęto. Executor pozostaje stubem dla `TASK-001`; nie ma pełnej agentowej pętli, narzędzi i niezależnej weryfikacji realnych artefaktów. To stan historyczny — sprawdź aktualny Git i CI, zanim powtórzysz te liczby.

Instrukcje testów/SDK: [fsasm-first/README.md](fsasm-first/README.md). Nie odtwarzaj usuniętych folderów archiwum ani usuniętego `.vibe/README.md` tylko dlatego, że stary README je wymieniał; wersje zachowuje historia Git.
