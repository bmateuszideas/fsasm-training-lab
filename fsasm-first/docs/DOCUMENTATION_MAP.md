# FS-ASM — mapa dokumentacji i zasady kolizji

**Aktualizacja 17.09.2026.** Dokument porządkuje źródła; sam nie zatwierdza nowych decyzji.

| Źródło | Znaczenie i autorytet |
|---|---|
| [`FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md`](FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md) | **Jedyny zatwierdzony dokument docelowy.** Wierna kopia projektu ChatGPT, sprawdzić SHA-256 `56aeeb60c8c700c71dc3d395659127afbf511e1726e0ffd76270c848fd764808`. |
| [`DEPLOYMENT_DECISIONS.md`](DEPLOYMENT_DECISIONS.md) | Późniejsze jawne decyzje użytkownika, nie zmiana treści v1. |
| [`PROJECT_STATUS.md`](../PROJECT_STATUS.md) | Aktualizowany datowany stan decyzji, milestone'ów, PR i braków. Sprawdzaj bieżący Git/CI. |
| [`MIGRATION_BACKLOG_V1.md`](MIGRATION_BACKLOG_V1.md) | Uporządkowana kolejka do osobnej akceptacji; nie pozwolenie na implementację. |
| [`ARCHITECTURE_V1_BRIEF.md`](ARCHITECTURE_V1_BRIEF.md) | Krótki indeks pełnej architektury; **nie** źródło nadrzędne. |
| Root [`AGENTS.md`](../../AGENTS.md), lokalny [`AGENTS.md`](../AGENTS.md), [`BRANCH_POLICY.md`](BRANCH_POLICY.md) | Nawigacja, kontrakt agenta, procedura Git. Nie modyfikują v1. |
| Repo `README.md`, `fsasm-first/README.md` | Opis i instalacja, nie dowód wykonanej funkcji. |
| [`CURRENT_FSASM_MODEL.md`](CURRENT_FSASM_MODEL.md) | Starszy model koncepcyjny; oryginalną wersję przechowuje Git history. Nie jest równorzędny z v1. |
| [`CURRENT_DEVELOPMENT_ANCHOR.md`](../CURRENT_DEVELOPMENT_ANCHOR.md), [`IMPLEMENTATION_SUMMARY.md`](../IMPLEMENTATION_SUMMARY.md) | Archiwalne migawki M1–M4; nie są aktywnymi poleceniami. |
| [`reviews/FSASM_V1_ARCHITECTURE_GAP_ANALYSIS_AND_MIGRATION_PLAN_2026-09-17.md`](reviews/FSASM_V1_ARCHITECTURE_GAP_ANALYSIS_AND_MIGRATION_PLAN_2026-09-17.md) | Pełny raport Astry: analiza konkretnego SHA; testy/reprodukcje tylko w zadeklarowanym zakresie. |
| `.vibe/skills/fsasm-vibe-coding/` | Metoda pracy **zewnętrznego** Vibe; nie jest FS-ASM Runtime. |
| `.agents/skills/workflows/` | Dostarczone referencje Mistral Workflows SDK, nie decyzje projektowe. |

**Interpretacja:** zamiar i docelowa budowa → pełna v1; szczegółowy profil → jawne późniejsze decyzje; fakty implementacji → kod/artefakty/testy na SHA; zatwierdzenie prac → polecenie użytkownika; historia → commit i datowany audyt. Nie wybieraj arbitralnie najdłuższego lub najnowszego dokumentu. W razie rzeczywistego konfliktu przedstaw dowód i zatrzymaj sprzeczną zmianę.

Przy sesji bez kontekstu: pełna v1 (również rozdziały XIX–XX) → decyzje → status → zadanie → zakres kodu/tests. Sesyjny handoff: branch i SHA, cel, zmienione ścieżki, testy i ograniczenia. Nie twórz równoległego „bieżącego stanu” w skillach, anchorach ani README. Nie przywracaj usuniętych katalogów historii jako środka do rozwiązania konfliktu kontekstu.
