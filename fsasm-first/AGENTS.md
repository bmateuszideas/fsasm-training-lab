# FS-ASM — kontrakt implementacyjny dla Vibe Code Web

**Nadrzędny dokument:** [`docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md`](docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md), pełna zatwierdzona architektura v1. Przeczytaj ją w całości. Jej przykłady są ilustracjami, a otwarte parametry nie stanowią zgody na arbitralne wybory. Doprecyzowanie późniejsze: [DEPLOYMENT_DECISIONS.md](docs/DEPLOYMENT_DECISIONS.md). Nie traktuj tego AGENTS jako drugiej architektury.

## Przed kodowaniem

1. Sprawdź HEAD `Fsasm-experimental`, aktualne branche i PR-y oraz CI. Historyczne `142db38`, `f600ed2`, `716f488` są punktami odniesienia, nie bieżącymi refami.
2. Odczytaj [PROJECT_STATUS](PROJECT_STATUS.md), [mapę dokumentacji](docs/DOCUMENTATION_MAP.md), [politykę branchy](docs/BRANCH_POLICY.md) i aktualne polecenie użytkownika. Nie realizuj backlogu w całości z własnej inicjatywy.
3. Dla zmian w SDK Workflows odczytaj `.agents/skills/workflows/SKILL.md` i odpowiednie referencje. `src/examples/` pozostaje zbiorem przykładów dostawcy, a nie architekturą FS-ASM.
4. Zanim zmienisz kod, zinwentaryzuj tylko bezpośrednio istotne moduły, granice danych i testy. Nazwij istniejące zachowanie, defekt, kryterium odbioru i zakres wyłączony.

## Rzeczywisty podział odpowiedzialności

- **Mistral Workflows:** techniczne activities, czekanie, sygnały i historia procesu; nie ustala, czy Child Task jest merytorycznie PASSED.
- **FS-ASM Domain Core:** stan i jego przejścia, ograniczenia, zależności, dopuszczenie retry, routing i autoryzacja. Jeden autorytatywny snapshot runu z planem/Task Register, revision i jednym punktem commit. `plan.json` może być wyłącznie projekcją.
- **Planner / Task Compiler:** semantyczna propozycja modelu versus walidacja i nadanie ID/statusów przez kod. Nie utrzymuj sztywnego limitu trzech zadań jako wymogu docelowego; to wyłącznie fixture/historyczny eksperyment.
- **Context Builder:** mały kontekst pojedynczego Child Task, początkowo zwykła nawigacja po ścieżkach/kodzie, bez obowiązkowego LLMC/wektorowej bazy.
- **Executor:** ograniczona pętla model → Tool Broker → rzeczywista obserwacja → model, a nie jednorazowy tekst `DONE`. Tool Broker kodem egzekwuje `allowed_files`, zakres operacji i narzędzia.
- **Verifier / Evidence:** obserwuje rzeczywisty artefakt, test/diff/check i wiąże wynik z run/task/attempt. Model ani `ExecutorStub` nie nadają PASS. Evidence musi istnieć, zanim stan powiąże je z PASSED.
- **Model Gateway:** wymienne adaptery; główny model lokalny ~7B Q4 i dwa modele Mistral API do późniejszej eskalacji. Vibe Web jest narzędziem BUDOWY, nie backendem działającego FS-ASM.
- **Reliability:** rozdziel start_new/resume, task attempts od technical activity retries. Nie obiecuj exactly-once dla zewnętrznych skutków, transakcji wielu plików ani działania offline. Jeden writer/run i sekwencyjne zadania w v1.

## Zakres implementacji i weryfikacji

Nie pisz kodu przed otrzymaniem jednego precyzyjnego i zaakceptowanego tasku. Otwarty backlog nie jest pozwoleniem. Nie przenoś bez przeglądu starych M1–M4 do nowego rdzenia; zachowaj sprawdzone zabezpieczenia F3/F4/F5/F8 i ich odpowiednie testy, ale nie buduj drugiego silnika workflow. G3–G5 z audytu są problemami do osobnej korekty, nie dowodem, że cała ścieżka produkcyjna została skompromitowana. Los legacy sygnałów bez `gate_id` wymaga decyzji użytkownika.

Wykonanie docelowego runtime'u z modelami rzeczywistymi nastąpi **po** ukończeniu testów całego systemu na scripted/fake backendach i przeniesieniu projektu na laptop. Nie próbuj korzystać z lokalnego modelu użytkownika ani tunelować się z Vibe. Fine-tuning, LLMC, neuralne MoE, UI, rozproszone workery i drugi framework pozostają poza zakresem v1.

Zmiany kodu: wąski task branch od aktualnego `Fsasm-experimental`, PR do niego, niezależny review i jawna zgoda przed merge. Używaj izolowanego katalogu testowego; nie usuwaj wartościowych `runtime/` danych. Uruchom adekwatne testy, `make check` i sprawdź diff. Nie deklaruj testu live, którego nie było, ani zamknięcia M4 bez zgody. Zakończ wynikiem ze SHA, dowodami, ograniczeniami i next step; nie uruchamiaj następnego tasku samodzielnie.
