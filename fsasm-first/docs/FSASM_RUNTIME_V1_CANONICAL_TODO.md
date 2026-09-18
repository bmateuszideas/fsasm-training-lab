# FS-ASM Runtime v1 Canonical Implementation TODO

> **Dla MistralVibeCodeweb:** realizować wyłącznie jeden jawnie zatwierdzony task naraz. Kroki używają pól wyboru `- [ ]`. Następny task nie jest automatycznie autoryzowany przez ukończenie poprzedniego.

**Status:** kanoniczny program wykonawczy prowadzący od obecnego demonstratora do operacyjnego FS-ASM Runtime v1 na laptopie użytkownika.

**Data ustanowienia:** 17 września 2026 r.

**Repozytorium:** `bmateuszideas/fsasm-training-lab`

**Linia integracyjna:** `Fsasm-experimental`

**Nadrzędny kontrakt:** `fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md`, SHA-256 `56aeeb60c8c700c71dc3d395659127afbf511e1726e0ffd76270c848fd764808`.

**Cel:** zbudować, zweryfikować, spakować i uruchomić na laptopie deterministyczny runtime FS-ASM v1, który wykonuje cały program Child Tasks przy użyciu lokalnego modelu około 7B Q4, realnych ograniczonych narzędzi, niezależnej weryfikacji, trwałego stanu, bounded retry, eskalacji do dwóch ról Mistral API, Human Gate i bezpiecznego resume.

**Architektura:** jeden modułowy program Python oparty na Mistral Workflows jako silniku przebiegu technicznego oraz FS-ASM Domain Core jako właścicielu znaczenia projektu. Jeden autorytatywny snapshot zawiera plan i Task Register; LLM proponuje działania, Tool Broker egzekwuje skutki, Verifier bada realne artefakty, a tylko Domain Core zatwierdza wynik. Najpierw cały system przechodzi testy z kontrolowanymi backendami, potem jest przenoszony na laptop i łączony z prawdziwymi modelami.

**Stos technologiczny:** Python 3.12+, Pydantic, `mistralai-workflows` 3.x zgodnie z lockfile, `uv`, pytest, pytest-asyncio, ruff, mypy, semgrep, JSON snapshot, izolowany workspace oraz jeden wybrany później lokalny protokół inferencji.

## 1. Rola tego dokumentu

Ten plik jest kanoniczną kolejnością wykonania, lecz nie zastępuje architektury v1. Rozstrzyga kolejność i granice prac, nie zmienia fundamentalnych decyzji architektonicznych. W razie konfliktu pierwszeństwo mają:

1. zatwierdzona architektura v1 i późniejsze jawne decyzje użytkownika;
2. ten dokument jako program kolejności;
3. aktualny kod i zweryfikowane wyniki jako stan implementacji;
4. datowane audyty jako dowody historyczne.

Samo istnienie checkboxa nie jest zgodą na rozpoczęcie pracy. Użytkownik i ChatGPT zatwierdzają task i review. Wyłącznie Mistral Vibe Code Web z GLM-5.2 zmienia kod runtime'u. Vibe nie wykonuje self-merge, nie zmienia `main`, nie zamyka milestone'u i nie rozpoczyna następnego taska bez polecenia.

## 2. Statusy i reguły przejścia

Każdy task ma jeden z pięciu statusów:

- `NOT STARTED` — nie został autoryzowany;
- `AUTHORIZED` — użytkownik zatwierdził dokładny zakres i SHA startowy;
- `IN IMPLEMENTATION` — istnieje branch lub PR wykonawczy;
- `READY FOR REVIEW` — wykonawca przedstawił kod i wymagane dowody;
- `ACCEPTED` — użytkownik zaakceptował wynik po review.

`NOT REQUIRED` wolno nadać wyłącznie taskowi warunkowemu, gdy kontrola na aktualnym SHA dowiodła, że poprawka nie jest potrzebna. `BLOCKED` oznacza udokumentowaną przeszkodę wymagającą decyzji, a nie zgodę na obejście architektury.

Task jest ukończony dopiero po akceptacji jego PR-u lub, dla prac laptopowych, po podpisaniu raportu odbiorczego. Zielony test, deklaracja Vibe i merge nie są wzajemnie zamienne.

## 3. Globalne ograniczenia

- Jeden aktywny task implementacyjny naraz, chyba że użytkownik jawnie zatwierdzi niezależność zakresów.
- Każdy task rozpoczyna się od ponownego odczytu bieżącego HEAD, otwartych PR-ów, CI i repository handoffu.
- Nowe zmiany powstają na krótkim branchu zadaniowym i w PR do `Fsasm-experimental`.
- Jeden writer na run i jeden aktywny Child Task w v1.
- Brak drugiego workflow engine, event store jako drugiego autorytetu, wielowriterowej bazy, domyślnego równoległego wykonywania tasków, obowiązkowego vector DB, LLMC, fine-tuningu, pluginu i web UI.
- Brak rzeczywistego lokalnego modelu oraz live Mistral A/B przed Gate H.
- Model nie nadaje statusu, nie zatwierdza PASS, nie zwiększa limitów i nie rozszerza scope.
- `plan.json` i widoki Markdown są wyłącznie projekcjami; nie są drugim źródłem prawdy.
- Evidence musi istnieć przed zaakceptowaną referencją w snapshotcie. Osierocone evidence nie daje PASS.
- Technical retry activity nie zwiększa `task_attempt` i nie powtarza na ślepo nieidempotentnego skutku.
- Sekrety nie trafiają do Git, evidence, logów ani fixture'ów.
- Każdy task chroni istniejące inwarianty F3, F4, F5 i F8, dopóki ich odpowiedzialność nie zostanie świadomie przeniesiona do nowej granicy.

## 4. Standard odbioru każdego taska implementacyjnego

Jeżeli specyfikacja taska nie stanowi inaczej, Vibe wykonuje i raportuje:

1. dokładny SHA startowy i końcowy;
2. reprodukcję brakującego zachowania lub czerwony test przed implementacją;
3. minimalną zmianę kodu;
4. skoncentrowany test potwierdzający naprawę;
5. `uv run pytest <testy skoncentrowane> -q`;
6. `uv run pytest`;
7. `uv run ruff check src/workflows/ src/fsasm/ tests/`;
8. `uv run ruff format --check src/workflows/ src/fsasm/ tests/`;
9. `make check`;
10. `git diff --check`;
11. listę zmienionych plików, znane ograniczenia i elementy celowo pozostawione poza zakresem.

Jeżeli aktualne repo nie obsługuje wskazanej komendy, wykonawca nie pomija jej po cichu: przedstawia dowód, proponuje najmniejszą korektę narzędzi i czeka na zgodę, jeśli zmienia to zakres taska.

---

# Część I. Implementacja kompletnego runtime'u przed laptopem

## Faza A i B. Kontrakt, aktualny baseline i odziedziczone defekty

### T00. Umieszczenie kanonicznego TODO w repo i odświeżenie handoffu

**Zależności:** zatwierdzenie tego dokumentu przez użytkownika.

**Istniejące pliki:** `AGENTS.md`, `.vibe/skills/fsasm-vibe-coding/references/repository-handoff.md`, `fsasm-first/docs/MIGRATION_BACKLOG_V1.md`.

**Nowy plik:** `fsasm-first/docs/FSASM_RUNTIME_V1_CANONICAL_TODO.md`.

- [ ] Dodać identyczną treść tego dokumentu do repo bez zmian runtime'u.
- [ ] Oznaczyć `MIGRATION_BACKLOG_V1.md` jako historyczną propozycję zastąpioną przez kanoniczne TODO, zachowując odsyłacz do audytu.
- [ ] Uaktualnić jedyny repository handoff: bieżący HEAD, PR/CI, status następnego dozwolonego taska.
- [ ] Sprawdzić wszystkie odsyłacze oraz hash kanonu architektury.

**Odbiór:** dokument istnieje w repo, aktywne instrukcje wskazują jedno TODO i jeden kanon, nie zmieniono kodu runtime'u, M4 pozostaje `OPEN`, a żaden kolejny task nie został automatycznie uruchomiony.

### T01. Niezależna reprodukcja G3, G4 i G5 na aktualnym HEAD

**Zależności:** T00 `ACCEPTED`.

**Istniejące pliki:** `src/workflows/fsasm_milestone_four.py`, `tests/test_m4_correction3_reproducers.py`, testy Human Gate.

**Produkt:** raport przypięty do SHA; bez napraw kodu produkcyjnego.

- [ ] Odtworzyć ponowne przyjęcie legacy decision bez pełnego `gate_id` po otwarciu nowej bramki.
- [ ] Sprawdzić, czy rejection powstałe bez otwartej bramki zachowuje `gate_id=None` w trwałym wpisie i kopercie.
- [ ] Użyć kontrolowanej bariery podczas `await`, aby ustalić, czy późne rejection zostaje pominięte przez kursor.
- [ ] Dla każdego G3–G5 zapisać `PRESENT`, `ABSENT` albo `INCONCLUSIVE` wraz z kodem i obserwacją.
- [ ] Nie zmieniać chronionych oczekiwań testów w celu uzyskania wyniku.

**Odbiór:** każdy przypadek ma niezależny, powtarzalny wynik na aktualnym SHA. `INCONCLUSIVE` blokuje naprawę i wymaga lepszego testu; nie jest interpretowane jako brak błędu.

### T02. Warunkowa korekta atrybucji i drain odrzuceń Human Gate

**Warunek:** T01 potwierdza G4 lub G5. Jeśli oba są `ABSENT`, oznaczyć T02 `NOT REQUIRED`.

**Pliki:** `src/workflows/fsasm_milestone_four.py`, właściwa activity persystencji, skoncentrowane testy Human Gate.

- [ ] Ustalić dokładny batch przed pierwszym `await` i potwierdzać tylko utrwalone elementy tego batcha.
- [ ] Pozostawić elementy dopisane podczas `await` do następnego drain.
- [ ] Zachować pierwotne `gate_id=None` bez przypisywania aktualnej bramki.
- [ ] Wymagać niepustych kolekcji w asercjach scenariuszy rejection.
- [ ] Udowodnić brak duplikacji w jednym wykonaniu bez deklarowania exactly-once przez crash.

**Odbiór:** G4/G5 przechodzą na tych samych reproduktorach, późne rejection nie ginie, `None` pozostaje `None`, a istniejący RETRY_ONCE/ABORT działa bez regresji.

### T03. Warunkowa korekta tożsamości zgody Human Gate

**Warunek:** T01 potwierdza G3 oraz użytkownik rozstrzyga politykę payloadów legacy. Jeśli G3 jest `ABSENT`, oznaczyć `NOT REQUIRED`.

**Rekomendacja wymagająca akceptacji:** runtime wymaga pełnych `run_id`, `task_id`, `gate_id`, `decision_id`; przyjazny klient pobiera aktualną bramkę i wysyła kompletny payload.

- [ ] Odrzucać niepełny, obcy, stary i przyszły payload bez rezerwowania bramki i bez zwiększania prób.
- [ ] Zachować first-valid-wins; duplikat tej samej decyzji nie daje drugiego uprawnienia, sprzeczna decyzja nie nadpisuje pierwszej.
- [ ] Utrzymać stabilne `decision_id` dla transportowego ponowienia tej samej decyzji.
- [ ] Zaktualizować fixture'y i instrukcje klienta zgodnie z zatwierdzoną polityką legacy.

**Odbiór:** payload gate-1 nie autoryzuje gate-2; niepełny payload nie blokuje późniejszej prawidłowej decyzji; dokładnie jedna poprawna RETRY_ONCE daje dokładnie jedną dodatkową próbę.

### Gate AB. Stabilna baza migracji

- [ ] T00–T03 są `ACCEPTED` lub warunkowe taski mają udokumentowane `NOT REQUIRED`.
- [ ] Aktualny pełny pytest i bramki jakości są zielone.
- [ ] Handoff wskazuje następny task, ale nie deklaruje M4 CLOSED ani M5 STARTED.

## Faza C. Właścicielstwo stanu

### T04. Kompletny model domenowy snapshotu

**Zależności:** Gate AB.

**Modyfikowane:** `src/fsasm/models.py`.

**Proponowane testy:** `tests/test_v1_state_models.py`.

- [ ] Dodać wersję schematu, monotoniczną `revision`, kompletny Task Register, Parent/Child, zależności, statusy, próby, aktywny task, gate, budżety oraz referencje zaakceptowanych evidence.
- [ ] Oddzielić konfigurację planu od dynamicznego stanu prób bez tworzenia drugiego autorytetu.
- [ ] Zdefiniować tożsamości `run_id`, `task_id`, `attempt`, `operation_id`, `artifact_id`, `evidence_id`, `gate_id`, `decision_id`.
- [ ] Walidować duplikaty ID, brakujące referencje, cykle, więcej niż jeden aktywny task i sprzeczne statusy.
- [ ] Nie wybierać jeszcze dokładnego formatu każdego późniejszego `ModelResponse`; model snapshotu obejmuje wyłącznie ustalone potrzeby domeny.

**Odbiór:** round-trip serializacji zachowuje cały stan; niespójny snapshot jest odrzucany; plan 1, 3 i N tasków nie jest ograniczony do historycznych trzech.

### T05. Czysty Domain Core i jedno zastosowanie zdarzeń

**Zależności:** T04.

**Modyfikowane:** `src/fsasm/transitions.py`.

**Proponowane:** `src/fsasm/domain.py`, `tests/test_v1_domain_events.py`.

- [ ] Zdefiniować jawne domenowe zdarzenia dla lifecycle run/task, attempts, verification, gate i accepted evidence.
- [ ] Wprowadzić czyste `apply_event(current_state, validated_event) -> next_state` bez I/O i bez mutacji wejścia.
- [ ] Zapewnić, że ten sam state+event daje ten sam wynik.
- [ ] Odrzucać złą tożsamość, nielegalne przejście, przekroczony limit i próbę modelowego przyznania PASS.
- [ ] Zachować wartościowe macierze przejść i limity obecnego `transitions.py`, przenosząc odpowiedzialność zamiast je kopiować.

**Odbiór:** testy domenowe dowodzą niezmienności wejścia, deterministyczności, jednego aktywnego taska i wyłącznej kontroli Domain Core nad PASS/retry/gate.

### T06. State Repository z revision i jednym atomowym commitem

**Zależności:** T05.

**Modyfikowane:** `src/fsasm/persistence.py`.

**Proponowane testy:** `tests/test_v1_state_repository.py`.

- [ ] Wprowadzić `load(run_id)` i `commit_snapshot(run_id, expected_revision, next_state)`.
- [ ] Odrzucać stale revision i niespójny `run_id`; zwiększać revision dokładnie raz na zaakceptowany event.
- [ ] Zachować atomowy zapis pojedynczego `state.json`, walidację ID, containment i rezerwację runu.
- [ ] Zapisywać `plan.json` i inne widoki wyłącznie jako odbudowywalne projekcje po commicie.
- [ ] Udowodnić przez fault injection, że awaria projekcji nie cofa autorytetu ani nie daje false PASS.
- [ ] Przed implementacją użytkownik wybiera politykę starych runów: rekomendowane read-only/archive; opcjonalny importer jest osobnym przyszłym taskiem, nie częścią resume v1.

**Odbiór:** reproduktor G1 nie może cofnąć stanu; state jest jedynym autorytetem; F3/F4/F5 pozostają zachowane.

### T07. Adaptacja activities oraz fundament start_new i resume

**Zależności:** T06.

**Modyfikowane:** `src/fsasm/executor_activities.py`, aktywny workflow, `src/entrypoints/start.py`; niskopoziomowe mutatory w `persistence.py`.

**Testy:** `tests/test_v1_activity_state_contract.py`, rozszerzone testy F3/F4.

- [ ] Activities przyjmują przede wszystkim ID, `expected_revision` i dane zdarzenia, nie kilka mutowalnych kopii State/Plan/Task.
- [ ] Każda semantyczna zmiana przechodzi przez load → apply_event → commit_snapshot.
- [ ] `start_new` rezerwuje nowy run i nie nadpisuje istniejącego celu.
- [ ] Fundament `resume` ładuje i waliduje zatwierdzony snapshot; nie obiecuje jeszcze reconcile rzeczywistych skutków narzędzi.
- [ ] Wycofać aktywne użycie publicznych `save_plan`/`save_run_state` jako niezależnych ścieżek mutacji.

**Odbiór:** nieaktualna activity nie nadpisuje nowszego stanu, retry techniczne nie dodaje `task_attempt`, a `start_new` i `resume` mają rozłączne kontrakty.

### Gate C. Jedno właścicielstwo stanu

- [ ] Jeden snapshot zawiera plan, Task Register, gate, counters i evidence refs.
- [ ] Jedna czysta operacja domenowa oraz jeden commit są aktywną ścieżką zmian.
- [ ] Kontrolowany restart na stubie wraca do zatwierdzonego snapshotu.
- [ ] Brak drugiego źródła statusów lub ukrytego workflow engine.

## Faza D. Pełny plan, rzeczywiste narzędzia i niezależny PASS

### T08. Trusted Intake i Task Compiler

**Zależności:** Gate C.

**Modyfikowane:** `src/fsasm/planner.py`, `src/fsasm/models.py`, `src/fsasm/planner_activities.py`.

**Proponowane testy:** `tests/test_v1_task_compiler.py`.

- [ ] Rozszerzyć `GoalInput` o zatwierdzone ograniczenia i maksymalny scope workspace.
- [ ] Traktować `PlannerProposal` jako niezaufane wejście semantyczne.
- [ ] Nadawać runtime-owned IDs, Parent/Child, dependencies, acceptance criteria, verification spec, limits i allowed scope.
- [ ] Odrzucać cykle, brakujące dependencies, duplikaty, przekroczenie rozmiaru planu i próbę rozszerzenia uprawnień.
- [ ] Zachować działający prompt/JSON Plannera, ale nie przepuszczać transportowych typów dostawcy do Domain Core.

**Odbiór:** propozycje planów 1/3/N kompilują się; nieprawidłowy DAG i scope spoza Intake są odrzucone przed utworzeniem runu.

### T09. Scheduler całego planu i agregacja Parent/run

**Zależności:** T08.

**Proponowane:** `src/fsasm/scheduler.py`, `tests/test_v1_scheduler.py`.

- [ ] Wybierać deterministycznie kwalifikujący się Child Task po spełnieniu dependencies.
- [ ] Utrzymywać najwyżej jeden active task.
- [ ] Rozróżniać brak gotowego taska wskutek ukończenia, blokady, cyklu/niespójności i oczekiwania na gate.
- [ ] Wyliczać Parent i run z wszystkich wymaganych Child Tasks.
- [ ] Nie pozwalać, aby PASS `TASK-001` kończył wielozadaniowy plan.

**Odbiór:** plany 1/3/N wykonują kontrolowane rezultaty we właściwej kolejności; blocked plan nie jest oznaczany jako completed.

### T10. Deterministyczne E2E pełnego planu na ExecutorStub

**Zależności:** T09.

**Proponowane:** `src/workflows/fsasm_runtime.py`, `tests/test_v1_full_plan_stub_e2e.py`.

- [ ] Utworzyć jedną docelową ścieżkę workflow korzystającą z nowego Domain Core i Schedulera.
- [ ] Przeprowadzić plan 1-, 3- i N-zadaniowy na kontrolowanych rezultatach stuba.
- [ ] Każdy Child Task przechodzi własną finalizację; planowy task „verify” nie zastępuje Verification Plane.
- [ ] Wykazać prawidłowe zakończenie, blokadę i wyczerpanie retry bez rzeczywistych tools.

**Odbiór:** cały plan, a nie pierwszy task, osiąga terminalny stan; stara ścieżka M4 nie jest jeszcze usuwana.

### T11. Tool Broker dla operacji plikowych

**Zależności:** T10.

**Proponowane:** `src/fsasm/tool_broker.py`, `tests/test_v1_tool_broker_files.py`.

- [ ] Zaimplementować funkcjonalne odpowiedniki `list_files`, `read_file`, `search_code`, `apply_patch`, `inspect_changes`.
- [ ] Egzekwować workspace root, `allowed_files`, normalizację, traversal, symlinki oraz limity rozmiaru przed skutkiem.
- [ ] Każde wywołanie ma `operation_id` i zwraca ustrukturyzowany `ToolObservation` bez nadawania PASS.
- [ ] Niedozwolony odczyt i zapis nie może wywołać częściowego skutku.
- [ ] Nie udostępniać modelowi ogólnego terminala.

**Odbiór:** dozwolony patch zmienia fixture i tworzy obserwację/diff; próby wyjścia poza scope, symlink escape i traversal są blokowane przed skutkiem.

### T12. Kontrolowane run_checks i izolacja procesów

**Zależności:** T11.

**Modyfikowane:** `src/fsasm/tool_broker.py`.

**Proponowane testy:** `tests/test_v1_tool_broker_processes.py`.

- [ ] Zdefiniować allowlistę rodzajów checks i mapowanie na zaufane argv bez shell interpolation.
- [ ] Egzekwować cwd, timeout, limit outputu, environment allowlist oraz zakaz modyfikowania obszaru poza workspace.
- [ ] Rejestrować exit code, stdout/stderr, czas, operation/artifact identity i truncation marker.
- [ ] Rozróżniać policy block, timeout, process error i negatywny wynik checku.

**Odbiór:** zaufany test działa w fixture; niedozwolona komenda, argument injection, zapis poza workspace i timeout są kontrolowanie odrzucone lub zatrzymane.

### T13. Niezależny Verifier i Evidence Plane

**Zależności:** T12.

**Modyfikowane:** `src/fsasm/verifier.py`, `src/fsasm/models.py`, finalizacja w Domain Core.

**Proponowane testy:** `tests/test_v1_verifier_artifacts.py`.

- [ ] Verifier czyta rzeczywisty diff/artefakt oraz wyniki zaufanych checks, nie deklarację Executora.
- [ ] `VerificationResult` i `EvidenceRecord` wiążą `run_id`, `task_id`, `attempt`, `operation_id`, `artifact_id` i check identity.
- [ ] Evidence jest utrwalane przed snapshotem, a snapshot przyjmuje wyłącznie integralne referencje aktualnej próby.
- [ ] Negatywny check, brak evidence, stara próba, obcy artefakt lub output „DONE” bez skutku blokuje PASS.
- [ ] Zachować i przenieść ochrony F8 do nowej granicy.

**Odbiór:** reproduktor G2 nie daje PASS; prawdziwy patch i właściwy check aktualnej próby dają PASS zatwierdzony wyłącznie przez Domain Core.

### T14. Deterministyczne E2E tools → verification → commit

**Zależności:** T13.

**Test:** `tests/test_v1_real_effects_stub_e2e.py`.

- [ ] Kontrolowany Executor modyfikuje realny fixture przez Broker.
- [ ] Verifier uruchamia realny check i zapisuje evidence.
- [ ] Domain Core zatwierdza snapshot i Scheduler przechodzi do następnego taska.
- [ ] Osobne scenariusze: fałszywa deklaracja bez zmiany, policy block, negatywny test, stare evidence i pełny sukces.

**Odbiór:** cały plan wykonuje rzeczywiste izolowane skutki i nie może osiągnąć PASS wyłącznie tekstem stuba.

### Gate D. Deterministyczny runtime wykonawczy bez LLM

- [ ] Pełny DAG jest wykonywany sekwencyjnie.
- [ ] Narzędzia mają programowo egzekwowany scope.
- [ ] PASS wynika z rzeczywistego artefaktu i checku aktualnej próby.
- [ ] Każdy accepted result ma integralne evidence refs w jednym snapshotcie.

## Faza E. Context Builder, Model Gateway i pętla Executora

### T15. Task-scoped Context Builder

**Zależności:** Gate D.

**Proponowane:** `src/fsasm/context.py`, `tests/test_v1_context_builder.py`.

- [ ] Budować `TaskContext` z objective, acceptance criteria, constraints, allowed files/tools, relevant sources/tests/decisions, poprzednich observations/verification i context budget.
- [ ] Pierwsza wersja używa jawnych ścieżek, search, symboli/importów i prostych zależności; bez obowiązkowego LLMC/vector DB.
- [ ] Rejestrować provenance wybranych fragmentów.
- [ ] Nie dołączać pliku spoza scope ani całego repo bez uzasadnionej potrzeby.
- [ ] Umożliwić modelowi dozwolony dodatkowy odczyt przez Broker.

**Odbiór:** mały kontekst wystarcza scripted backendowi do fixture, zachowuje limit i nie ujawnia niedozwolonych danych.

### T16. Provider-neutral Model Gateway i scripted backend

**Zależności:** T15.

**Proponowane:** `src/fsasm/gateway.py`, `src/fsasm/model_types.py`, `tests/test_v1_gateway_contract.py`.

- [ ] Zdefiniować request oraz odpowiedzi `ToolCall`, `FinalResponse`, `EscalationRequest`, `InvalidResponse` i znormalizowane błędy/usage.
- [ ] Zapewnić jeden interfejs `generate(messages, tools, parameters)` niezależny od dostawcy.
- [ ] Dodać deterministyczny scripted backend pozwalający zaplanować kolejne odpowiedzi i błędy.
- [ ] Wprowadzić budżety `model_call_count`, `tool_call_count`, tokenów/kosztu jeśli dostępne, czasu i agent steps.
- [ ] Parser nie może mylić błędnego formatu z udanym tool callem lub final response.

**Odbiór:** kontraktowe testy pokrywają poprawne tool calls, final, escalation, invalid response, usage oraz błędy transportu bez provider-specific typów w domenie.

### T17. Rzeczywista Executor Loop

**Zależności:** T16.

**Modyfikowane:** `src/fsasm/executor.py`, `src/fsasm/executor_activities.py`.

**Proponowane testy:** `tests/test_v1_executor_loop.py`.

- [x] Zrealizować model → Tool Broker → ToolObservation → model aż do jawnego terminalnego outcome.
- [x] W jednej `task_attempt` obsłużyć wiele `agent_step`, tool calls i model calls.
- [x] Egzekwować limity przed następnym skutkiem.
- [x] Normalizować `COMPLETED`, `NEEDS_INFORMATION`, `ESCALATION_REQUESTED`, `STEP_LIMIT_REACHED`, `TOOL_ERROR`, `POLICY_BLOCKED` lub zatwierdzone semantyczne odpowiedniki.
- [x] Final response jest prośbą o Verification, nie PASS.

**Odbiór:** scripted backend przechodzi co najmniej dwie iteracje rozdzielone realnym narzędziem; przekroczenie każdego limitu daje prawidłowy terminal reason bez niejawnej nowej próby.

### T18. Retry merytoryczne i feedback poprzedniej próby

**Zależności:** T17.

**Modyfikowane:** Domain Core, Context Builder, workflow adapter.

**Testy:** `tests/test_v1_task_retry_feedback.py`.

- [x] Negatywna Verification kończy próbę, zapisuje evidence/feedback i dopiero Domain Core decyduje o kolejnej `task_attempt`.
- [x] Context kolejnej próby zawiera konkretną poprzednią porażkę i aktualny artefakt.
- [x] Retry activity po błędzie transportu nie zwiększa `task_attempt`.
- [x] Wyczerpanie max attempts prowadzi do zatwierdzonej ścieżki eskalacji/gate, nie do nieskończonej pętli.

**Odbiór:** scenariusz FAIL → attempt 2 → PASS używa poprzedniego feedbacku; błędy transportowe i tool calls nie zużywają prób merytorycznych.

### Gate E. Pełna pętla na kontrolowanym modelu

- [x] Context jest ograniczony i ma provenance.
- [x] Gateway normalizuje odpowiedzi i usage.
- [x] Executor wykonuje wiele kroków narzędziowych w jednej próbie.
- [x] Retry merytoryczne, techniczne i agent steps są oddzielne.

## Faza F. Adaptery modeli i deterministyczna eskalacja

### T19. Adapter jednego lokalnego protokołu na fixture

**Zależności:** Gate E oraz zatwierdzony wybór protokołu, nie konkretnego modelu.

**Proponowane:** `src/fsasm/adapters/local.py`, testowy serwer/fixture i `tests/test_v1_local_adapter_contract.py`.

- [x] Wybrać jeden protokół lokalnej inferencji po porównaniu zgodności z tool callingiem, Windows/docelowym OS, streamingiem, timeoutami i metadanymi usage.
- [x] Adapter tłumaczy tylko transport i format; nie kopiuje Executor Loop ani polityk routingu.
- [x] Znormalizować tool calls, final response, invalid output, timeout i unavailable backend.
- [x] Testować na kontrolowanym serwerze/fixture bez prawdziwego 7B.

**Odbiór:** wszystkie kontraktowe scenariusze Gateway przechodzą przez adapter lokalny; brak zależności Domain Core od biblioteki serwera inferencji.

### T20. Adapter Mistral oraz role Planner, API A i API B na fixture

**Zależności:** T19.

**Proponowane:** `src/fsasm/adapters/mistral.py`, modyfikacja `planner_activities.py`, `tests/test_v1_mistral_adapter_contract.py`.

- [x] Użyć jednego transportowego adaptera Mistral z konfigurowanymi logicznymi rolami, bez zakładania konkretnych nazw modeli.
- [x] Przepodłączyć Planner do wspólnego Gateway bez zmiany własności Task Compilera.
- [x] Znormalizować tool calls, błędy, usage i rate/transport failure.
- [x] Testy nie wykonują płatnych ani live wywołań.

**Odbiór:** Planner oraz role A/B korzystają z jednego kontraktu, adapter nie zawiera retry domenowego, uprawnień ani decyzji PASS.

### T21. Model Router, consultation i handover

**Zależności:** T20 oraz zatwierdzona konfiguracja limitów logicznych.

**Proponowane:** `src/fsasm/router.py`, `tests/test_v1_model_router.py`.

- [x] Lokalny backend jest domyślny dla normalnego Child Task.
- [x] Consultation zwraca wskazówkę do kontekstu bieżącej próby bez zmiany właściciela wykonania.
- [x] Handover jawnie przypisuje task innemu adapterowi z tym samym lub węższym scope i własnym budżetem.
- [x] Ograniczyć liczbę eskalacji, koszt i dozwolone przejścia; zablokować ping-pong.
- [x] `ask_expert` nie może obchodzić scope ani dodawać prób.

**Odbiór:** testy rozróżniają consultation/handover, egzekwują limit i kończą wyczerpaną ścieżkę gate/stopem zgodnym z polityką.

### Gate F. Wymienne modele bez duplikacji agenta

- [ ] Jedna Executor Loop obsługuje scripted, local fixture i Mistral fixture.
- [ ] Adaptery nie posiadają reguł domenowych.
- [ ] Routing jest deterministyczny, limitowany i audytowalny.

## Faza G. Docelowy Human Gate i recovery

### T22. Human Gate jako trwała semantyka Domain Core

**Zależności:** Gate F.

**Modyfikowane:** modele/domain, aktywny workflow, adapter sygnałów.

**Testy:** `tests/test_v1_domain_human_gate.py`, reprezentatywne worker tests.

- [ ] Snapshot przechowuje gate occurrence, lifecycle, accepted/applied decision oraz zakres udzielonego uprawnienia.
- [ ] Workflows dostarcza i oczekuje; Domain Core waliduje i stosuje RETRY_ONCE/ABORT.
- [ ] Stara, obca, przyszła, niepełna, zduplikowana i sprzeczna decyzja nie wykonuje pracy.
- [ ] Zastosowanie decyzji i zmiana limitu/statusu są jednym eventem snapshotu; dodatkowy audit pozostaje diagnostyczny.
- [ ] Przenieść wartościowe testy M4, nie kopiować całego wewnętrznego mechanizmu słowników/kursorów.

**Odbiór:** dokładnie jedna poprawna RETRY_ONCE daje jedno uprawnienie; crash po commicie nie umożliwia ponownej aplikacji tej decyzji.

### T23. Reconcile częściowych i niepewnych skutków

**Zależności:** T22.

**Proponowane:** `src/fsasm/recovery.py`, `tests/test_v1_recovery_reconcile.py`.

- [ ] Zdefiniować checkpointy przed skutkiem, po skutku przed evidence, po evidence przed commit i po commit przed odpowiedzią activity.
- [ ] Wiązać operację z `attempt`, `operation_id`, aktualnym artefaktem i evidence refs bez tworzenia drugiego autorytatywnego event store.
- [ ] Przy resume najpierw inspekcja artefaktu i snapshotu, potem jawna decyzja verify/retry/stop.
- [ ] Nie deklarować exactly-once zewnętrznych skutków.
- [ ] Błąd transportowy nie jest automatycznie merytorycznym FAIL.

**Odbiór:** fault injection w każdym checkpointcie nie daje false PASS, nie powiela na ślepo patcha ani zgody i prowadzi do jednoznacznego bezpiecznego stanu.

### T24. Operacyjne start_new, resume, status i signal

**Zależności:** T23.

**Modyfikowane:** `src/entrypoints/start.py`, proponowane `src/entrypoints/status.py`, `resume.py`, `signal.py`; dokumentacja CLI.

**Testy:** `tests/test_v1_product_entrypoints.py`.

- [ ] Przed implementacją użytkownik zatwierdza zewnętrzny kontrakt CLI: argumenty, human/JSON output i exit codes. Rekomendacja: stabilny JSON dla automatyzacji oraz krótki human output jako osobny tryb.
- [ ] `start_new` tworzy nowy run, `resume` obsługuje istniejący, `status` tylko odczytuje, `signal` wysyła kompletną decyzję bieżącej bramki.
- [ ] Żadna komenda nie zgaduje gate, nie nadpisuje runu ani nie ujawnia sekretów.
- [ ] Status rozróżnia domenowy stan od technicznego stanu usługi Workflows.

**Odbiór:** kontraktowe testy CLI pokrywają sukces, brak runu, kolizję ID, niespójny snapshot, brak otwartej bramki i błąd usługi.

### Gate G. Bounded autonomy i bezpieczne wznowienie

- [ ] Human Gate jest częścią snapshotu, a nie ulotną zgodą workflow.
- [ ] Resume rozstrzyga niepewny skutek przed ponowieniem.
- [ ] Start/status/signal mają stabilne kontrakty produktu.
- [ ] Zakres gwarancji nie zawiera fikcyjnego exactly-once.

## Faza H. Integracja, obserwowalność, pakiet i odbiór przed laptopem

### T25. Spójne trajektorie, liczniki i redakcja sekretów

**Zależności:** Gate G.

**Modyfikowane:** wspólne modele obserwacji/evidence, logowanie i config.

**Testy:** `tests/test_v1_trajectory_integrity.py`, `tests/test_v1_secret_redaction.py`.

- [ ] Składać istniejące identyfikatory w trajektorię task → context → model call → tool call → observation → verification → evidence → state transition.
- [ ] Rejestrować backend, liczniki, czas i tokeny/koszt tylko jeśli dostępne.
- [ ] Audit/trajectory nie jest drugim źródłem PASS.
- [ ] Redagować klucze, tokeny i oznaczone sekrety z promptów, observations, stdout/stderr i raportów.
- [ ] Nie budować osobnej platformy monitoringu ani pipeline'u fine-tuningu.

**Odbiór:** trajektoria jest korelowalna i kompletna dla scenariusza E2E, a utrata pomocniczego logu nie zmienia zatwierdzonego stanu.

### T26. Pełna macierz Runtime v1 E2E na kontrolowanych backendach

**Zależności:** T25.

**Testy:** `tests/test_v1_runtime_acceptance_e2e.py` z prawdziwym testowym workerem tam, gdzie wymagany jest silnik.

- [ ] Human Goal → Planner stub → Compiler → authoritative snapshot → Scheduler → Context → Executor Loop → Broker → Verifier → Evidence → commit → następny task → cały Plan PASSED.
- [ ] FAIL → feedback → nowa próba → PASS.
- [ ] Consultation oraz jawny handover.
- [ ] Retry exhaustion → Human Gate → RETRY_ONCE i ABORT.
- [ ] Crash/resume w zdefiniowanych checkpointach.
- [ ] Próba operacji poza allowed scope.
- [ ] Fałszywy final bez skutku, stare evidence i obcy artefakt.
- [ ] Plan 1/3/N, blocked dependency i ukończenie całego Parent/run.

**Odbiór:** wszystkie scenariusze przechodzą bez prawdziwego 7B i live Mistral API; każdy terminal state ma dowód oraz właściwy reason.

### T27. Przełączenie na jeden aktywny runtime

**Zależności:** T26.

**Modyfikowane:** `src/worker.py`, discovery, entrypoints, tests i dokumentacja.

**Zakres historyczny:** `src/workflows/fsasm_milestone_one.py` do `four.py`, `hello.py`, examples.

- [ ] Ustawić docelowy FS-ASM Runtime jako standardowo rejestrowaną ścieżkę.
- [ ] Wyjąć M1–M4 z domyślnego discovery po przeniesieniu ich inwariantów; zachować historię w Git/dokumentacji.
- [ ] Oddzielić examples od worker produktu.
- [ ] Usunąć aktywne wymagania „dokładnie 3 taski” i „tylko TASK-001”, zachowując fixture trzytaskowy.
- [ ] Nie usuwać testu bezpieczeństwa bez wskazania jego następcy w nowej granicy.

**Odbiór:** standardowy worker rejestruje jeden runtime produktu; historyczne workflow nie wpływają na discovery ani aktywne kontrakty.

### T28. Pakiet instalacyjny, diagnostyka i walidacja profilu Workflows

**Zależności:** T27.

**Modyfikowane:** `pyproject.toml`, `uv.lock`, `Makefile`, `.env.example`, dokumentacja instalacji/operacji; proponowane narzędzie `doctor`.

- [ ] Zamrozić sprawdzony profil Python/Workflows w lockfile bez nieuzasadnionej aktualizacji SDK.
- [ ] Zapewnić czystą instalację przez `uv sync --frozen` lub zatwierdzony równoważny proces.
- [ ] Dodać przykładową konfigurację bez sekretów i diagnostykę: filesystem, workspace, Python, dependencies, Workflows connectivity, local backend endpoint i role modeli.
- [ ] Udokumentować profil hybrydowy: co działa lokalnie, co przechodzi przez Mistral, wymagania internetu, start worker/workflow/signal/resume oraz dane wychodzące.
- [ ] Zbudować wheel/artefakt instalacyjny i odtworzyć instalację w czystym środowisku.
- [ ] Runtime nie może wymagać Vibe ani GitHuba podczas pracy.

**Odbiór:** czysta instalacja uruchamia pełne T26 E2E; `doctor` rozpoznaje brakujące zależności bez ujawniania sekretów; dokumentacja wystarcza nowemu operatorowi.

### Gate H. Runtime kompletny i gotowy do przeniesienie

- [ ] Spełniona definicja kompletnego Runtime v1 z §40 kanonu.
- [ ] Pełny pytest, jakość, E2E, instalacja i pakiet są zaakceptowane na dokładnym SHA.
- [ ] Nie ma zależności produkcyjnej od Vibe/GitHub ani aktywnych demonstratorów M1–M4.
- [ ] Prawdziwy 7B i live Mistral A/B nadal nie były używane jako substytut testów runtime'u.
- [ ] Użytkownik akceptuje raport gotowości do laptopa.

---

# Część II. Uruchomienie i odbiór na lokalnym laptopie

## Zasada odpowiedzialności fazy I

Czynności lokalne wykonuje użytkownik z ChatGPT. Vibe Code Web nie otrzymuje dostępu do laptopa ani sekretów. Jeżeli test lokalny ujawni defekt kodu, powstaje osobny, ograniczony task dla Vibe z reproduktorem pozbawionym sekretów; po review i merge pakiet jest ponownie instalowany. Nie poprawia się kodu produktu ręcznie poza Git.

### T29. Zatwierdzenie profilu laptopa i modeli

**Zależności:** Gate H.

**Decyzje użytkownika:** docelowy OS, zasoby RAM/VRAM/CPU/GPU, jeden serwer/protokół inferencji, konkretny model około 7B Q4, role i modele Mistral A/B, limity prób/kroków/czasu/kosztu/eskalacji oraz polityka retencji workspace/evidence.

- [ ] Zebrać parametry sprzętu i systemu bez przesyłania sekretów.
- [ ] Wybrać protokół zgodny z zaimplementowanym adapterem T19; zmiana protokołu wymaga osobnego taska Vibe.
- [ ] Wybrać model pod kątem licencji, tool callingu, kontekstu, pamięci i realnego uruchomienia na sprzęcie.
- [ ] Wybrać Mistral A/B według ról consultation/handover, nie według niezweryfikowanego założenia „tańszy/lepszy”.
- [ ] Zapisać konfigurowalne wartości limitów i warunki Human Gate.

**Odbiór:** istnieje zatwierdzony profil instalacji bez kluczy i bez zmiany architektury; wszystkie wybory mają uzasadnienie oraz sposób wycofania.

### T30. Czysta instalacja FS-ASM i uruchomienie usług bazowych

**Zależności:** T29.

**Operator:** użytkownik + ChatGPT.

- [ ] Zainstalować wymagany Python, `uv`, pakiet z zaakceptowanego SHA i zależności z lockfile.
- [ ] Utworzyć strukturę workspace/project/source/runs oraz lokalną konfigurację poza Git.
- [ ] Skonfigurować konto/klucz Workflows i sprawdzić wyłącznie connectivity oraz worker lifecycle.
- [ ] Uruchomić `doctor`, worker i stubowe E2E na laptopie.
- [ ] Sprawdzić `start_new`, `status`, `signal`, `resume` i diagnostykę po restarcie procesu.

**Odbiór:** zaakceptowane stubowe E2E przechodzi na laptopie; stan i artefakty pozostają lokalnie zgodnie z profilem; brak sekretów w logach.

### T31. Instalacja serwera inferencji i smoke test lokalnego adaptera

**Zależności:** T30.

**Operator:** użytkownik + ChatGPT.

- [ ] Zainstalować wybrany serwer inferencji oraz model 7B Q4 zgodnie z licencją i zasobami.
- [ ] Powiązać endpoint wyłącznie przez lokalną konfigurację.
- [ ] Wykonać health, prostą generację, invalid response, timeout oraz przynajmniej jeden kontrolowany tool call przez rzeczywisty Gateway.
- [ ] Zmierzyć pamięć, start, latency, stabilność i maksymalny bezpieczny context budget; nie stroić jeszcze całego systemu pod benchmark.

**Odbiór:** prawdziwy model przechodzi kontraktowy smoke test adaptera i nie otrzymuje nieograniczonego terminala ani scope poza fixture.

### T32. Odbiór lokalnego 7B jako Executora FS-ASM

**Zależności:** T31.

**Operator:** użytkownik + ChatGPT.

- [ ] Uruchomić reprezentatywne małe Child Tasks: odczyt/search, kontrolowany patch, negatywny check i korekta po feedbacku.
- [ ] Każdy task przechodzi przez Broker, niezależny Verifier, evidence i state commit.
- [ ] Sprawdzić step/tool/context limits, invalid response, brak postępu i wyczerpanie prób.
- [ ] Zapisać trajektorie i wyniki bez uznawania pojedynczego sukcesu za ogólną jakość modelu.
- [ ] Skorygować jedynie konfigurację w zatwierdzonych granicach; defekt adaptera/runtime'u wraca do Vibe jako nowy task.

**Odbiór:** lokalny 7B wykonuje co najmniej jeden pełny wielozadaniowy plan z rzeczywistym skutkiem i truthful PASS; znane ograniczenia jakości są zapisane.

### T33. Live integracja Mistral API A i B

**Zależności:** T32.

**Operator:** użytkownik + ChatGPT.

- [ ] Skonfigurować klucze poza repo i sprawdzić redakcję logów.
- [ ] Wykonać kontrolowaną consultation A, w której lokalny Executor zachowuje ownership.
- [ ] Wykonać kontrolowany handover B z zachowanym scope i budżetem.
- [ ] Sprawdzić timeout, rate/transport failure, limit eskalacji i brak ping-ponga.
- [ ] Potwierdzić zapisy usage/kosztu, jeśli API je udostępnia.

**Odbiór:** obie role przechodzą realne testy bez omijania Brokera/Verifiera; wyczerpana lub niedostępna eskalacja prowadzi do zatwierdzonego gate/stop.

### T34. Końcowy odbiór operacyjny Runtime v1 na laptopie

**Zależności:** T33.

**Operator:** użytkownik + ChatGPT; wynik zatwierdza użytkownik.

- [ ] Wykonać cały realny scenariusz: Human Goal → Planner → Compiler → wielozadaniowy plan → lokalny Executor → tools → Verification → retry → consultation/handover → Human Gate → resume → terminal.
- [ ] Wymusić restart procesu przed skutkiem, po skutku przed commitem i po commicie przed odpowiedzią activity.
- [ ] Potwierdzić brak nadpisania runu, brak replay starej zgody i brak false PASS.
- [ ] Potwierdzić backup/odtworzenie workspace oraz czytelność state/evidence po ponownym uruchomieniu.
- [ ] Sprawdzić, że normalna praca nie wymaga Vibe ani GitHuba, a wymagania sieciowe Workflows/Mistral odpowiadają zatwierdzonemu profilowi.
- [ ] Utworzyć raport końcowy z wersją kodu, konfiguracją bez sekretów, modelami, wynikami, limitami i znanymi ograniczeniami.

**Odbiór końcowy:** użytkownik jawnie zatwierdza status `FS-ASM Runtime v1 OPERATIONAL ON LAPTOP`. Dopiero ten punkt oznacza pełne osiągnięcie celu niniejszego TODO. Nie oznacza ukończenia przyszłych benchmarków, LLMC, fine-tuningu, web UI ani v2.

---

## 5. Macierz bramek

| Bramka | Co jest prawdą | Czego jeszcze nie wolno twierdzić |
|---|---|---|
| Gate AB | Baza i Human Gate demonstratora są niezależnie ocenione | Zgodności runtime'u z v1 |
| Gate C | Jeden snapshot, Domain Core, revision i fundament start/resume | Pełnego planu i realnych tools |
| Gate D | Cały plan wykonuje realne izolowane skutki z truthful PASS | Rzeczywistej agentowej pętli |
| Gate E | Executor Loop działa na kontrolowanym modelu | Gotowości produkcyjnych adapterów |
| Gate F | Adaptery i routing działają na fixture'ach | Jakości lub dostępności realnych modeli |
| Gate G | Human Gate i recovery są trwałe i ograniczone | Instalowalności na docelowym laptopie |
| Gate H | Kompletny runtime jest spakowany i przyjęty przed laptopem | Operacyjności prawdziwego 7B/Mistral A/B |
| T34 | Pełny runtime działa z prawdziwymi modelami na laptopie | Funkcji poza zakresem v1 |

## 6. Otwarte decyzje przypisane do konkretnych tasków

Nie są lukami planu; są celowo odroczonymi decyzjami z określonym momentem rozstrzygnięcia:

| Decyzja | Moment | Domyślna rekomendacja, nie wymaganie |
|---|---|---|
| Payload legacy Human Gate | przed T03 | pełne ID wymagane na granicy runtime'u |
| Stare runy | przed T06 | read-only/archive; importer tylko przy realnej potrzebie |
| CLI output i exit codes | przed T24 | stabilny JSON plus osobny human mode |
| Lokalny protokół | przed T19, potwierdzenie T29 | jeden protokół zgodny z docelowym OS i tool callingiem |
| Konkretne budżety | przed T21/T29 | konserwatywne wartości konfigurowalne |
| OS, model 7B Q4 i Mistral A/B | T29 | wybór po Gate H na podstawie sprzętu i dostępnych modeli |

## 7. Raport końcowy każdego taska

Raport Vibe lub operatora musi zawierać:

- identyfikator taska;
- status i dokładne SHA/pakiet;
- wykonane zmiany lub operacje;
- czerwony dowód przed i zielony dowód po, jeśli dotyczy;
- uruchomione komendy i ich wyniki;
- dowody kryteriów odbioru;
- znane ograniczenia i odstępstwa;
- potwierdzenie braku działań poza zakresem;
- rekomendację `READY FOR REVIEW`, `BLOCKED` albo `FAILED`, nigdy samodzielne `ACCEPTED`.

## 8. Definicja pełnego zakończenia

Lista jest ukończona wyłącznie wtedy, gdy T34 został zaakceptowany. Wtedy FS-ASM:

- przechowuje program, stan, scope, decyzje i wyniki poza LLM-em;
- wykonuje cały plan, nie wyłącznie `TASK-001`;
- używa ograniczonego kontekstu i jednej wymiennej Executor Loop;
- wykonuje realne operacje tylko przez Tool Broker;
- nadaje PASS wyłącznie po niezależnej weryfikacji aktualnego artefaktu;
- ma jeden wersjonowany snapshot i bezpieczne `start_new/resume`;
- rozdziela task retry, agent steps, technical retry i eskalację;
- ogranicza consultation/handover, retry, tools, czas i koszt;
- wiąże Human Gate z właściwym run/task/gate/decision;
- działa na laptopie z rzeczywistym lokalnym 7B Q4 i dwiema skonfigurowanymi rolami Mistral API;
- nie wymaga Vibe ani GitHuba do normalnej pracy;
- uczciwie dokumentuje wymagane usługi sieciowe i granice gwarancji.
