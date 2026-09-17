# FS-ASM — informacja o demonstratorze M1–M4 (dokument historyczno-techniczny)

**Status: informacja o ZASTANYM KODZIE, NIE ARCHITEKTURA DOCZELOWA ani żywy backlog.** Poprzedni wielostronicowy opis M1–M4, w tym oryginalne kryteria „dokładnie trzy taski” i stare twierdzenia o PR, można odtworzyć z Git history (blob `76a2ecdb6220771b8e530d852086e4112f9969d0`). Zastąpiono go skrótem, aby nie przekazywać modelowi stale tych samych nieaktualnych poleceń.

## Dotychczas zbudowane mechanizmy

- **M1:** modele Pydantic, deterministyczny PlannerStub, walidacja planu, zapis i przejścia.
- **M2:** Planner Mistral przez adapter zwracający `PlannerProposal`, następnie deterministyczny assembler ustalający identyfikatory i statusy; live API nie jest wymaganym testem bieżącego stubowego runtime'u.
- **M3:** `ExecutorStub`, jeden Child Task i demonstracyjny `VerificationResult`/`EvidenceRecord`. Weryfikacja obecnej odpowiedzi stuba nie stanowi niezależnego dowodu realnej edycji plików ani przejścia prawdziwych testów.
- **M4:** ograniczone retry, Workflows Human Gate, persystencja i poprawki F3/F4/F5/F8. PR #20 został scalony 17.09.2026. To nie zamyka M4 i nie usuwa automatycznie G3–G5.

M4 wykonuje tylko `TASK-001`; `TASK-002/003` pozostają PENDING. `success=true` z demonstracji nie jest dowodem realizacji całego celu. Zainstalowane modele, enumy adapterów czy 625 zaliczonych testów stuba nie dowodzą istnienia rzeczywistej pętli agenta. Operacyjny `resume`, pełny plan, Tool Broker, niezależny Verifier rzeczywistych artefaktów, Context Builder, Model Gateway i routing to zadania migracyjne.

## Jedyny kontrakt dalszego rozwoju

[Pełna architektura v1](docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md) + [późniejsze decyzje](docs/DEPLOYMENT_DECISIONS.md) + [status oparty na Git/CI](PROJECT_STATUS.md). Szczegółowe dowody i dokładne SHA: [audyt Astry](docs/reviews/FSASM_V1_ARCHITECTURE_GAP_ANALYSIS_AND_MIGRATION_PLAN_2026-09-17.md). Plan przyszłych prac: [MIGRATION_BACKLOG_V1](docs/MIGRATION_BACKLOG_V1.md). Każde zadanie wymaga osobnego zatwierdzenia.
