# FS-ASM v1 — indeks operacyjny (nie zastępuje architektury)

**Źródło jedyne:** [`FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md`](FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md). Jest to oryginalna zatwierdzona kopia; przed istotną migracją należy ją przeczytać CAŁĄ, również części XIX–XX. Ten plik tylko ułatwia nawigację.

## Cel, nie demonstrator

Deterministyczny runtime przeprowadza projekt przez zwalidowany plan Child Tasks, zachowuje stan poza kontekstem modelu, dobiera mały kontekst, egzekwuje uprawnienia narzędzi, zbiera niezależne evidence i wznawia pracę. **Model NIE pilnuje systemu; system pilnuje modelu.** Agent rozwijający repo (Vibe Web) nie jest agentem działającym w FS-ASM.

## Mapa warstw

```text
Human Goal → Intake / PlannerProposal / Task Compiler
            → FS-ASM Domain Core + Scheduler (stan/status/limity)
            → Workflows (techniczne activities/sygnały/wait)
            → Context Builder (task-specific retrieval)
            → Model Gateway (lokalny ~7B Q4, później Mistral A/B)
            → Executor Loop: model ↔ Tool Broker ↔ ToolObservation
            → niezależny Verifier rzeczywistych artefaktów
            → Evidence → commit jednego RunState → następny Child Task
```

**Pamięć:** Project Memory, autorytatywny Run State ze zintegrowanym planem i Task Register, oddzielna techniczna Workflow History. Jeden writer/run, jeden aktywny Child Task w v1; revision i jeden punkt zatwierdzenia. `plan.json` może być wyłącznie odtwarzalną projekcją. Przy PASS dowód musi istnieć, pochodzić z właściwego run/task/attempt i zostać zaakceptowany przed commitem stanu. Nie obiecujemy exactly-once dowolnych skutków narzędzi ani transakcji wszystkich plików naraz.

**Planowanie i wykonanie:** Planner tworzy nieufną propozycję, Compiler nadaje IDs i weryfikuje strukturę/scope/dependencies; trzy Child Tasks to przypadek demonstracyjny, nie docelowy limit. Scheduler wykonuje cały wymagany plan. Executor ma prawdziwą ograniczoną pętlę model→tools→observation; oddzielaj task_attempt, agent_step, model/tool calls i techniczne retry Workflows. Sam tekst `DONE` nie oznacza PASSED.

**Dostęp i jakość:** Tool Broker kodem sprawdza `allowed_files` i uruchamiane polecenia, a Verifier czyta diff/test/artefakt zamiast przepakowywać odpowiedź stuba. Human Gate wiąże decyzję z konkretną instancją gate, a retry jest ograniczone. Router jest deterministyczny, domyślnie wybiera lokalny model, a Mistral API służy do limitowanej konsultacji lub jawnego przekazania.

**Wdrożenie:** Workflows w zatwierdzonym wariancie hybrydowym, worker/stan/kod i lokalny LLM na laptopie, zdalna orkiestracja dozwolona. Użytkownik akceptuje jawne przesyłanie danych i telemetrię, przy zachowaniu ochrony kluczy i uprawnień. Vibe buduje i testuje cały runtime na atrapach; dopiero potem transfer na laptop, realny ~7B Q4 i dwa modele API. LLMC/wektorowy retrieval, fine-tuning, inny framework, distributed workers, web UI i neuralne MoE nie są zadaniami v1.

**Weryfikacja ukończenia:** pełny plan, realne kontrolowane narzędzia i niezależne artefakty, bezpieczne start/resume, retry/routing/gate, działanie całości na scripted modelach i możliwość instalacji — nie sam `pytest green` dla stuba ani `TASK-001=PASSED`.
