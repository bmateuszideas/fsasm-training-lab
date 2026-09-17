# FS-ASM — bieżący status projektu i następny punkt decyzyjny

**Migawka przygotowana 17.09.2026.** W czasie przeglądu potwierdzono `Fsasm-experimental` @ `716f4884879fd713e19bfcf5ebcc80d31b846323` (porządkowy commit po scaleniu PR #20). **To nie jest niezmienny HEAD.** Po zastosowaniu niniejszego pakietu dokumentacyjnego sprawdź faktyczny commit, PR i CI; nie przepisuj dawnych SHA jako aktualnych.

## Co zostało zatwierdzone

- Jedyna architektura docelowa: [`docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md`](docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md), bez zmian treści, SHA-256 `56aeeb60c8c700c71dc3d395659127afbf511e1726e0ffd76270c848fd764808`.
- `Fsasm-experimental` jest aktywną linią dalszej implementacji. `main` pozostaje osobną, starszą linią — bez automatycznej integracji.
- Profil Workflows: lokalny worker, workspace, kod i model ~7B Q4; chmurowa orkiestracja Mistrala dozwolona. Użytkownik akceptuje jawny transfer danych i telemetrię. Zob. [`DEPLOYMENT_DECISIONS.md`](docs/DEPLOYMENT_DECISIONS.md).
- ChatGPT + użytkownik planują/review; Mistral Vibe Code Web / GLM-5.2 jako jedyny pisze kod FS-ASM. Najpierw kompletny runtime z testowanymi atrapami; rzeczywisty 7B, a następnie dwa modele API — dopiero po przeniesieniu na laptop.
- LLMC, fine-tuning, wielowriterowy/rozproszony runtime i nowy framework pozostają poza zakresem v1. Nie zlecono automatycznie wszystkich Q1–Q12.

## Stan GitHub i testów — rozdzielić fakty

| Obszar | Fakt ze sprawdzonego stanu |
|---|---|
| PR #20 | `merged=true`, zamknięty 17.09 o 04:53:21 UTC. Kandydat `142db38079d2e15c4c65a4a3c9481bb4cdab81fd`; merge commit `f600ed210501030398740ce87006364dd78a034f`. Sam merge nie kończy M4. |
| Integracja | Po merge nastąpił commit usuwający historyczny katalog, a potem usunięcie `.vibe/README.md`; sprawdzony HEAD `716f488...` (05:29:42 UTC). Nie odtwarzaj usuniętych materiałów bez polecenia. |
| M1–M3 | Historycznie oznaczone CLOSED; nie są pełnym runtime'em. |
| M4 | Zaimplementowany demonstrator z retry/Human Gate, ale **OPEN — bez odrębnej akceptacji zamknięcia**. |
| M5 | **NOT STARTED**. Stary „M5 jest następne” nie jest bieżącym zleceniem. |
| Testy | Astra wykonała na kandydacie `142db38` 625 passed, 3 skipped, 0 failed, Ruff/mypy OK i odnotowała CI green; brak ponownego wykonania tych testów na każdym późniejszym HEAD lub na docelowym runtime v1. |

Źródło techniczne: [PR #20](https://github.com/bmateuszideas/fsasm-training-lab/pull/20); pełny datowany [audyt Astry](docs/reviews/FSASM_V1_ARCHITECTURE_GAP_ANALYSIS_AND_MIGRATION_PLAN_2026-09-17.md). Weryfikuj live dane na GitHubie.

## Co realnie robi obecny kod

Zapis stanów i projekcji ma poprawki F3/F4; w kodzie są modele Pydantic, rozdzielenie PlannerProposal/assembler, przejścia, demonstracyjna weryfikacja, retry i Workflows Human Gate. M4 wykonuje **tylko `TASK-001` deterministycznym ExecutorStub**. `TASK-002/003` pozostają PENDING; sukces demonstratora nie jest końcem planu. Evidence opakowujące odpowiedź stuba nie dowodzi prawdziwej modyfikacji pliku ani przejścia testu. `recover_run` nie jest operacyjnym `resume` kompletnego systemu.

Brakuje docelowej semantyki revision/jednego commita stanu, pełnego schedulera Parent/Child, Context Buildera, Tool Brokera z egzekwowanym scope, niezależnego Verifiera artefaktów, realnej pętli Executora, Gatewaya/adapterów, routingu, poprawnie odtwarzalnego resume i pakietu docelowego uruchomienia. To luki v1, nie dowód, że obecne poprawki M4 są bezwartościowe.

## Audyt Astry — niezamknięte kwestie

Audyt na `142db38` odtworzył komponentowo: **G3** — legacy decyzja bez `gate_id` przyjęta dla kolejnego gate; **G4** — odrzucenie `gate_id=None` błędnie przypisane bieżącej bramce; **G5** — rekord dopisany w czasie `await` flush może zostać pominięty przez kursor. Nie udowodniono pełnego naruszenia na produkcyjnym workerze; nie wolno jednak deklarować ich naprawionymi tylko na podstawie opisu scalanego PR. Reprodukcje G1 (stary stan nadpisuje nowy bez revision) i G2 (syntetyczny/stary evidence może dać PASS) dotyczą późniejszej migracji domeny i Verification.

**Decyzja przed kodem G3:** czy wycofujemy bez-ID legacy payload na granicy runtime'u i ewentualnie zapewniamy przyjazny CLI, który pobiera aktualny `gate_id` i wysyła pełne dane? To wymaga jawnej akceptacji użytkownika, nie arbitralnego wyboru Vibe.

## Jedyny najbliższy zatwierdzony zakres

Użytkownik polecił **uporządkować całą dokumentację kontekstową repo na gałęzi `Fsasm-experimental`**, tak aby Vibe czytał pełną zatwierdzoną v1 z repo, a nie wymagał przesyłania pliku w czacie. To zadanie nie zmienia `src/`, testów, milestone'ów ani `main`. Po zastosowaniu pakietu i weryfikacji jego treści następny krok to review znanych G3–G5 **na bieżącym kodzie po merge** oraz osobna decyzja o kontrakcie legacy, a dopiero potem precyzyjny task dla Vibe.

**Kolejka migracji**: [`docs/MIGRATION_BACKLOG_V1.md`](docs/MIGRATION_BACKLOG_V1.md). Bez zgody użytkownika nie zamykaj M4 i nie rozpoczynaj implementacji kolejnego punktu. Nie odtwarzaj bieżących ustaleń ze starego `CURRENT_DEVELOPMENT_ANCHOR.md`.
