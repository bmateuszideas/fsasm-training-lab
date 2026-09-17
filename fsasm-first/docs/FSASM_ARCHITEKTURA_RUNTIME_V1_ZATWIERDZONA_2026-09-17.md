# FS-ASM — architektura docelowa runtime'u v1

**Status:** ZATWIERDZONA ARCHITEKTURA — decyzja użytkownika w projekcie ChatGPT FS-ASM, 17 września 2026 r.  
**Wersja dokumentu:** 1.0 — pełny zapis zatwierdzonej propozycji architektury.  
**Charakter:** kanoniczny kontrakt *kierunku architektonicznego*, nie raport o tym, co obecny kod już implementuje.  
**Projekt:** FS-ASM / File System as State Machine; w materiałach występuje także rozwinięcie „File System As State Memory”, akcentujące trwałą pamięć stanu. Niniejszy dokument nie rozstrzyga historycznej nomenklatury przez zmianę nazwy repozytorium.  
**Środowisko planowania:** użytkownik + ChatGPT w projekcie FS-ASM.  
**Jedyny wykonawca prac programistycznych:** Mistral Vibe Code Web, model GLM-5.2.  
**Docelowe miejsce działania runtime'u:** komputer użytkownika, po ukończeniu implementacji i przeniesieniu kodu.  
**Status wdrożenia:** architektura zatwierdzona; nie oznacza, że została wdrożona w repozytorium, że M4 zostało zaakceptowane, że M5 rozpoczęto lub że runtime jest gotowy.

> **Zasada nadrzędna:** model może utracić kontekst, zostać wymieniony lub zakończyć sesję. FS-ASM zachowuje program zadań, stan, uprawnienia i wyniki poza modelem, aby kolejny model mógł bezpiecznie kontynuować pracę. Jeżeli coś można jednoznacznie rozstrzygnąć kodem, nie delegujemy tego do LLM-a.

---

## 0. Znaczenie, zakres i hierarchia tego dokumentu

Ten plik scala **całą zatwierdzoną w rozmowie propozycję**, łącznie z jej dokończeniem: definicję FS-ASM, rozdzielenie środowisk, warstwy systemu, odpowiedzialności, persystencję, wznowienie, Planner, Task Compiler, model danych, scheduler, Context Builder, pętlę Executora, adaptery modeli, narzędzia, Verification i Evidence, routing, Human Gate, obserwowalność, późniejszy fine-tuning, docelowe uruchomienie, migrację oraz definicję ukończenia v1.

**Priorytet interpretacyjny:** (1) zatwierdzona architektura v1 i późniejsze *jawne* decyzje użytkownika; (2) obecny kod i faktycznie sprawdzone wyniki testów jako informacja o implementacji; (3) wcześniej uzgodniony model `CURRENT_FSASM_MODEL.md` jako źródło genezy i celu; (4) datowane audyty i dokumenty historyczne jako materiał dowodowy. Starszy plan etapów, nazwy milestone'ów i techniczne rekomendacje z audytu nie mogą automatycznie unieważniać nowszej decyzji.

**Rozróżnienie statusów:** „zatwierdzone” odnosi się do architektury; „zaimplementowane” wymaga przeglądu kodu; „zweryfikowane” wymaga odpowiedniego dowodu; „ukończone” wymaga akceptacji użytkownika. Nie wolno tych pojęć zamieniać.

**Nierozstrzygnięte szczegóły:** konkretny lokalny model i serwer inferencyjny, tożsamość dwóch modeli Mistral API, dokładny format wewnętrznej serializacji, polityki budżetowe w liczbach, zgodność używanej wersji Workflows z wymaganym docelowym trybem uruchomienia i szczegółowe mapowanie nowych modułów do istniejącego kodu. Nie wolno interpretować ilustracyjnych przykładów w dokumencie jako niejawnego zatwierdzenia tych parametrów.

---

# I. Definicja, geneza i nienaruszalna teza

## 1. Co budujemy

FS-ASM to **deterministyczny runtime organizujący i kontrolujący pracę wymiennych modeli językowych nad projektami**, korzystający z trwałego programu zadań, ograniczonego kontekstu, egzekwowanych programowo uprawnień, narzędzi, niezależnej weryfikacji i pamięci poza oknem kontekstowym modelu.

Nie budujemy nowego LLM-a, klona Vibe Code, dokumentacyjnej metodologii pozbawionej wykonania, nowego ogólnego frameworka agentowego ani sieci swobodnie korespondujących modeli. Wieloagentowość to **logiczne role z jasnymi kontraktami**; role mogą używać tego samego modelu lub różnych modeli, nie potrzebują tylu odrębnych usług.

## 2. Problem źródłowy

Pierwsze FS-ASM powstało z potrzeby utrzymania ciągłości długiego projektu programistycznego, kiedy Codex w VS Code gubił wcześniejsze ustalenia, zmieniał lokalne elementy bez uwzględnienia zależności i nie potrafił bezpiecznie dokończyć procesu. Użytkownik i ChatGPT przygotowywali plan, instrukcje i `TODO`; Codex wykonywał pracę; człowiek ręcznie przekazywał kontekst. Pliki były jednocześnie pamięcią, programem, rejestrem stanu i kanałem handoffu.

Rdzeń historyczny — **`TODO as Code`** — oznaczał plan jako program małych, jednoznacznych Child Tasks, a nie luźną listę życzeń. Jeden krok miał zakres, weryfikację, wynik i jawny stan. Przejście do kolejnego następowało dopiero po odpowiednim sprawdzeniu.

Współczesny runtime automatyzuje dawny ręczny handoff. Nie implementujemy literalnie całego historycznego v7: zachowujemy funkcję mechanizmów, nie tekstowe rytuały i niezaimplementowane obietnice.

## 3. Niezmienniki najwyższego poziomu

1. **Stan jest poza LLM-em** i jest możliwy do odczytania przez nową instancję modelu.
2. **LLM proponuje, kod rozstrzyga.** Model nie nadaje statusów, nie zatwierdza własnego PASS, nie poszerza uprawnień i nie zmienia limitów autonomii.
3. **Praca jest rozbita na Child Tasks**, o kontrolowanych zależnościach i weryfikowalnych kryteriach.
4. **Model ma mały, zadaniowy kontekst.** Nie musi odtwarzać całej architektury ani pełnej rozmowy.
5. **Wykonanie daje obserwowalny skutek**, a Verification opiera się na niezależnych artefaktach, nie na deklaracji Executora.
6. **Wznowienie i wymiana modelu są elementami kontraktu**, nie wyłącznie oczekiwaniem względem promptu.
7. **Autonomia jest ograniczona** liczbą kroków, prób, narzędzi, zakresem plików, czasem i budżetem.
8. **Komponenty modelowe są wymienne**; runtime pozostaje możliwie niezależny od ich API i od szczegółów pojedynczego frameworka, bez przepisywania Mistral Workflows.

---

# II. Dwa oddzielne środowiska i zasady pracy nad projektem

## 4. Środowisko deweloperskie — budowa FS-ASM

```text
UŻYTKOWNIK + CHATGPT (projekt FS-ASM)
  architektura → decyzje → precyzyjne zadania → review
                         ↓
MISTRAL VIBE CODE WEB / GLM-5.2
  jedyny agent piszący i zmieniający kod runtime'u
                         ↓
GITHUB
  kod podczas rozwoju, historia, branche, PR-y, CI
                         ↓
GOTOWA IMPLEMENTACJA → KOMPUTER UŻYTKOWNIKA
```

- ChatGPT w tym projekcie planuje, tworzy kontrakty, przygotowuje zadania dla Vibe i przegląda rezultaty. **Nie koduje autonomicznie w repozytorium** i nie scala PR-ów bez odrębnego polecenia.
- Vibe Code Web z GLM-5.2 implementuje kod na podstawie przekazanego zadania. Może testować w chmurowym sandboxie, korzystając z fixture'ów, stubów i symulowanych backendów.
- GitHub jest środowiskiem rozwoju i nośnikiem kodu **na czas budowania**, nie wymaganym elementem działającego FS-ASM.
- Vibe **nie jest** Plannerem, Executorem, runtime'em ani modelem eskalacyjnym FS-ASM; jest zewnętrznym agentem **budującym** ten system.
- Aktualny otwarty PR/milestone ma własny status. Sama akceptacja architektury nie autoryzuje jego merge, nie rozpoczyna M5 i nie oznacza zmiany `main`.

## 5. Środowisko docelowe — uruchomienie FS-ASM

Po ukończeniu kodu projekt jest przenoszony na komputer użytkownika: runtime, konfiguracja, wymagane zależności i workspace. Tam użytkownik uruchomi **całość** z lokalnym modelem ok. 7B w kwantyzacji Q4 oraz skonfigurowanym dostępem do dwóch modeli przez swoje Mistral API.

**Kolejność jest wymagana:** najpierw programujemy i sprawdzamy kompletny runtime bez rzeczywistego lokalnego LLM-a; dopiero po przeniesieniu na laptop następuje integracja i testy rzeczywistego lokalnego modelu, potem uruchomienie eskalacji przez Mistral API. Nie zlecamy chmurowemu Vibe testowania laptopowego `localhost` ani benchmarkowania niegotowego systemu z 7B.

**Otwarta weryfikacja technologiczna:** przed uznaniem runtime'u za gotowy do przeniesienia trzeba ustalić, jakie elementy używanej wersji Mistral Workflows mogą działać na lokalnym komputerze i jakie ewentualnie wymagają zewnętrznej usługi. Lokalny worker i lokalna inferencja nie są automatycznie gwarancją pełnego offline. Tego nie należy zgadywać ani maskować niepotrzebną infrastrukturą sieciową.

---

# III. Architektura logiczna — całość i podział ról

## 6. Schemat

```text
HUMAN GOAL / wymagania / ograniczenia
                 │
                 ▼
INTAKE → PLANNER → TASK COMPILER → WALIDACJA PLANU
                 │
                 ▼
      FS-ASM CONTROL PLANE
   Mistral Workflows + Domain Core
  scheduler / transitions / retry / Human Gate / routing
                 │
       ┌─────────┴─────────┐
       ▼                   ▼
PERSISTENT MEMORY     CONTEXT BUILDER
 Project + Run State  task-scoped retrieval
       │                   │
       └─────────┬─────────┘
                 ▼
          EXECUTION PLANE
      Model Gateway + Executor Loop
                 │
        LOCAL 7B Q4 [domyślnie]
                 │
         MODEL → TOOL BROKER
                 ▲         │
                 └─ obserwacja
                 │
        ┌────────┴───────────┐
        ▼                    ▼
  MISTRAL API A        MISTRAL API B
 konsultacja/ekspert  trudniejsze wykonanie
        └────────┬───────────┘
                 ▼
        INDEPENDENT VERIFIER
        realne artefakty / testy
                 │
                 ▼
     EVIDENCE → STATE COMMIT
                 │
         kolejny Child Task
         lub koniec planu
```

Diagram przedstawia **odpowiedzialności logiczne**, nie nakaz budowania osobnych mikroserwisów, ośmiu agentów ani nowego frameworka. Wersja v1 ma być jednym rozsądnie modułowym programem Python, używającym Workflows tam, gdzie Workflows już rozwiązuje problem.

## 7. Macierz właścicielstwa

| Obszar | Właściciel | Czego nie robi |
|---|---|---|
| Techniczne uruchamianie activities, oczekiwanie, historia wykonania | Mistral Workflows | Nie interpretuje semantyki PASS zadania |
| Reguły domenowe, statusy, limity, przejścia | FS-ASM Domain Core | Nie implementuje drugiego silnika workflow |
| Wybór kwalifikującego się Child Task | FS-ASM Scheduler | Nie zleca sobie nowych celów poza planem |
| Trwały stan runu | FS-ASM Persistence | Nie utrzymuje drugiej autorytatywnej kopii `plan.json` |
| Trwała pamięć i pliki projektu | Workspace / Project Memory | Nie zastępują technicznej historii Workflows |
| Propozycja planu | Planner | Nie nadaje autorytatywnych statusów i ID wykonawczych |
| Kompilacja/akceptacja planu | Task Compiler | Nie przyjmuje bezkrytycznie propozycji modelu |
| Dobór danych dla pojedynczego zadania | Context Builder | Nie wkłada całego repo do promptu |
| Wybór modelu i egzekwowanie polityki eskalacji | Model Router | Nie deleguje sam sobie polityki do LLM-a |
| Komunikacja z backendem LLM | Model Adapter | Nie duplikuje pętli agentowej |
| Proponowanie kolejnych działań | Executor LLM | Nie wykonuje bezpośrednio dowolnego kodu ani nie przyznaje PASS |
| Egzekwowanie scope i operacji narzędziowych | Tool Broker | Nie ufa samej instrukcji `allowed_files` w promptcie |
| Ustalenie wyniku na podstawie skutków pracy | Verifier + Domain Core | Nie ufa deklaracji „DONE” |
| Decyzje wymagające uprawnionego człowieka | Human Gate + użytkownik | Nie interpretuje starego sygnału jako nowej zgody |

## 8. Granica Workflows ↔ FS-ASM

Mistral Workflows odpowiada za **przebieg procesu**: wywołania activities, oczekiwania, dostarczanie sygnałów i retry techniczne w określonym zakresie. FS-ASM jest właścicielem **znaczenia projektu**: zależności między taskami, statusów domenowych, decyzji o dopuszczalnym retry, uprawnień i kryteriów zakończenia. Retry techniczne po błędzie transportu nie może samoczynnie zwiększać licznika merytorycznych prób zadania ani niekontrolowanie powtarzać nieidempotentnej zmiany plików.

Nie budujemy równoległego „workflow engine” w FS-ASM. Jednocześnie sama historia silnika nie zastępuje przenośnej, zatwierdzonej pamięci projektu.

---

# IV. Stan, pamięć, persystencja i źródło prawdy

## 9. Trzy różne znaczenia stanu

| Pojęcie | Zakres | Przykłady |
|---|---|---|
| **Project Memory** | Wiedza trwała między uruchomieniami | wymagania, architektura, decyzje, kod, notatki projektowe |
| **Run State** | Autorytatywny stan konkretnego uruchomienia | plan, rejestr zadań, próby, statusy, zaakceptowane evidence |
| **Workflow History** | Historia technicznego przebiegu zarządzana przez silnik | aktywności, oczekiwania, techniczne wznowienia |

Te warstwy współpracują, ale **nie są trzema równorzędnymi źródłami prawdy o jednym statusie**. Po zakończeniu jednej sesji LLM-a nowa może odczytać Project Memory i Run State. Nie wymaga historii poprzedniej rozmowy.

## 10. Jeden autorytatywny snapshot na run

Zatwierdzona decyzja kierunkowa: **jeden `state.json` (lub równoważny pojedynczy autorytatywny snapshot) zawiera także plan, Task Register, statusy, liczniki i referencje do zaakceptowanych dowodów.** Nie utrzymujemy niezależnego `plan.json` jako drugiego zapisywalnego rejestru stanu. Ewentualne `plan.json`, `task_register.json` lub widoki Markdown mają charakter odtwarzalnych projekcji.

Przykładowy układ na komputerze:

```text
workspace/
├── project/
│   ├── project_spec.md
│   ├── architecture.md
│   ├── decisions.jsonl
│   └── roadmap.md
├── source/
│   └── ... pliki projektu, nad którym pracuje agent
└── runs/
    └── run-001/
        ├── state.json                 # autorytatywny snapshot runu
        ├── evidence/                  # rzeczywiste dowody
        ├── observations/              # obserwacje narzędzi i prób
        └── artifacts/                 # wytworzone rezultaty
```

Struktura jest logicznym wzorcem, nie arbitralnym nakazem przemianowania wszystkich obecnych folderów. Zawartość i nazwy plików mogą zostać dopracowane przez mapę migracji, ale **jedno źródło prawdy jest obowiązkowe**.

### 10.1. Wymogi snapshotu

- Plan, stan zadań i zależności tworzą jeden spójny obiekt.
- Stan ma `run_id` i monotoniczną `revision` lub równoważny licznik wersji.
- Jeden writer na run w v1; nie deklarujemy równoległych wielu writerów.
- Zapis kompletnego snapshotu następuje atomowo na poziomie pojedynczego pliku, z walidacją przed zatwierdzeniem.
- `plan.json` jako eksport nie może być czytany jako alternatywny autorytatywny stan.
- Activity otrzymuje przede wszystkim ID i oczekiwaną wersję; **nie otrzymuje kilku mutowalnych kopii `RunState`, `Plan`, `ChildTask`, które musi ręcznie uzgadniać**.
- Identyfikatory wykorzystywane w ścieżkach muszą przejść jednoznaczną walidację przed użyciem.

## 11. Jedna operacja zmiany stanu

Koncepcyjny kontrakt (pseudokod, nie instrukcja implementacji 1:1):

```python
next_state = apply_event(current_state, validated_event)
commit_snapshot(run_id, expected_revision, next_state)
```

Sekwencja:

```text
read authoritative state
 → validate run/revision/event
 → enforce domain transition
 → create complete next state
 → commit one snapshot
 → return committed revision
```

Reguły nie mogą być rozproszone w activity tak, aby każda z nich ręcznie zmieniała status w `state.plan`, osobnym `plan`, `ChildTask` i dwóch plikach. Zachowujemy czysty, możliwy do testowania rdzeń domenowy i pojedynczy punkt zatwierdzenia.

## 12. Evidence i zatwierdzanie — granica transakcji

```text
Tool/Executor powoduje skutek
          ↓
Verifier niezależnie bada skutek
          ↓
Zapis evidence i odniesienia do artefaktu
          ↓
Jedno zatwierdzenie snapshotu Run State
          ↓
Zadanie otrzymuje PASSED
```

**Evidence przed referencją w zatwierdzonym stanie.** Jeśli evidence powstało, ale snapshot nie został zatwierdzony, mamy ewentualnie osierocony dowód, lecz zadanie **nie** otrzymuje PASS. Jeśli snapshot wskazuje zaakceptowane evidence, trzeba móc je odnaleźć i sprawdzić integralność. Przyjęta architektura nie obiecuje wieloplikowej transakcji atomowej między plikami, procesem testowym i historią Workflows.

Log audytowy nie jest drugim źródłem statusu. Dopuszczalny jest oddzielny, możliwie append-only zapis zdarzeń diagnostycznych, ale określenie „append-only” musi odpowiadać faktycznemu sposobowi zapisu; sama nazwa nie tworzy gwarancji trwałości lub współbieżności.

---

# V. Niezawodność, start i wznowienie

## 13. Jawna granica gwarancji v1

Gwarantujemy **jednoznaczność zatwierdzonego stanu**, rozsądne wykrywanie przerwanych operacji, niejawne nienadpisywanie istniejących runów oraz ograniczenia autoryzacji. **Nie deklarujemy exactly-once wykonania dowolnego działania zewnętrznego**, pełnej transakcyjności między różnymi systemami, odporności na dowolną awarię sprzętu ani bezpiecznej pracy wielu writerów na jednym runie.

Wersja v1: jeden host, jeden writer/run, sekwencyjne zadania i jawne punkty zatwierdzenia.

## 14. Rozdzielne tryby startu

| Operacja | Kontrakt |
|---|---|
| `start_new` | Tworzy nowy run; nie nadpisuje istniejącego `run_id` bez jawnej, osobnej decyzji i semantyki |
| `resume` | Czyta zatwierdzony snapshot, waliduje jego spójność, rekonstruuje bezpieczny punkt kontynuacji |

Ponowne `start_new` z tym samym ID i innym celem nie może wymazywać wcześniejszego celu, mieszać evidence ani podmieniać historii.

## 15. Przerwanie po częściowym skutku

Jeżeli narzędzie zmodyfikowało plik, lecz potwierdzenie nie dotarło do runtime'u, wznowienie nie zakłada automatycznie „nic się nie wydarzyło”. Najpierw odczytuje aktualny artefakt, wiąże go z identyfikatorem próby/operacji i decyduje, czy można bezpiecznie zweryfikować, ponowić czy zatrzymać proces. Błąd transportowy ≠ nieudana merytorycznie zmiana. Retry activity ≠ kolejna próba rozwiązania Child Task.

Jeżeli trwałość/odtwarzanie Mistral Workflows nie potrafi sprostać potrzebnej ścieżce lokalnego uruchomienia, należy to zgłosić i podjąć **jawną decyzję architektoniczną**, a nie dopisywać ukryty drugi silnik.

---

# VI. Planning Plane — od celu do programu zadań

## 16. Intake, Planner, Task Compiler

```text
Human Goal + constraints
   ↓ Intake
Planner → PlannerProposal
   ↓ Task Compiler
IDs / statusy / zależności / limity / scope
   ↓ walidacja programu
Plan → Task Register → snapshot
```

Planner może być pojedynczym wywołaniem modelu, ograniczoną rolą agentową albo stubem w testach. Proponuje treść semantyczną. Nie nadaje autorytatywnych statusów, nie ustala sam bez nadzoru podwyższonych limitów, nie przyznaje PASS.

Task Compiler nadaje wykonawcze identyfikatory, waliduje zależności, zakres i strukturę, a następnie tworzy zaakceptowany program. **Modelowa propozycja jest nieufnym wejściem**. Zachowujemy z obecnego prototypu rozdzielenie `PlannerProposal` od assemblera.

## 17. Parent Task i Child Task

Parent Task reprezentuje większy etap lub rezultat; Child Task jest minimalną jednostką wykonawczą modelu. Ma cel, zakres, dozwolone działania, zależności, weryfikowalne kryteria, limit prób i wymagane evidence. Wybranie następnego zadania nie oznacza dowolnego repriorytetyzowania przez Executora.

```text
PARENT-001: popraw moduł
 ├─ TASK-001: zidentyfikuj funkcję
 ├─ TASK-002: popraw wskazaną funkcję
 └─ TASK-003: zweryfikuj rezultat
```

Parent Task może mieć kontrolę na swojej granicy, w tym opcjonalny Human Gate. Nie wymuszamy zatwierdzenia przez człowieka po każdym Child Task. Trzy taski są **scenariuszem testowym**, a nie uniwersalnym limitem liczności planu.

## 18. Scheduler

Na v1 jeden aktywny Child Task w danym runie. Scheduler wybiera kwalifikujące się zadanie po spełnieniu zależności, blokuje przejście z nierozstrzygniętym wynikiem, respektuje limity i wyznacza stan Parent Task oraz całego runu **na podstawie rezultatów wszystkich odpowiednich zadań**. Ukończenie `TASK-001` nie oznacza ukończenia całego planu.

Statusy zadania i stan oczekiwania workflow/Human Gate mają być pojęciowo rozdzielone. Konkretny enum i mapowanie z obecnym kodem wymagają kontrolowanego projektu migracji; nie wolno podmieniać nazw losowo. Tabela przejść musi mieć jeden autorytatywny punkt egzekucji.

---

# VII. Model danych i kontrakty API wewnętrznego

## 19. Podstawowe schematy

Zachowujemy Pydantic/ustrukturyzowane dane i rozdzielenie ról:

| Schemat logiczny | Znaczenie |
|---|---|
| `GoalInput` | cel i ograniczenia człowieka |
| `PlannerProposal` | propozycja modelu, bez autorytatywnego stanu |
| `Plan` | zaakceptowany program zadań |
| `ChildTask` | atomowa jednostka pracy |
| `RunState` | autorytatywny snapshot runu |
| `TaskContext` | zestaw danych dla konkretnego modelu i zadania |
| `ExecutorOutput` | wynik próby Executora |
| `ToolObservation` | rzeczywista obserwacja wywołania narzędzia |
| `VerificationResult` | wynik niezależnego sprawdzenia |
| `EvidenceRecord` | dowód konkretnego wyniku |
| `HumanDecision` | decyzja z tożsamością bramki i zakresu autoryzacji |
| `EscalationRequest` | ustrukturyzowane żądanie pomocy/przekazania |

Są to logiczne kontrakty. Część już istnieje; niektóre są nowe. Nie oznacza to obowiązku stworzenia osobnego pliku lub klasy dla każdej tabelarycznej pozycji bez analizy obecnego kodu.

### 19.1. Przykład Child Task (ilustracja)

```json
{
  "task_id": "TASK-002",
  "parent_id": "PARENT-001",
  "goal": "Popraw funkcję calculate_value",
  "dependencies": ["TASK-001"],
  "allowed_files": ["src/calculations.py"],
  "verification": {
    "type": "test",
    "target": "tests/test_calculations.py"
  },
  "max_attempts": 2
}
```

To przykład semantyki, a **nie zgodny 1:1 schemat aktualnej implementacji**. Status bieżący, wykonane próby i zaakceptowane evidence są rozstrzygane przez stan runtime'u, nie przez dowolną wiadomość modelu.

---

# VIII. Context Builder i Retrieval

## 20. Task-scoped context

Context Builder otrzymuje aktualny Child Task, stan, ograniczenia, dozwolone pliki i wyniki poprzednich prób. Buduje **mały, wystarczający** pakiet dla modelu. Nie przesyła całego repozytorium ani pełnej metodologii FS-ASM do każdego wywołania.

Proponowany kontrakt `TaskContext`:

```text
TaskContext
├── task_id / objective
├── acceptance_criteria / constraints
├── allowed_files / available_tools
├── relevant_sources / relevant_tests
├── relevant_project_decisions
├── previous_observations / previous_verification
└── context_budget
```

Jeśli informacji brakuje, Executor może poprosić o dozwolony dodatkowy odczyt. Model nie musi otrzymywać maksymalnego kontekstu na starcie. Context Builder musi umieć powiedzieć, skąd pochodzą wybrane dane; dynamiczny stan zadania nie jest tym samym co historyczna pamięć projektu.

## 21. Etapy retrieval

**Pierwszy etap:** jawne ścieżki, `grep`/wyszukiwanie tekstowe, symbole, odczyt odpowiednich funkcji, importy i proste zależności. **Etap późniejszy, jeśli wykaże potrzebę:** embeddings, wektorowe wyszukiwanie, bardziej rozbudowany graf zależności i LSP. Interfejs wyboru kontekstu ma umożliwiać ulepszanie bez uzależnienia całego systemu od jednego RAG-u.

LLMC jest odłożonym eksperymentem, nie blokadą dostarczenia runtime'u. Oddzielamy narzędzie kontekstu **dla Vibe budującego repo** od Context Buildera **dla Executora pracującego pod FS-ASM**.

---

# IX. Execution Plane — rzeczywista pętla agenta

## 22. Executor musi być agentową pętlą, nie „task → odpowiedź”

```text
TaskContext
   ↓
Model Adapter → LLM
   ↓
Tool Call / Final / Escalate
   ↓
Tool Broker: walidacja + wykonanie
   ↓
ToolObservation
   └──────────→ kolejne wywołanie modelu
                   ↓
        wynik do niezależnej weryfikacji
```

Executor LLM proponuje działania i analizuje obserwacje. Runtime wykonuje narzędzia, zarządza pętlą i stop conditions. Tekst „DONE” jest co najwyżej prośbą o sprawdzenie, a nie zmianą stanu.

## 23. Dwie pętle, dwa poziomy retry

```text
TASK LOOP (FS-ASM / Workflows)
  wybierz task
     EXECUTOR LOOP
       model → tool → observation → model → ...
  verifier
  commit result
  kolejny task albo koniec
```

Oddzielne miary: `task_attempt` (ponowna próba całego zadania), `agent_step` (iteracja model–narzędzie), `tool_call_count`, `model_call_count`, `escalation_count`. Wielokrotne wywołanie narzędzi podczas jednej próby nie może zużywać budżetu retry jako wiele prób. Ponowienie techniczne activity nie jest nową autoryzowaną próbą.

## 24. Wyniki i zatrzymania Executora

Normalizujemy znaczenie rezultatów, np. `COMPLETED`, `NEEDS_INFORMATION`, `ESCALATION_REQUESTED`, `STEP_LIMIT_REACHED`, `TOOL_ERROR`, `POLICY_BLOCKED`. Dokładne nazwy są do dopasowania przy implementacji; ważne jest, aby nie utożsamiać z góry każdego błędu narzędzia z merytorycznym FAIL. Runtime ma limity kroków, prób, czasu, kosztu i narzędzi. Wyjątki techniczne powinny być odróżnione od negatywnej weryfikacji.

---

# X. Model Gateway, backendy i adaptery

## 25. Jeden wspólny kontrakt modeli

Pętla agenta nie powinna być kopiowana do adaptera dla każdego dostawcy. Przykładowy interfejs logiczny:

```python
response = model_adapter.generate(
    messages=messages,
    tools=tools,
    parameters=parameters,
)
```

Adapter komunikuje się z backendem, normalizuje tool calls i raportuje błędy, ograniczenia i metadane dostępne u dostawcy. Runtime wybiera model, interpretuje decyzje i egzekwuje politykę. Nie zakładamy identycznego natywnego tool callingu we wszystkich lokalnych implementacjach. Pierwsza wersja obsługuje **jeden wybrany protokół lokalny**, ale izoluje go za interfejsem.

Logiczny `ModelResponse` obejmuje co najmniej: `ToolCall`, `FinalResponse`, `EscalationRequest`, `InvalidResponse` lub ich semantyczne odpowiedniki. Parser nie może mylić nieprawidłowego formatu z udanym wynikiem narzędzia.

## 26. Docelowe backendy

1. **Local Model Adapter:** główny docelowy Executor, lokalny model ok. 7B Q4. Konkretna rodzina/model i silnik inferencji nie zostały zatwierdzone.
2. **Mistral API Model A:** wsparcie, ekspertyza, diagnoza problemu; konkretny model i zakres pomocy pozostają do decyzji.
3. **Mistral API Model B:** potencjalnie trudniejsze wykonanie lub druga forma eskalacji; konkretny model i rola nie są przesądzone.

Nie należy z góry przyjmować, że A jest zawsze tańszy od B albo że drugi model jest „sędzią” każdego wyniku. Konfiguracja powinna pozwalać przypisać role bez przebudowy systemu. **Vibe tworzy adaptery i testuje je na atrapach.** Realny lokalny model jest uruchamiany po przeniesieniu gotowego runtime'u na laptop; realne API konfigurowane jest w odpowiednim późniejszym etapie.

---

# XI. Tool Broker, uprawnienia, workspace

## 27. Pierwszy zakres narzędzi

Minimalny katalog możliwości: `list_files`, `read_file`, `search_code`, `apply_patch`, `run_checks`, `inspect_changes` — albo funkcjonalnie równoważne operacje. Są to funkcje zwykłego programu, nie nakaz stawiania sześciu usług. Model nie dostaje domyślnie nieograniczonego terminala.

## 28. Egzekwowanie uprawnień

`allowed_files` i dozwolone polecenia muszą być sprawdzane **przez kod przed skutkiem operacji**; ograniczenia zapisane wyłącznie w promptcie nie zapewniają ochrony. Tool Broker musi uwzględniać normalizację i rozwiązywanie ścieżek, wyjście poza katalog, dowiązania symboliczne oraz skutki procesów uruchamianych przez `run_checks`. Wersja v1 używa wydzielonego workspace/sandboxu i wąskich operacji.

Zakres narzędzi jest przyznany w ramach zadania i nie może zostać rozszerzony pojedynczą odpowiedzią LLM-a. Wszelkie operacje przekraczające uzgodnioną autonomię przechodzą odrębną ścieżkę autoryzacji.

---

# XII. Verification Plane i Evidence

## 29. Weryfikator niezależny od twierdzenia modelu

```text
Executor: „poprawiłem kod”
Verifier:
  read actual diff / artifact
  check allowed scope
  run specified check/test
  capture exit code, stdout/stderr and artifact identity
  compare result against acceptance criteria
  persist evidence
Domain Core: approve PASS or record failure
```

Weryfikacja ma obserwować **rzeczywisty plik, diff, kod zakończenia procesu, rezultat testu lub równoważny dowód zewnętrzny**. Przepisanie `expected` do `ExecutorOutput` i opakowanie go jako Evidence nie jest niezależnym dowodem. Testy kontrolne powinny odrzucać deklarację „gotowe” przy braku realnego skutku.

## 30. Kontrakt PASS

`PASSED` jest możliwe wyłącznie, kiedy wynik Verifiera dotyczy tego samego `run_id`, `task_id`, właściwej próby i właściwych artefaktów; wszystkie wymagane checks są spełnione, a powiązane evidence istnieje i zostało zaakceptowane. `status=PASS` przy `passed=false` w wymaganym checku lub pustych obowiązkowych evidence musi być odrzucony. **Tylko Domain Core zatwierdza przejście.**

Deterministyczne kontrole mają pierwszeństwo. Opcjonalny LLM Verifier dla oceny semantycznej to rozszerzenie, nie obowiązkowy drugi model recenzujący każdą linijkę.

---

# XIII. Routing i wielomodelowa eskalacja

## 31. Model lokalny jako domyślna droga

Lokalny 7B ma być pierwszym wyborem do normalnych Child Tasks. Mistral API jest pomocą przy problemach, a nie automatycznie uruchamianą częścią każdej operacji.

Pierwsza polityka routera jest **deterministyczna**: warunki eskalacji mogą obejmować przekroczenie limitu prób, brak postępu, `NEEDS_INFORMATION`, niepowodzenia możliwe do rozwiązania ekspertyzą i przekroczenie kompetencji danego modelu, pod warunkiem spełnienia polityki uprawnień i budżetu. Dokładne progi i koszt zostaną określone w konfiguracji po wyborze modeli.

## 32. Konsultacja a przekazanie zadania

- **Konsultacja:** pomocniczy model API otrzymuje ograniczony kontekst i zwraca wskazówki; lokalny Executor nadal jest właścicielem bieżącej próby w znaczeniu wykonawczym.
- **Przekazanie wykonania:** runtime świadomie przypisuje bieżący Child Task do innego adaptera z właściwym zakresem i budżetem. Samo narzędzie `ask_expert` nie może być ukrytym obejściem autoryzacji lub zwiększeniem limitu prób.

Nie ma nieskończonego ping-ponga między modelami. Liczba eskalacji, koszt i możliwe ścieżki są ograniczone i zapisywane. Dwa modele API oraz ich faktyczne kompetencje pozostają **do osobnego wyboru**.

---

# XIV. Human Gate i autonomia

## 33. Prostota przy zachowaniu tożsamości decyzji

Podstawowe decyzje dla wyczerpanego zadania pozostają `RETRY_ONCE` i `ABORT`. Workflows obsługuje oczekiwanie i mechanizm sygnału; FS-ASM waliduje jego związek z właściwym runem, taskiem, wystąpieniem bramki i konkretną zgodą, a następnie stosuje skutki w Domain Core.

Nie akceptujemy starej zgody jako autoryzacji przyszłej bramki. Zduplikowane sygnały nie mogą dodać kolejnej próby. Odrzucone sygnały nie wykonują pracy. Zakres audytu musi być opisany uczciwie; nie obiecujemy transakcyjnego exactly-once logowania każdej próby dostarczenia przy dowolnym crashu, jeśli kod tego nie gwarantuje.

Przyszłe typy bramek, np. zgoda na koszt lub poszerzenie zakresu, wymagają konkretnych scenariuszy i oddzielnych kontraktów, nie dopisywania wszystkiego do bieżącej implementacji M4.

---

# XV. Obserwowalność, koszty i potencjalny fine-tuning

## 34. Dane wykonania

Rejestrujemy tyle, ile jest potrzebne do diagnozy i późniejszego pomiaru: model/backend, identyfikatory prób i wywołań, tool calls i observations, wyniki weryfikacji, decyzje człowieka, ścieżkę eskalacji, czas i tokeny/koszty **jeśli backend je udostępnia**. Nie budujemy na starcie osobnej platformy monitoringu.

Pamiętamy o oddzieleniu danych audytu od autorytatywnego stanu: brak rekordu pomocniczego nie może zmienić PASS w arbitralny sposób, a pojedynczy wpis logu sam w sobie nie jest dowodem wykonania.

## 35. Trajektorie na dalszy etap

Docelowa trajektoria:

```text
task → context → model response → tool call → observation
     → independent verification → evidence → accepted result
```

Może później posłużyć do analizy i przygotowania zbioru danych. **Fine-tuning lokalnego modelu nie jest obecnie projektowany ani wykonywany.** Najpierw runtime musi działać i generować realne, zweryfikowane trajektorie. Przed wykorzystaniem danych należy usunąć sekrety, filtrować jakość i rozdzielić próbki treningowe i testowe.

---

# XVI. Dostarczenie na komputer użytkownika

## 36. Artefakt końcowy Vibe

Gotowy projekt ma zawierać: kod i zależności, przykładową konfigurację bez sekretów, dokumentację instalacji i uruchomienia na docelowym systemie, strukturę workspace oraz narzędzia diagnostyczne. Nie wolno umieszczać kluczy Mistral API w GitHubie, logach testów i przykładach. `.env` pozostaje poza repo; możliwy jest `.env.example`.

Uruchomienie na laptopie nie może wymagać sesji Vibe Code Web, stałego połączenia z GitHubem ani dostępu Vibe do lokalnych plików. Należy jawnie potwierdzić wymagania Mistral Workflows dotyczące lokalnego workera, zewnętrznej historii/procesu i ewentualnego połączenia sieciowego, **zanim ogłosimy pełną zgodność wdrożeniową**.

## 37. Kolejność realnej integracji

1. Zakończona i zweryfikowana implementacja całego runtime'u z kontrolowanymi odpowiedziami modelu.
2. Przeniesienie na komputer użytkownika.
3. Konfiguracja i pierwsze uruchomienie lokalnego LLM ok. 7B Q4.
4. Integracja dwóch wybranych modeli Mistral API i rzeczywiste testy eskalacji.
5. Dopiero później benchmarki, eksperymenty z retrieval/LLMC i ewentualny fine-tuning.

Nie przyspieszamy punktów 3–5 tylko po to, by udowodnić częściowo zaimplementowany milestone.

---

# XVII. Program implementacji i migracja istniejącego repo

## 38. Nie przepisujemy całości bez analizy

Najpierw należy porównać obecny kod z tym dokumentem i oznaczyć elementy: **zachować, dostosować, zastąpić, pozostawić jako historyczny przykład**. Szczególnie wartościowe do rozważenia: modele Pydantic, rozdzielenie propozycji Plannera od assemblera, walidatory i przejścia, podstawowy Human Gate, zabezpieczenia ścieżek i testy rzeczywistych inwariantów. ExecutorStub jest fixture'em/testowym backendem, a nie docelowym Executorem. Historyczne M1–M4 nie muszą stać się czterema równoległymi implementacjami tego samego runtime'u.

Zatwierdzenie architektury **nie zamyka automatycznie PR #20 i M4, nie autoryzuje merge do `main`, nie rozpoczyna M5**. Status kodu wymaga osobnego aktualnego przeglądu; audyty datowane 9 i 16 września opisują swoje konkretne SHA, a nie dowolny późniejszy commit.

## 39. Kolejność realizacji przez Vibe

| Etap | Cel | Dowód zakończenia |
|---|---|---|
| A. Utrwalenie kontraktu | Architektura jako jeden dokument, granice i decyzje | Dokument zatwierdzony i dostępny agentowi kodującemu |
| B. Gap analysis i migracja | Co z istniejącego kodu pasuje; określenie zakresu zmian | Mapa modułów oraz plan zmian bez pisania wszystkiego od nowa |
| C. Właścicielstwo stanu | Snapshot, domain transitions, start/resume | Jedno źródło statusów i kontrolowany restart na stubach |
| D. Pełny plan i weryfikacja artefaktów | Scheduler wszystkich Child Tasks, rzeczywiste izolowane tools, niezależne checks | Cały plan wykonany przy użyciu kontrolowanego Executora |
| E. Executor loop i Model Gateway | Pętla tool/observation, limity, normalizacja modeli | Kontraktowe testy z atrapą lokalnego modelu |
| F. Adaptery i eskalacja | Interfejsy lokalnego backendu i dwóch ról API, router | Symulowane poprawne routing, limity i przekazanie |
| G. Human Gate i recovery | Ograniczona autonomia oraz bezpieczne punkty wznowienia | Scenariusz decyzji i przerwania/wznowienia |
| H. Walidacja dostarczenia | Cały system instalowalny i uruchamialny według instrukcji | Pełny end-to-end bez prawdziwego lokalnego modelu |
| I. Laptop | Lokalny model, potem dwa modele API | Oddzielne realne testy już po przeniesieniu |

To **program logiczny**, nie automatyczne przemianowanie aktualnej roadmapy ani nakaz realizacji jednego gigantycznego PR. Zadania dla Vibe powstają po analizie istniejącego repo i mają zamknięty zakres. Nie planujemy przypadkowych rozbudów kontraktu w trakcie review.

## 40. Polityka testowania i końcowe kryterium

Trzy podstawowe poziomy: testy jednostkowe **inwariantów domenowych**, kontraktowe **adapterów, schema i Tool Brokera** oraz integracyjne **przepływu end-to-end**. Bez arbitralnej liczby „mikrotestów”; każdy test ma wykazywać istotne zachowanie lub wcześniej odtworzony błąd. Testów bezpieczeństwa i rzeczywistych skutków operacji nie usuwamy wyłącznie z powodu liczby przypadków. Po uproszczeniu architektury testy obsolete należy świadomie zweryfikować, nie kasować bez uzasadnienia.

**Definicja kompletnego Runtime v1 przed laptopem:** program przyjmuje cel lub zatwierdzony plan, kompiluje Task Register, wykonuje kwalifikujące się zadania zgodnie z zależnościami, dobiera ograniczony kontekst, wywołuje model przez adapter testowy, obsługuje tool calls i obserwacje, niezależnie weryfikuje rzeczywiste artefakty, zatwierdza jeden autorytatywny stan, stosuje ograniczone retry, potrafi przekazać problem do adaptera pomocniczego, zatrzymać się na Human Gate oraz wznowić z zatwierdzonego punktu. Rozpoznaje też ukończenie **całego planu**, a nie tylko `TASK-001`.

Wszystko powyższe musi zostać sprawdzone **bez rzeczywistego lokalnego 7B**, za pomocą kontrolowanych odpowiedzi modeli i rzeczywistych, izolowanych operacji plikowych/testowych. Po tym następuje etap instalacji i rzeczywistych eksperymentów na laptopie. Zielony pytest dla jednego stuba i liczba mikrotestów nie są samodzielnym dowodem ukończenia runtime'u.

---

# XVIII. Poza zakresem v1 i decyzje do późniejszego doprecyzowania

## 41. Czego nie budujemy teraz

Nie budujemy klastra rozproszonych workerów, wielowriterowej persystencji, domyślnego równoległego wykonywania Child Tasks, nowego silnika orkiestracji, neuralnego MoE, modelowego judge'a po każdej operacji, autonomicznego routera LLM, obowiązkowej bazy wektorowej, kompletnego fine-tuningu, pluginu ChatGPT czy rozbudowanego web UI. Mogą być przyszłymi kierunkami, jeśli badania wykażą wartość.

## 42. Rejestr jawnie otwartych parametrów

| Temat | Status i zasada |
|---|---|
| Model lokalny | ok. 7B, Q4 ustalone klasowo; dokładny model po ukończeniu runtime'u |
| Lokalny inference server/protokół | do wyboru; adapter ma izolować szczegóły |
| Modele Mistral API A/B | dwie role wsparcia ustalone kierunkowo; nazwy i dokładne zadania później |
| Budżety, retry, timeouty | ograniczenia wymagane; wartości liczbowe konfigurowalne, do ustalenia |
| Mistral Workflows local/dependencies | technicznie zweryfikować przed uznaniem gotowości wdrożeniowej |
| Szczegółowe statusy/schematy | mapowanie do obecnego kodu w planie migracji |
| Rozbudowany retrieval | późniejszy eksperyment, nie zależność startowa |
| Fine-tuning | wyraźnie odłożony |
| Baza SQLite zamiast JSON | nie jest obecną decyzją; v1 przyjmuje jeden autorytatywny snapshot |

## 43. Zasada kontroli zmian

Nowy agent programujący ma otrzymać **niniejszy dokument plus aktualny, datowany status implementacji**, a nie polecenie odtwarzania kanonu z dziesiątek sprzecznych raportów. Jeżeli odkryje konflikt techniczny lub niemożliwość wdrożenia zatwierdzonej architektury, powinien go zgłosić z dowodem i wariantami rozwiązania. Nie wolno mu samodzielnie zmieniać fundamentalnej własności stanu, roli Vibe, momentu podłączenia lokalnego LLM-a ani zakresu gwarancji. Zmiany tego dokumentu wymagają odrębnego uzgodnienia.

---

# XIX. Mapa ustaleń — wersja do szybkiego przekazania modelowi bez kontekstu

| Decyzja | Status |
|---|---|
| ChatGPT + użytkownik planują i przeprowadzają review | Zatwierdzone |
| Wyłącznie Mistral Vibe Code Web / GLM-5.2 koduje runtime | Zatwierdzone |
| GitHub służy rozwojowi/transportowi kodu, nie jest zależnością produkcyjną runtime'u | Zatwierdzone |
| Gotowa implementacja trafia na laptop | Zatwierdzone |
| Pierwszy rzeczywisty LLM uruchomiony pod runtime'em: lokalny ~7B Q4 | Zatwierdzone |
| Dwa modele Mistral API jako pomoc/eskalacja | Zatwierdzony kierunek; modele i szczegóły później |
| Mistral Workflows jako silnik pierwszej implementacji | Zatwierdzony kierunek; lokalne zależności do zweryfikowania |
| Domain Core egzekwuje reguły; model nie przyznaje sobie PASS | Zatwierdzone |
| Jedno autorytatywne źródło Run State ze zintegrowanym planem | Zatwierdzone |
| Jeden aktywny Child Task i jeden writer per run w v1 | Zatwierdzone |
| Executor loop, narzędzia, Context Builder, niezależny Verifier, Evidence | Zatwierdzone |
| Deterministyczna, ograniczona polityka routingu | Zatwierdzone; konkretne progi później |
| Jawny start/resume i ograniczone gwarancje trwałości | Zatwierdzone; bez obietnicy exactly-once zewnętrznych skutków |
| Stub/mock do budowania i testowania runtime'u przed laptopem | Zatwierdzone |
| Podłączenie prawdziwego 7B podczas budowy na chmurowym Vibe | **Nie** — dopiero po ukończeniu i przeniesieniu |
| Fine-tuning, LLMC, neuralne MoE, plugin, rozproszona infrastruktura | Odłożone |
| Bieżący PR #20, M4, M5, `main` | Statusy NIE są zmieniane przez akceptację architektury |

---

# XX. Pochodzenie, ograniczenia i relacja do materiałów historycznych

Dokument opracowano z zatwierdzonej przez użytkownika w projekcie ChatGPT rozmowy „FS-ASM — kompleksowa propozycja architektury docelowej”, jej dokończenia oraz jawnych poprawek dotyczących ról Vibe/GitHub, kolejności budowy i docelowego lokalnego Executora, z uwzględnieniem starszych źródeł, w szczególności:

- `CURRENT_FSASM_MODEL(1).md` / `fsasm-first/docs/CURRENT_FSASM_MODEL.md` — geneza, cel i kierunek koncepcyjny.
- `ORIGIN_AND_CURRENT_UNDERSTANDING-1.md` — rekonstrukcja historycznych mechanizmów i TODO as Code.
- `FS_ASM_Orkiestrator_Agentowy.txt` — rozmowa o przejściu od dokumentów do Training Lab i warstw runtime'u.
- `Wyja_nij_agenta_AI.md` — rozróżnienie LLM, agenta, runtime'u i pętli; wizja modelu lokalnego oraz wsparcia API.
- `chatgpt-decisions.md` — datowana ekstrakcja starszych decyzji, interpretowana z uwzględnieniem nowszych ustaleń.
- `FSASM_Fsasm-experimental_AUDYT_2026-09-09.md` i `FSASM_REVIEW_main_i_Fsasm-experimental_2026-09-16.md` — datowane raporty o stanie kodu, nie automatyczne źródło prawdy o późniejszych commitach.
- `fsasm-first.zip` — historyczne materiały i poligon, **nie** tożsamy z aktualnym kodem aktywnego brancha.

**Ważne:** ustalenia raportów źródłowych dotyczą ich dat/SHA; dokument architektury opisuje stan **decyzji**, a nie certyfikuje implementacji, zgodności SDK z laptopem, aktualnego CI ani jakości przyszłych modeli. Nie dokonano tutaj zmian w repozytorium GitHub.

---

**Dokument zamknięty jako pełny zapis zatwierdzonej architektury v1. Kolejne czynności: umieścić ten plik w źródłach projektu ChatGPT, a dopiero później przygotować kontrolowaną analizę zgodności obecnego repozytorium i zadania implementacyjne dla Vibe.**
