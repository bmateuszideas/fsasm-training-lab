FS-ASM — analiza porównawcza wersji i ewolucji metodologii

> **Wersja finalna po audycie wszystkich dostępnych artefaktów historycznych.**  
> Obejmuje korektę v6.0 po rozpakowaniu pakietu oraz audyt v4.0 Critical Addendum i dokumentu „Ciąg Logiczny Działania + błędylog”. Rozdzielono wersje normatywne, artefakty pomostowe i późniejsze interpretacje.

1. Wniosek główny

FS-ASM rozwijał się w czterech zasadniczych kierunkach:

1. Od listy zadań do wykonywalnego rejestru stanu.
2. Od jednego agenta kodującego do systemu Planning Agent → Human → Coding Agent.
3. Od prostych instrukcji do wielowarstwowego Control Plane i pamięci trwałej.
4. Od wspólnej specyfikacji dla obu agentów do ścisłej izolacji ról i kompilacji kontekstu.

Najbardziej stabilnym rdzeniem całej metodologii pozostaje:

wiedza i dokumentacja użytkownika
        ↓
formalizacja przez Planning Agenta
        ↓
pliki sterujące w repozytorium
        ↓
atomowe wykonanie przez Coding Agenta
        ↓
test, log, aktualizacja stanu

Audyt pełnego pakietu v6.0 potwierdził, że wersja ta była przede wszystkim modularną, zgodną wstecznie finalizacją v5.1. Nie stanowiła przełomu runtime; prawdziwe zerwanie architektoniczne nastąpiło dopiero w v7.

Największą zmianą architektoniczną nie było dodanie kolejnego pliku lub Hard Constraint, lecz przejście w v7 do zasady:

«Coding Agent nie powinien znać metodologii ani istnienia Planning Agenta. Powinien otrzymać wyłącznie skompilowany, samowystarczalny pakiet instrukcji projektu.»

---

CZĘŚĆ I — ANALIZA POSZCZEGÓLNYCH WERSJI

2. FS-ASM v2.1 — Task Register jako program wykonawczy

Cel

v2.1 nie próbuje jeszcze opisać całego systemu wieloagentowego. Koncentruje się na jednym problemie:

«Jak zaprojektować "todo.md", aby bezstanowy Coding Agent wykonywał pracę deterministycznie, atomowo i weryfikowalnie?»

Dokument definiuje "todo.md" jako:

- Control Script,
- Instruction Tape,
- zewnętrzny Program Counter,
- persistent working memory Coding Agenta.

Planning Agent jest już opisany jako kompilator wykonujący „Programming in Prose”.

Model agentów

Model zawiera:

- Planning Agenta projektującego zadania,
- Coding Agenta wykonującego zadania,
- Human Supervisora kontrolującego przebieg.

Podział ról istnieje, ale metodologia skupia się niemal wyłącznie na kontrakcie pomiędzy Planning Agentem a Coding Agentem za pośrednictwem "todo.md".

Struktura plików

Najważniejszym elementem jest pojedynczy Task Register:

todo.md
├── SESSION CONTEXT
├── CURRENT / ACTIVE TASK
├── CURRENT PLAN
├── PENDING QUEUE
└── DONE HISTORY

Wspomniane są także:

- "ROADMAP.md",
- ".ai/MEMORY.md",
- ".ai/scratchpad.md",
- testy,
- manifest zależności.

Nie tworzą one jeszcze kompletnego, formalnie zdefiniowanego Control Plane.

Mechanizm wykonywania zadań

Podstawowa maszyna wykonawcza:

FETCH
→ PLAN
→ EXECUTE
→ VERIFY
→ COMMIT
→ FETCH

Coding Agent:

1. znajduje pierwsze niewykonane zadanie,
2. zapisuje plan,
3. realizuje zadanie,
4. uruchamia określoną w zadaniu weryfikację,
5. oznacza zadanie jako wykonane,
6. przechodzi do kolejnego.

Zadanie ma być traktowane jak wywołanie funkcji:

[ID] + ACTION_VERB + TARGET_OBJECT + CONTEXT_LOCATION

Wymagane pola obejmują:

- "Input",
- "Constraint",
- "Dependency",
- "Verification".

Pamięć

Pamięć jest przede wszystkim zapisana w:

- aktualnym stanie checkboxów,
- sekcji "CURRENT",
- "CURRENT PLAN",
- historii "DONE",
- opcjonalnych aktualizacjach ".ai/MEMORY.md".

Jest to głównie pamięć stanu wykonania, a nie pełna pamięć architektoniczna i operacyjna.

Protokoły kontroli

Główne zasady:

- zero guesswork,
- test-first,
- jedno zadanie = jeden commit,
- topologiczna kolejność zadań,
- maksymalnie trzy próby przy niepowodzeniu,
- obowiązkowy exit condition,
- aktualizacja pamięci przy zmianach API, schematu lub zależności.

Nowe elementy względem wcześniejszych, niewidocznych artefaktów

v2.1 formalizuje:

- "todo.md" jako kod,
- atomowość,
- obiektywną weryfikację,
- Task Register jako ISA dla modelu,
- Coding Agenta jako „single-threaded loop machine”.

Elementy później usunięte lub przemianowane

- "CURRENT STACK" i "CURRENT ACTIVE TASK" są później zastępowane pełną hierarchią Parent–Child.
- "PENDING QUEUE" i "DONE HISTORY" przestają być jedynym dopuszczalnym modelem rejestru.
- Prosty limit trzech retry zostaje później zawężony do konkretnych typów zadań jako Controlled Dynamics.

Sprzeczności i problemy

Najważniejsza sprzeczność:

- dokument wymaga bezpieczeństwa i sprawdzania konfliktów,
- ale nie definiuje jeszcze kompletnego, niezależnego pliku praw i hierarchii źródeł prawdy.

"todo.md" jest bardzo silnym nośnikiem poleceń, ale bez późniejszego Control Plane może sam zawierać polecenie destrukcyjne.

Ślepe uliczki

- Nadmierne traktowanie modelu jako „ślepego procesora”, bez rozróżnienia typów pracy.
- Założenie, że każda porażka może otrzymać trzy retry.
- Przenoszenie zbyt dużej ilości bieżącego stanu do jednego pliku "todo.md".
- Brak wyraźnego oddzielenia kontekstu projektu od operacyjnego jądra agenta.

Elementy warte zachowania

Bezwzględnie zachować:

- "todo" jako wykonywalny rejestr stanu,
- deterministyczność, weryfikowalność i atomowość,
- zadanie jako strukturalny kontrakt,
- obiektywny exit condition,
- DAG zadań,
- zasadę „nie polegaj na historii czatu”.

---

3. FS-ASM v3.0 — pełny Control Plane i Bootstrap Mode

Cel

v3.0 rozszerza FS-ASM z architektury Task Register do kompletnej metodologii repozytorium.

Jej celem jest:

- zainicjalizowanie nowego projektu,
- zaprogramowanie Coding Agenta,
- rozdzielenie strategii, architektury, zasad i stanu,
- umożliwienie rozpoczęcia pracy po ręcznym bootstrapie.

Model agentów

Wprost zdefiniowane są dwa agenty:

- Planning Agent w środowisku webowym,
- Coding Agent w IDE/CLI.

Human pełni rolę:

- approval gate,
- operatora handoffu,
- źródła autoryzacji „Proceed”.

Jednocześnie jeden dokument nadal jest adresowany do obu agentów. To później zostanie uznane za błąd architektoniczny.

Struktura plików

Powstaje właściwy Control Plane:

.ai/
├── INSTRUCTIONS.md
├── STANDARDS.md
├── ARCHITECTURE.md
├── MEMORY.md
└── scratchpad.md

README.md
ROADMAP.md
todo.md
test_failures.log
src/
tests/

Każdy plik otrzymuje wyraźną funkcję:

- "INSTRUCTIONS.md" — kernel operacyjny,
- "STANDARDS.md" — prawo,
- "ARCHITECTURE.md" — wzorce i granice,
- "MEMORY.md" — decyzje długoterminowe,
- "ROADMAP.md" — strategia,
- "todo.md" — taktyczny stan wykonania,
- "scratchpad.md" — write-ahead log.

Mechanizm wykonywania zadań

v3.0 wprowadza Protocol Zero:

1. odczytaj kontekst,
2. załaduj zasady,
3. znajdź aktywne zadanie,
4. zacytuj zadanie w handshake,
5. poczekaj na „Proceed”,
6. wykonaj OODA Loop.

OODA:

OBSERVE
→ ORIENT
→ DECIDE
→ ACT
→ VERIFY

Handshake pełni funkcję wymuszonego pobrania kontekstu i blokady zadania.

Pamięć

Pamięć zostaje rozdzielona na:

- "todo.md" — bieżący stan,
- ".ai/scratchpad.md" — plan bieżącego zadania,
- ".ai/MEMORY.md" — ADR,
- "test_failures.log" — pamięć niepowodzeń,
- "README" i "ROADMAP" — długoterminowy kontekst domenowy i strategiczny.

Protokoły kontroli

v3.0 wprowadza:

- Conflict Resolution Hierarchy,
- odrzucanie poleceń z czatu,
- obowiązkowy handshake,
- Human Approval Gate,
- Bootstrap Mode i Normal Mode,
- zakaz rozpoczęcia Coding Agenta przed zaakceptowaniem bootstrapu,
- test jako warunek ukończenia.

Nowe elementy względem v2.1

Najważniejsze przyrosty:

- kompletny Control Plane,
- Protocol Zero,
- OODA Loop,
- konfliktowa hierarchia źródeł prawdy,
- Bootstrap Workflow,
- jawny approval gate,
- rozróżnienie Bootstrap Mode / Normal Mode,
- pierwszy pełny system dwuagentowy.

Elementy usunięte lub przemianowane

v2.1 nie zostaje usunięta, lecz jest w praktyce włączona do v3.0 jako druga część dokumentu.

Task Register pozostaje, ale staje się jednym z kilku komponentów metodologii.

Sprzeczności

Najważniejsze:

1. Jeden dokument jest jednocześnie:
   
   - specyfikacją dla Planning Agenta,
   - gotową instrukcją dla Coding Agenta.

2. Coding Agent ma działać tylko na podstawie repozytorium, ale jego wygenerowane instrukcje nadal otwarcie mówią o FS-ASM i metodologii zewnętrznej.

3. Human musi zatwierdzić handshake przed wykonaniem każdego przebiegu, co ogranicza autonomię nawet wewnątrz dobrze zdefiniowanych zadań.

4. "README.md" bywa przedstawiany jako entrypoint, ale innym razem entrypointem jest bezpośrednio ".ai/INSTRUCTIONS.md".

Ślepe uliczki

- Kopiowanie dużych sekcji metodologii „verbatim” do projektów.
- Utrzymywanie jednego dokumentu źródłowego dla obu ról.
- Zbyt rytualny handshake bez walidacji, czy agent naprawdę odczytał wszystkie pliki.
- Wymóg pełnego ludzkiego „Proceed” przed każdą fazą wykonania.
- Silne uzależnienie od ręcznego formatowania sekcji "CURRENT".

Elementy warte zachowania

- rozdzielenie Control Plane, State Register i Execution Plane,
- Bootstrap Mode,
- approval gate przed wdrożeniem Coding Agenta,
- OODA jako czytelny model orientacyjny,
- ADR,
- rejection of chat injection,
- hierarchia źródeł prawdy,
- write-ahead logging.

---

4. Project Agent Bootstrap Protocol — osobna gałąź rozwoju Planning Agenta

Ten dokument nie jest numerowaną wersją głównej metodologii, ale jest krytycznym artefaktem rozwojowym.

Cel

Zaprogramować Planning/Project Agenta do przekształcania dokumentacji biznesowej w kompletny pakiet repozytorium.

Model agentów

Planning Agent jest już nie tylko projektantem listy zadań, lecz pełnym kompilatorem specyfikacji.

Human przekazuje:

- dokumentację biznesową,
- metodologię FS-ASM,
- dodatkowy kontekst.

Planning Agent wykonuje analizę i materializuje repozytorium dla Coding Agenta.

Struktura procesu

Powstaje czterofazowy Domain-to-Execution Translation Process:

Domain Analysis
→ Architecture Design
→ Task Decomposition
→ Materialization

Dokument wprowadza pojęcie Context Programming Language: Markdown i YAML pełnią rolę składni, znaczenie instrukcji jest semantyką, a działania Coding Agenta są wykonaniem programu.

Nowe elementy

- klasyfikacja systemów domenowych,
- identyfikacja encji i operacji,
- analiza wymagań niefunkcjonalnych,
- systematyczny dobór architektury,
- moduły z odpowiedzialnościami i interfejsami,
- generowanie manifestów zależności i scaffoldu,
- Planning Agent jako osobny proces kompilacji.

Problem

Dokument jest bardzo rozbudowany i miejscami zaczyna generować zbyt wiele plików „dla kompletności”:

- CI/CD,
- konfiguracje,
- "py_lib.md",
- ".gitignore",
- dokumenty domenowe,
- szkielety folderów.

To prowadzi do konfliktu z późniejszą zasadą v7: generuj tylko pliki faktycznie używane w pętli wykonawczej.

Elementy warte zachowania

- Context Programming Language jako model pojęciowy,
- czterofazowy proces translacji,
- systematyczna analiza domeny,
- jawne uzasadnienie architektury,
- Planning Agent jako compiler front-end.

---

5. FS-ASM v4.0 — cognitive hardening i zewnętrzna pamięć wykonawcza

Cel

v4.0 próbuje zwiększyć posłuszeństwo i stabilność Coding Agenta poprzez:

- bardziej imperatywny język,
- twarde zatrzymania,
- dodatkowe warstwy pamięci,
- Hierarchical Lock,
- symbole i usage anchors,
- Trap Task.

Dokument sam określa się jako „Hardened with Cognitive Hard-Stopping”.

Model agentów

Nadal jeden wspólny dokument obsługuje dwie role:

IF PLANNING AGENT → GENERATE
IF CODING AGENT → EXECUTE

Planning Agent ma „maintain the truth”, Coding Agent ma „execute the truth”.

Human nadal kontroluje autoryzację.

Struktura plików

Do wcześniejszego Control Plane dochodzą:

py_lib.md
admin/
archive/
usage anchors w ARCHITECTURE.md

"admin/" staje się Task-Specific Memory.

"py_lib.md" staje się Symbol Table, choć nazwa sugeruje bibliotekę Pythona, a zawartość ma obejmować publiczne symbole całego projektu.

Mechanizm wykonywania zadań

Protocol Zero zostaje zaostrzony:

- agent ma pozostać suspended,
- nie może generować small talk,
- musi zacytować Task Lock,
- ma załadować architekturę, standardy, symbole i pamięć zadaniową.

OODA zostaje rozszerzona o:

- odczyt logów "admin/",
- odczyt "py_lib.md",
- usage anchoring,
- tooling-first,
- test-first,
- changelog po każdym zadaniu,
- aktualizację symbol table.

Pamięć

v4 tworzy kilka różnych klas pamięci:

1. "todo.md" — instrukcja i program counter.
2. ".ai/MEMORY.md" — ADR.
3. ".ai/scratchpad.md" — pamięć robocza.
4. "admin/" — pamięć zadaniowa.
5. "test_failures.log" — pamięć błędów.
6. "py_lib.md" — pamięć symboliczna.
7. usage anchors — pamięć wzorców użycia.
8. "archive/" — pamięć poprzednich implementacji.

Protokoły kontroli

Dodane zostają:

- Trap Task,
- Hierarchical Lock Parent–Child,
- Usage Anchoring,
- Tooling First,
- Symbol Table Protocol,
- Task-Specific Memory,
- fingerprinting danych i modeli,
- rozszerzone HC-01–HC-06,
- semantic task register naming,
- legacy repository hardening.

Nowe elementy względem v3.0

- Parent jako kontener, Child jako jednostka wykonawcza,
- dokładniejsza pamięć między sesjami,
- próba przeciwdziałania duplikacji funkcji,
- kontrola API przez usage anchors,
- kontrola reuse przez tooling-first,
- test odporności w postaci Trap Task,
- specjalne reguły dla ML/OPT,
- hardening istniejących repozytoriów.

Elementy usunięte lub przemianowane

Najważniejsza niespójność numeracji:

- plik nazywa się v4.0,
- canonical filename mówi o v3.1,
- wewnętrzna specyfikacja Task Register również nazywa się v3.1.

Wskazuje to na brak dyscypliny wersjonowania.

Sprzeczności

1. HC-05 i HC-06 zmieniają znaczenie między wersjami.
   
   - W v4 HC-05 to Defensive Coding.
   - HC-06 to Model/Data Fingerprinting.
   - W v7 kolejność zostaje odwrócona.

2. Zakaz refaktoryzacji in-place i obowiązek archiwizacji może powodować:
   
   - mnożenie wersji modułów,
   - pozostawianie martwego kodu,
   - narastanie długu technicznego.

3. Trap Task jest celowym wprowadzeniem błędnego polecenia do produkcyjnego rejestru zadań.

4. Imperatywny język zakłada, że słowa pisane wielkimi literami zwiększają wiarygodność wykonania. To hipoteza, nie gwarancja.

5. "py_lib.md" miesza:
   
   - allowlistę bibliotek,
   - indeks symboli,
   - dokumentację publicznego API.

Ślepe uliczki

- Archiwizowanie starego kodu zamiast korzystania z Git.
- Jedna ręcznie utrzymywana Symbol Table dla wszystkich funkcji.
- Trap Task w realnym backlogu.
- Nadmierna liczba obowiązkowych plików odczytywanych przy każdym zadaniu.
- „Cognitive hard-stopping” jako substytut walidatora mechanicznego.
- Zbyt literalne przypisywanie funkcji poznawczych wielkim literom i rytuałom tekstowym.

Elementy warte zachowania

- Parent–Child hierarchy,
- usage anchors,
- task-specific logs,
- symbol deduplication jako cel,
- semantic naming Task Registers,
- model/data fingerprinting,
- explicit ML/OPT metrics,
- legacy repository hardening,
- czytelne granice modułów,
- aktualizacja ADR przy zmianach strukturalnych.

---

5A. Artefakty pomostowe v4 — Critical Addendum i Ciąg Logiczny Działania

Status

Te dwa dokumenty nie są osobnymi wersjami FS-ASM. Uzupełniają analizę v4 z dwóch stron:

- `FS-ASM v4.0 CRITICAL SPECIFICATION ADDENDUM` jest normatywnym patchem opartym na śladach z Execution Plane projektu PUR.
- `FS-ASM _ Majster_Method_ Ciąg Logiczny Działania+błędylog` jest interpretacyjną mapą runtime v4 i analizą ryzyka dryftu.

Critical Addendum — funkcja historyczna

Addendum jawnie wiąże mechanizmy metodologiczne z konkretnymi artefaktami projektu PUR. Formalizuje:

- model/data fingerprinting,
- Task-Specific Memory w `admin/`,
- semantyczne nazwy Task Registers,
- `.ai/ARCHITECTURE.md` jako źródło ORIENT,
- usage anchoring,
- tooling first,
- Metric + Threshold dla ML/OPT.

Jest to najmocniejszy zachowany dowód procesu:

```text
problem lub rozwiązanie w realnym repozytorium
→ reguła metodologiczna
→ integracja w Unified v4
```

Mechanizmy te nie powstały dopiero w v6. v6 je dziedziczy i porządkuje.

Zmiany podczas integracji do Unified v4

- Fingerprinting występuje w Addendum jako HC-05, a w Unified v4 jako HC-06.
- TSM zostaje rozszerzona: Addendum uruchamia ją po trzecim błędzie lub ręcznym pause; Unified v4 wymaga logu również po udanym zadaniu.
- Usage anchors zostają uogólnione z konkretnych plików PUR do list `usage_anchors.tests` i `usage_anchors.scripts`.
- Zasada semantycznego nazewnictwa zostaje włączona do specyfikacji Task Register.

Ciąg Logiczny — funkcja historyczna

Dokument układa v4 w pięć etapów:

1. Bootstrap,
2. Protocol Zero,
3. OODA,
4. kontrola zgodności,
5. audyt i pamięć.

Nie jest rzeczywistym błędylogiem: nie zawiera datowanych incydentów ani danych wykonawczych. Jest analizą trzech failure modes:

- pozorna zgodność podczas ORIENT,
- dryft zakresu i atomowości,
- pomijanie aktualizacji pamięci po VERIFY.

Najważniejszy wkład

Dokument wprowadza ważny wniosek:

```text
FS-ASM ogranicza utratę kontekstu,
ale nie usuwa halucynacji.
Ryzyko przesuwa się na interpretację zasad,
deklarowanie wykonania kontroli
oraz synchronizację stanu i dowodów.
```

To zalążek osobnego Assurance Model, którego nie należy mieszać z samym Runtime Model.

Nieścisłości

- „Majster jako jedyny modyfikujący Control Plane” przeczy roli Planning Agenta i dozwolonym aktualizacjom MEMORY przez Coding Agenta.
- `APPROVED` i `Proceed` są mieszane, choć zatwierdzenie bootstrapu i sygnał runtime to inne operacje.
- Handshake jest traktowany zbyt mocno: może kierować uwagę, ale nie dowodzi odczytu i zgodności.
- Trap Task nie zapewnia ciągłej kontroli ORIENT.
- Tekstowa checklista nie „wymusza” aktualizacji pamięci.
- Test nie jest jedynym możliwym Exit Condition.
- Dokument nie obejmuje Quality Gate v6 ani Parent Boundary Gate i izolacji ról v7.

Znaczenie dla nowego FS-ASM

Zachować:

- evidence-driven development metodologii,
- failure-mode catalog,
- Task-Specific Memory jako klasę pamięci,
- usage anchors i tooling first,
- mierzalną walidację domenową,
- human oversight jako jawny składnik.

Przeprojektować:

- Trap Task,
- ręczną Symbol Table,
- tekstowe checklisty,
- handshake jako dowód,
- wielokrotne ręcznie synchronizowane pliki stanu.

Wniosek

Addendum pokazuje, skąd pochodzą konkretne mechanizmy v4. Ciąg Logiczny pokazuje, gdzie tekstowa implementacja tych mechanizmów nadal może zawieść. Razem tworzą brakujące połączenie między historią PUR, hardeningiem v4 i późniejszą potrzebą walidatorów mechanicznych.

---

6. FS-ASM v6.0 — modularna finalizacja v5.1 i domenowy Quality Gate

Status źródeł

Pełny pakiet `FS-ASM_v6.0.zip` został rozpakowany i przeanalizowany. Wersja zawiera siedem modułów tematycznych oraz własne dokumenty ewolucji:

- `00_Introduction_and_Philosophy.md`,
- `01_Control_Plane/`,
- `02_State_Register_and_Task_System/`,
- `03_Bootstrap_Protocol/`,
- `04_Execution_Model/`,
- `05_Examples_and_Patterns/`,
- `06_Versioning_and_Evolution/`,
- `README.md`.

Własny changelog i migration guide v6.0 deklarują zgodność runtime z v5.1 oraz brak breaking changes. Dlatego v6 nie należy opisywać jako nowej architektury wykonawczej, lecz jako modularną finalizację i rozwinięcie linii v4/v5.1.

Cel

v6 ma cztery faktyczne cele:

1. Rozbić monolityczną specyfikację v5.1 na moduły tematyczne.
2. Podnieść Input Documentation Quality Gate do rangi obowiązkowego pierwszego kroku bootstrapu.
3. Dopracować wzorce `[PHYSICS-CRITICAL]` i `[DATA-GAP]`.
4. Dodać Controlled Dynamics, czyli ograniczone retry wewnątrz zadań fizyczno-krytycznych.

Nie zmienia natomiast fundamentalnie sposobu działania Coding Agenta.

Model agentów

v6 zachowuje model wspólnej specyfikacji dla trzech uczestników:

- Planning Agent analizuje dokumentację klienta, przeprowadza Quality Gate, projektuje architekturę, rozkłada pracę na Parent i Child Tasks oraz generuje bootstrap bundle.
- Coding Agent uruchamia Protocol Zero, odczytuje Control Plane i pierwszy unchecked Child Task, realizuje OODA Loop i stosuje HC-01–HC-06.
- Human Supervisor pozostaje recenzentem, audytorem, approval gate’em i źródłem wyjaśnień.

Jednocześnie jeden pakiet nadal miesza:

- metodykę Planning Agenta,
- runtime contract Coding Agenta,
- szablony plików docelowych,
- wzorce domenowe.

To właśnie v7 uznaje później za podstawowy błąd strukturalny.

Struktura plików

v6 reprezentuje podejście „bootstrap pełnego repozytorium i całego środowiska sterowania”. Generowany projekt ma zawierać:

```text
.ai/
├── INSTRUCTIONS.md
├── STANDARDS.md
├── ARCHITECTURE.md
├── MEMORY.md
└── scratchpad.md

README.md
ROADMAP.md
todo.md lub todo_<moduł>.md
pyproject.toml
py_lib.md
docs/INPUT_QUALITY_REPORT.md
src/
tests/
docs/
configs/
admin/
scripts/
```

Jest to wyraźnie większy bundle niż późniejszy, redukowany pakiet v7.0/v7.1.

Mechanizm wykonywania zadań

Runtime v6 pozostaje niemal bezpośrednią kontynuacją v4/v5.1:

```text
Protocol Zero
→ OBSERVE
→ ORIENT
→ DECIDE
→ ACT
→ VERIFY
```

Protocol Zero wymaga:

1. odczytania `.ai/STANDARDS.md` i `.ai/ARCHITECTURE.md`,
2. odczytania aktywnego rejestru,
3. znalezienia pierwszego unchecked Child Task,
4. zacytowania Task Lock w handshake,
5. zadeklarowania odrzucania operacyjnych poleceń z czatu.

OODA obejmuje:

- OBSERVE — aktywne zadanie, failure log, `admin/*.md`, Symbol Table,
- ORIENT — architekturę, allowlistę i usage anchors,
- DECIDE — plan materializowany w pliku,
- ACT — TDD oraz atomowy zakres zmian,
- VERIFY — test, aktualizację tasku, changelogu, `py_lib.md` i ADR.

v6 nie zawiera jeszcze reguły znanej z v7:

- wykonuj automatycznie wszystkie Child Tasks w obrębie Parent,
- zatrzymaj się dopiero na granicy Parent Task,
- zaczekaj na `Proceed` przed kolejnym Parent Task.

Parent Boundary Gate jest zatem rzeczywistą innowacją v7.

Pamięć

v6 ma rozwiniętą pamięć wielowarstwową:

- `todo*.md` — Program Counter,
- `.ai/MEMORY.md` — ADR i assumptions,
- `.ai/scratchpad.md` — plan roboczy,
- `admin/` — Task-Specific Memory,
- `test_failures.log` — pamięć błędów,
- `py_lib.md` — ręczna Symbol Table,
- usage anchors — wzorce poprawnego użycia,
- Git i changelogi — historia zmian,
- `archive/` lub versioned modules — zachowane poprzednie implementacje.

Mocną stroną jest rozpoznanie różnych klas pamięci. Słabą — ręczne utrzymywanie wielu reprezentacji tego samego stanu, co grozi ich rozjazdem.

Input Documentation Quality Gate

Quality Gate v6 jest silnie ukształtowany przez domenę PUR, symulacje i projekty fizyczno-inżynierskie. IQ-01–IQ-06 dotyczą między innymi:

- kanonicznego źródła parametrów fizycznych i geometrycznych,
- równań i danych dla krytycznych mechanizmów,
- odróżniania referencji od założeń,
- metryk i progów dla zadań ML/OPT/PHYSICS,
- zachowania granicznego i warunków awaryjnych,
- sprzeczności między dokumentami.

Dopiero v7/v7.1 generalizują ten gate do bardziej uniwersalnych kategorii: goal clarity, domain completeness, data availability, non-negotiables, ambiguity scan i gap inventory.

Controlled Dynamics

W v6 Controlled Dynamics dotyczą wyłącznie zadań `[PHYSICS-CRITICAL]`.

Retry są dozwolone tylko wtedy, gdy zadanie definiuje:

- maksymalną liczbę prób,
- kryterium konwergencji,
- docelową metrykę i próg,
- pełny log każdej próby,
- końcową Verification bez obniżania wymagań.

Po wyczerpaniu budżetu następuje failure i eskalacja. v7.1 rozszerza ten mechanizm także na `[ML]` i `[OPT]`.

Task tagging

Główna tabela v6 formalizuje:

- `[DATA-GAP]`,
- `[PHYSICS-CRITICAL]`,
- `[ASSUMPTION]`.

ML i OPT pojawiają się semantycznie w dodatkowych regułach, ale nie są jeszcze ujęte równie konsekwentnie w głównej tabeli tagów. v7.1 porządkuje ten system, dodając `[ML] / [OPT]` oraz obowiązkowe `Metric:` i `Threshold:`.

Rzeczywiste innowacje względem v5.1/v4

Innowacje potwierdzone przez własny changelog v6:

1. Modularizacja monolitycznej specyfikacji.
2. Controlled Dynamics dla `[PHYSICS-CRITICAL]`.
3. Mocniejsze wyeksponowanie Input Documentation Quality Gate.
4. Kanoniczny `docs/INPUT_QUALITY_REPORT.md`.
5. Dopracowane wzorce `[PHYSICS-CRITICAL]` i `[DATA-GAP]`.
6. Rozszerzony bootstrap self-verification.
7. Dokładniejsze Physical Validation Criteria.

Elementy odziedziczone, a nie nowe:

- Protocol Zero,
- OODA Loop,
- Parent–Child tasks,
- HC-01–HC-06,
- Trap Task,
- usage anchors,
- Symbol Table,
- Task-Specific Memory,
- chat-injection rejection,
- Planning Agent jako compiler.

Elementy usunięte lub przemianowane

v6 nie usuwa kluczowych mechanizmów v5.1 i deklaruje brak breaking changes. Zmiana dotyczy przede wszystkim organizacji dokumentacji oraz dodania warstw walidacyjnych. Nie następuje jeszcze rozdzielenie specyfikacji według odbiorców.

Sprzeczności

1. Bundle ma być samowystarczalny, ale generowane `INSTRUCTIONS.md` jawnie identyfikuje metodologię jako FS-ASM v6.0.
2. Coding Agent ma czytać wyłącznie pliki projektu, lecz główny podręcznik nadal zawiera bezpośrednią gałąź instrukcji dla Coding Agenta.
3. Controlled Dynamics wprowadza dynamikę do systemu deklarującego deterministyczność, bez mechanicznego formatu oceny konwergencji.
4. Atomicity i zakaz partial commits utrudniają analizę kolejnych prób w dużych zadaniach fizycznych.
5. TDD jest traktowane jako zasada niemal uniwersalna, bez jasnego wyjątku dla eksploracji i eksperymentów.
6. Trap Task nadal jest elementem prawdziwego rejestru produktu.
7. `py_lib.md` łączy rolę indeksu symboli, dokumentacji API i pośredniej kontroli duplikacji.
8. Archiwizacja kodu dubluje funkcję Git i może prowadzić do rozrostu repozytorium.

Ślepe uliczki

- modularizacja bez rozdzielenia Planning i Coding Agenta,
- nadmiar obowiązkowych plików i ręcznych indeksów,
- retoryczny hardening zamiast mechanicznych validatorów,
- Trap Task w produkcyjnym Task Register,
- archiwizacja kodu jako domyślna polityka regresji,
- zbyt silne zakotwiczenie Quality Gate w fizyce,
- jeden runtime protocol dla agentów o różnych możliwościach,
- brak wersjonowanego schematu bundle,
- brak Parent Boundary Gate,
- brak rozróżnienia zadań implementacyjnych, badawczych, eksperymentalnych i operacyjnych.

Elementy warte zachowania

- modularne rozdzielenie zagadnień metodologii,
- obowiązkowa kontrola jakości wejścia,
- jawne gaps, assumptions i sources,
- Physical Validation Criteria,
- Metric + Threshold jako Definition of Done,
- Controlled Dynamics z retry budget i kryterium konwergencji,
- pełne logowanie prób,
- bootstrap self-verification,
- usage anchors,
- Task-Specific Memory oddzielona od ADR,
- semantyczne nazwy Task Registers,
- rozdzielenie Domain Analysis, Architecture Design, Task Decomposition i Materialization.

Najważniejsza wartość

Najważniejszą wartością v6 nie jest nowa maszyna runtime. Jest nią przeniesienie kontroli jakości z samego wykonania również na dokumentację wejściową, jawne założenia i domenową walidację fizyczną.

---

7. FS-ASM v7.0 — pełna separacja Planning Agenta i Coding Agenta

Cel

v7.0 dokonuje korekty strukturalnej:

«specyfikacja metodologii jest wyłącznie dla Planning Agenta.»

Coding Agent:

- nie widzi dokumentu v7,
- nie zna pojęcia FS-ASM,
- nie zna Planning Agenta,
- otrzymuje wyłącznie wygenerowane pliki projektu.

Model agentów

Model staje się jednoznaczny:

Planning Agent
    ↓ generuje
bootstrap bundle
    ↓ Human kopiuje
Coding Agent

Human pozostaje message busem i approval gate’em.

Planning Agent jest compilerem i architektem, a nie implementerem.

Struktura plików

Minimalny pakiet:

README.md
.ai/STANDARDS.md
.ai/INSTRUCTIONS.md
.ai/ARCHITECTURE.md
.ai/MEMORY.md
ROADMAP.md
todo.md
docs/INPUT_QUALITY_REPORT.md
admin/README.md

Kluczowa zmiana:

- nie generuj dodatkowych plików „dla kompletności”,
- generuj tylko pliki faktycznie używane w pętli Coding Agenta.

Mechanizm wykonywania zadań

v7 opisuje pełną pętlę, którą Planning Agent ma skompilować do ".ai/INSTRUCTIONS.md".

Najważniejsza innowacja:

- Child Tasks w obrębie jednego Parent Task są wykonywane automatycznie,
- po ostatnim Child Task Parent Tasku agent musi się zatrzymać,
- następny Parent Task wymaga jawnego „Proceed”.

To tworzy kontrolowaną autonomię odcinkową.

Pamięć

- Control Plane,
- Task Register,
- "admin/" jako pamięć wykonania,
- ".ai/MEMORY.md" jako ADR i założenia,
- Quality Report jako pamięć jakości wejścia.

"py_lib.md" znika z obowiązkowego pakietu. Informacje o nowych symbolach mają być zapisywane w changelogach zadań.

Protokoły kontroli

- Input Quality Gate,
- pełny execution loop,
- Parent Boundary Gate,
- chat injection rejection,
- Conflict Resolution Hierarchy,
- Trap Task,
- task tags,
- bounded retries,
- bootstrap self-verification,
- zero external context requirement.

Nowe elementy względem v6

- ścisła izolacja odbiorców,
- brak jawnych odwołań do metodologii w plikach Coding Agenta,
- kompilacja zachowania zamiast przekazywania metodologii,
- minimalny obowiązkowy bundle,
- pełna pętla wielozadaniowa,
- stop pomiędzy Parent Tasks,
- jednozdaniowy handoff do Coding Agenta.

Elementy usunięte lub przemianowane

Usunięte lub zdegradowane:

- wspólny dokument dla obu ról,
- obowiązkowy "py_lib.md",
- obowiązkowy ".ai/scratchpad.md" jako osobny plik,
- rozbudowany scaffold infrastrukturalny,
- jawne informowanie Coding Agenta o nazwie FS-ASM.

Sprzeczności

1. v7 nadal wymaga dokładnie jednego Trap Tasku.
2. README ma kierować do INSTRUCTIONS, ale pętla każe za każdym razem czytać README ponownie.
3. Agent ma czytać admin logs relevant to recent tasks, ale nie istnieje deterministyczny indeks wskazujący, które logi są relevant.
4. Chat jest najniższym źródłem prawdy, ale „Proceed” z czatu jest wymaganym sygnałem zmiany Parent Tasku.
5. „Zero additional context” jest częściowo sprzeczne z koniecznością pytań o blokery.

Ślepe uliczki

- dokładnie jeden Trap Task jako obowiązek produkcyjny,
- traktowanie wszystkich modeli i IDE jako wykonujących identycznie ten sam protokół,
- ręczny handoff jako jedyna forma transportu pakietu,
- pełne ponowne czytanie wszystkich plików po każdym Child Task,
- brak formalnego schematu maszynowego Task Register.

Elementy warte zachowania

- role isolation,
- compiler model,
- self-contained Coding Agent bundle,
- bounded autonomy,
- Parent Boundary Gate,
- minimalny bundle,
- zero hidden context,
- pełny Quality Gate,
- jedna instrukcja handoffu.

---

8. FS-ASM v7.1 — rozwinięta, kompletna specyfikacja Planning Agenta

Cel

v7.1 zachowuje architekturę v7.0, ale odzyskuje szczegółowość z v6.

Jest opisana jako:

- Planning-Agent-only,
- Full Detailed,
- authoritative operating manual.

Model agentów

Bez zmian względem v7:

- Planning Agent czyta metodologię,
- Coding Agent czyta tylko wygenerowany bundle,
- Human przekazuje i zatwierdza.

Struktura plików

Ten sam minimalny bundle co w v7.0, ale dokładniej określony.

"ARCHITECTURE.md" musi zawierać:

- stack i jego uzasadnienie,
- moduły i granice,
- data flow,
- dependency rules,
- "usage_anchors.tests",
- "usage_anchors.scripts".

"MEMORY.md" musi zawierać sekcję bootstrapowych luk i założeń.

Mechanizm wykonywania zadań

v7.1 rozwija każdy krok:

1. entrypoint,
2. standardy,
3. architektura,
4. task register,
5. pierwszy Child Task,
6. logi admin,
7. handshake,
8. plan,
9. TDD,
10. verification,
11. aktualizacje stanu i pamięci,
12. stop lub kontynuacja.

Pamięć

Doprecyzowane zostają:

- format changelogu,
- rejestrowanie nowych symboli,
- ADR przy zmianach architektury,
- założenia w pamięci,
- failure logging,
- task-specific logs.

Protokoły kontroli

- IQ-01 do IQ-06,
- wymóg "INPUT_QUALITY_REPORT.md",
- dokładny Parent/Child stop rule,
- Controlled Dynamics z budżetem i kryterium konwergencji,
- wymagane pola dla tagów,
- pełna self-verification checklist,
- zakaz generowania znaczącego kodu przez Planning Agenta.

Nowe elementy względem v7.0

Głównie uszczegółowienia:

- dokładniejszy Quality Gate,
- dokładny format logów,
- pełny Controlled Dynamics,
- precyzyjne wymagania task tags,
- bardziej rygorystyczna autoweryfikacja,
- dokładne wymagania wobec "ARCHITECTURE.md" i "MEMORY.md".

Elementy usunięte lub przemianowane

Nie jest to nowa architektura, lecz wersja rozwinięta.

Można ją traktować jako:

v7.0 = zasady i rdzeń
v7.1 = pełny podręcznik operacyjny

Sprzeczności

1. „Generate only files” kontra możliwość seedowania "src/" skeletonami.
2. „Nie twórz dodatkowych plików” kontra rosnące wymagania raportów i logów.
3. HC-04 mówi „one Child Task = one commit”, ale agent może nie mieć dostępu do Git lub prawa commitowania.
4. HC-06 nadal zaleca archiwizację superseded logic, co może być gorsze niż poleganie na historii Git.
5. Input Quality Gate każe pytać Human o istotne luki, ale pełna automatyzacja bootstrapu zakłada możliwie mało interakcji.
6. Trap Task nadal pozostaje obowiązkowy.
7. TDD jest wymagane „where applicable”, ale nie ma ścisłej definicji applicable.

Ślepe uliczki

- tekstowa autoweryfikacja bez mechanicznego validatora,
- zbyt wiele zasad zapisanych jako natural language,
- brak wersjonowanego schematu artefaktów,
- brak identyfikatora bundle/spec compatibility,
- brak rozróżnienia agent capabilities,
- brak formalnego protokołu aktualizacji task register po zmianie wymagań,
- brak mechanizmu konfliktu między roadmapą a późniejszymi ADR.

Elementy warte zachowania

- pełna izolacja ról,
- Quality Gate,
- self-verification bootstrapu,
- Controlled Dynamics,
- Parent Boundary Gate,
- typed tasks,
- domain validation,
- usage anchors,
- samowystarczalność artefaktów,
- dokładna odpowiedzialność Planning Agenta.

---

CZĘŚĆ II — ANALIZA PRZEKROJOWA

9. Ewolucja modelu "todo.md"

v2.1

todo.md = program

Pierwszy unchecked task jest instruction pointerem.

v3.0

todo.md = taktyczny stan podległy Control Plane

Pojawia się hierarchia źródeł prawdy.

v4.0

todo.md = hierarchiczna maszyna Parent–Child

Parent zapewnia kontekst, Child jest instrukcją atomową.

v6

todo.md = odziedziczony Parent–Child Task Register rozszerzony o wzorce domenowe

v6 zachowuje mechanizm v5.1, ale wzmacnia kontrakty `[DATA-GAP]`, `[ASSUMPTION]` i `[PHYSICS-CRITICAL]`. ML/OPT są obecne w regułach, lecz nie są jeszcze równie konsekwentnie sformalizowane w głównej tabeli tagów.

v7/v7.1

todo.md = wykonywalny plan z granicami autonomii

Child Tasks wykonują się automatycznie w obrębie Parent Task, a Parent Boundary wymaga zgody człowieka.

Ocena

To jest najbardziej udana linia ewolucji całej metodologii.

Do nowego FS-ASM warto zachować:

- atomowy Child Task,
- Parent jako boundary autonomii,
- obiektywną Verification,
- jawne Dependency,
- typed tags,
- jednoznaczny status.

Należy natomiast odejść od ręcznego parsowania Markdown na rzecz opcjonalnego, walidowalnego schematu YAML/JSON.

---

10. Ewolucja pamięci

Etap 1 — pamięć zadaniowa

- checkboxy,
- current task,
- done history.

Etap 2 — pamięć architektoniczna

- ".ai/MEMORY.md",
- ADR.

Etap 3 — pamięć robocza i błędów

- scratchpad,
- "test_failures.log".

Etap 4 — pamięć wielowarstwowa

- "admin/",
- symbol table,
- usage anchors,
- archive.

Etap 5 — pamięć jakości wejścia

- "INPUT_QUALITY_REPORT.md",
- assumptions,
- data gaps.

Ocena

FS-ASM prawidłowo rozpoznał, że „pamięć agenta” nie jest jednym plikiem.

Nowy model powinien formalnie rozdzielać:

Normative Memory
- standards
- architecture
- contracts

Execution State
- active task
- task statuses
- blockers

Decision Memory
- ADR

Evidence Memory
- tests
- metrics
- logs

Input Provenance
- assumptions
- sources
- unresolved gaps

"py_lib.md" jako ręczna Symbol Table nie powinien wracać w obecnej formie. Lepsze są automatyczne indeksy kodu lub manifesty generowane narzędziowo.

---

11. Ewolucja autonomii

v2.1

Coding Agent autonomicznie przechodzi do następnego zadania po zakończeniu poprzedniego.

v3/v4

Handshake i „Proceed” wprowadzają silną kontrolę człowieka przed wykonaniem.

v6

Controlled Dynamics pozwala na ograniczoną samokorektę wyłącznie w zadaniach `[PHYSICS-CRITICAL]`. Nie wprowadza jeszcze autonomicznego przechodzenia przez cały Parent Task ani zatrzymania na granicy Parent.

v7/v7.1

Najbardziej dojrzały model:

- autonomia wewnątrz Parent Task,
- stop pomiędzy Parent Tasks,
- eskalacja po wyczerpaniu retry budget.

Ocena

To jest dobry model bounded autonomy.

Do nowej wersji należy zachować:

- execution envelope,
- retry budget,
- escalation conditions,
- human gate na semantycznych granicach,
- brak gate’u przy każdym drobnym Child Task.

---

12. Ewolucja Planning Agenta

v2.1

Planning Agent pisze precyzyjne zadania.

v3.0

Planning Agent bootstrapuje cały Control Plane.

Bootstrap Protocol

Planning Agent staje się compilerem:

Domain Analysis
→ Architecture Design
→ Task Decomposition
→ Materialization

v6

Planning Agent otrzymuje mocniej wyeksponowany, fizyczno-inżynierski Quality Gate, kanoniczny Input Quality Report, dopracowane wzorce DATA-GAP/PHYSICS-CRITICAL i rozszerzoną self-verification. Sam model Planning Agenta jako compilera jest jednak odziedziczony z wcześniejszej linii, a nie wprowadzony po raz pierwszy w v6.

v7/v7.1

Planning Agent staje się jedynym odbiorcą metodologii.

Jego produktem nie jest „dokumentacja o FS-ASM”, lecz:

«skompilowany program kontekstowy dla konkretnego Coding Agenta i projektu.»

Ocena

To jest drugi najbardziej wartościowy kierunek po Task Register.

Nowa wersja powinna definiować Planning Agenta jako:

- compiler front-end,
- semantic analyzer,
- architecture synthesizer,
- task graph generator,
- artifact validator.

---

13. Ewolucja Coding Agenta

Wczesny model

„Ślepa, bezstanowa maszyna wykonawcza”.

v3/v4

„Stateful Engineer”, ale stan pochodzi wyłącznie z plików.

v7

Coding Agent nie zna metodologii, tylko lokalne instrukcje projektu.

Ocena

Najważniejszy właściwy wniosek:

«Coding Agent nie powinien interpretować uniwersalnej metodologii w czasie wykonania. Powinien otrzymać projektowo skompilowaną politykę działania.»

Należy jednak odejść od założenia, że każdy Coding Agent jest identyczny. Nowy FS-ASM powinien uwzględniać capability profile:

- może/nie może uruchamiać terminala,
- może/nie może commitować,
- może/nie może czytać całego repo,
- ma/nie ma narzędzia wyszukiwania symboli,
- obsługuje/nie obsługuje długie sesje autonomiczne.

---

14. Ewolucja mechanizmów bezpieczeństwa

Udane

- hierarchy of authority,
- chat-injection rejection,
- verification gate,
- dependency allowlist,
- atomicity,
- stop conditions,
- logging,
- model/data fingerprinting.

Wątpliwe

- Trap Task,
- wielkie litery jako hard stop,
- wymuszanie small-talk prohibition,
- archiwizowanie kodu zamiast Git,
- pełna odmowa każdego polecenia z czatu,
- zbyt sztywne „one task = one commit” bez uwzględnienia środowiska.

Ocena

Bezpieczeństwo należy przenieść z retoryki do walidacji mechanicznej:

- schema validation,
- policy checks,
- dependency checks,
- test runners,
- change-scope diff checks,
- artifact linting,
- fingerprint verification.

---

15. Najważniejsze sprzeczności między wersjami

15.1. Kto czyta metodologię?

- v3/v4: Planning Agent i Coding Agent.
- v7/v7.1: wyłącznie Planning Agent.

Rekomendacja: przyjąć model v7.

15.2. Co jest entrypointem?

- czasami ".ai/INSTRUCTIONS.md",
- czasami "README.md".

Rekomendacja: jeden stały plik maszynowy, np. ".agent/ENTRYPOINT.md", a README wyłącznie dla człowieka.

15.3. Znaczenie HC-05 i HC-06

Znaczenia zostały zamienione między v4 i v7.

Rekomendacja: stabilne identyfikatory polityk niezależne od numeru, np.:

HC-TEST-INTEGRITY
HC-DEPENDENCY-ALLOWLIST
HC-COMPLETE-CHANGE
HC-ATOMIC-SCOPE
HC-ARTIFACT-FINGERPRINT
HC-REGRESSION-SAFETY

15.4. Autonomia Coding Agenta

- v3/v4: czeka na Proceed przed wykonaniem.
- v7: działa autonomicznie w obrębie Parent Task.

Rekomendacja: model v7.

15.5. Scratchpad

- czasem obowiązkowy plik,
- czasem sekcja w todo,
- czasem opcjonalny.

Rekomendacja: nie wymuszać prywatnego toku rozumowania. Wymagać wyłącznie krótkiego, audytowalnego execution plan.

15.6. Symbol Table

- v4: "py_lib.md" jest obowiązkowy.
- v7: informacje o symbolach trafiają do changelogów.

Rekomendacja: symbol index generowany automatycznie, nie ręcznie.

15.7. Archiwizacja starego kodu

- v4/v7 HC-06 sugeruje archiwizację.
- jednocześnie system zakłada Git i atomowe commity.

Rekomendacja: polegać na Git. Archiwizować wyłącznie wtedy, gdy stara implementacja ma być częścią runtime lub eksperymentu porównawczego.

15.8. Chat jako najniższe źródło prawdy

Chat nie może wydawać poleceń, ale musi wydawać "Proceed".

Rekomendacja: rozróżnić:

- operational mutation commands,
- control signals,
- clarification responses,
- emergency stop.

---

CZĘŚĆ III — CHRONOLOGIA EWOLUCJI

16. Chronologia funkcjonalna

Etap 0 — praktyczne źródło w projekcie PUR

Problemy:

- utrata kontekstu,
- duplikacja modułów,
- zapominanie decyzji,
- lokalnie poprawne, globalnie błędne zmiany,
- sukces bez dowodu,
- brak trwałego stanu.

Odpowiedź:

- pliki instrukcji,
- TODO,
- testy,
- changelogi,
- ręczny handoff,
- człowiek jako orchestrator.

Etap 1 — v2.1: programowanie wykonania

Przełom:

todo.md nie jest listą
todo.md jest programem

Powstają atomowość, weryfikowalność i task ISA.

Etap 2 — v3.0: system operacyjny repozytorium

Przełom:

Task Register
+ Control Plane
+ Protocol Zero
+ Bootstrap Mode

FS-ASM staje się metodologią całego workflow.

Etap 3 — Bootstrap Protocol: kompilacja domeny

Przełom:

Planning Agent = compiler
files = Context Programming Language

Pojawia się formalny proces od dokumentacji do wykonania.

Etap 4 — v4.0: hardening

Przełom:

hierarchical lock
external memory
usage anchors
symbol table
trap task
fingerprinting

Critical Addendum pokazuje, że znaczna część tych reguł była formalizacją konkretnych rozwiązań i awarii z projektu PUR. `Ciąg Logiczny` następnie opisuje pięcioetapowy runtime oraz ryzyko, że model może pozornie spełniać tekstowe kontrole.

Etap 4A — assurance i analiza failure modes

Przełom:

```text
file-based state nie usuwa halucynacji
→ ryzyko przenosi się na interpretację i compliance
→ potrzebne są mechaniczne walidatory i dowody
```

Etap 5 — v5.1/v6.0: modularna finalizacja starej architektury

Potwierdzony przyrost v6.0:

modularizacja v5.1
+ silniejszy, domenowy Input Quality Gate
+ kanoniczny INPUT_QUALITY_REPORT
+ wzorce DATA-GAP i PHYSICS-CRITICAL
+ Controlled Dynamics dla PHYSICS-CRITICAL
+ rozszerzona self-verification

Protocol Zero, OODA, Parent–Child, Trap Task, usage anchors, Symbol Table i Task-Specific Memory pozostają odziedziczone. v6 rozszerza kontrolę jakości procesu projektowego, ale nie przebudowuje runtime i nie rozdziela jeszcze specyfikacji według odbiorców.

Etap 6 — v7.0: izolacja ról

Przełom:

Planning Agent czyta metodologię
Coding Agent czyta skompilowany bundle

Usunięty zostaje fundamentalny błąd wspólnej specyfikacji.

Etap 7 — v7.1: kompletna specyfikacja kompilatora

Przełom:

- połączenie czystej architektury v7 z detalami v6,
- pełny execution loop,
- pełny quality gate,
- pełne typed tasks,
- self-verification.

---

CZĘŚĆ IV — REKOMENDACJE DLA NOWEGO FS-ASM

17. Rdzeń, który należy zachować

17.1. Model systemu

Human Knowledge
→ Planning Compiler
→ Validated Artifact Bundle
→ Coding Runtime
→ Evidence and State Updates

17.2. Trzy płaszczyzny

Zachować:

- Control Plane,
- State Register,
- Execution Plane.

Dodać czwartą:

- Evidence Plane.

Control Plane
- prawa, architektura, kontrakty

State Plane
- task graph, statusy, blokery

Execution Plane
- kod, testy, narzędzia

Evidence Plane
- wyniki testów, metryki, fingerprinty, logi

17.3. Task Contract

Każdy Child Task powinien mieć:

id:
parent:
action:
target:
inputs:
constraints:
dependencies:
allowed_files:
verification:
evidence:
retry_policy:
escalation:
memory_updates:

17.4. Bounded autonomy

- automatyczna realizacja Child Tasks w granicach Parent,
- gate na końcu Parent,
- natychmiastowy stop dla naruszeń polityk,
- ograniczone retry wyłącznie dla zadań oznaczonych jako retryable.

17.5. Quality Gate

Zachować IQ-01–IQ-06, ale wynik zapisywać w strukturalnym formacie.

---

18. Elementy do usunięcia lub przeprojektowania

Usunąć

- wspólną specyfikację dla Planning i Coding Agenta,
- obowiązkowy Trap Task w realnym backlogu,
- obowiązek ręcznej Symbol Table,
- archiwizowanie każdego zastępowanego modułu,
- retoryczne hard stops jako jedyny mechanizm ochrony,
- niestabilną numerację HC,
- duplikaty v3.0,
- niejednoznaczne nazwy wersji i canonical filenames.

Przeprojektować

- "todo.md" → strukturalny Task Register z czytelnym renderem Markdown,
- handshake → krótki state acknowledgement z identyfikatorem tasku i wersją bundle,
- "MEMORY.md" → ADR + osobny assumptions register,
- "admin/" → generowane execution records,
- input report → provenance manifest,
- usage anchors → formalne canonical workflows,
- dependency allowlist → mechaniczna kontrola manifestu.

---

19. Proponowana nowa architektura dokumentów

fsasm/
├── methodology/
│   ├── PLANNING_AGENT_SPEC.md
│   ├── ARTIFACT_SCHEMA.md
│   ├── TASK_SCHEMA.md
│   └── POLICY_CATALOG.md
│
├── project-bundle/
│   ├── .agent/
│   │   ├── ENTRYPOINT.md
│   │   ├── POLICY.md
│   │   ├── ARCHITECTURE.md
│   │   ├── STATE.yaml
│   │   ├── ASSUMPTIONS.yaml
│   │   └── CAPABILITIES.yaml
│   ├── tasks/
│   │   └── task-register.yaml
│   ├── evidence/
│   ├── decisions/
│   └── execution-logs/
│
└── tools/
    ├── validate_bundle
    ├── validate_tasks
    ├── check_dependencies
    ├── check_task_scope
    └── render_markdown

Markdown może pozostać warstwą czytelną dla człowieka, ale stan i kontrakty powinny mieć walidowalny format.

---

20. Ostateczna ocena wersji

Najważniejszy fundament

v2.1 — ponieważ definiuje "todo.md" jako wykonywalny program.

Najważniejsze rozszerzenie systemowe

v3.0 — ponieważ tworzy Control Plane i Bootstrap Mode.

Najbardziej innowacyjny artefakt Planning Agenta

Project Agent Bootstrap Protocol — ponieważ definiuje Context Programming Language i czterofazową kompilację domeny.

Najbardziej eksperymentalna wersja

v4.0 — ponieważ wprowadza wiele mechanizmów hardeningu, zarówno trafnych, jak i nadmiarowych.

Najpełniejsza modularna konsolidacja starej linii

v6.0 — ponieważ finalizuje architekturę v4/v5.1 bez breaking changes, porządkuje ją w moduły oraz wzmacnia domenowy Quality Gate i Controlled Dynamics dla `[PHYSICS-CRITICAL]`. Nie jest jednak głównym przełomem runtime.

Najważniejsza korekta architektoniczna

v7.0 — ponieważ izoluje role i definiuje właściwy model kompilacji.

Najbardziej kompletna istniejąca specyfikacja

v7.1 — ponieważ łączy izolację ról z v7 z wybranymi detalami v6, jednocześnie generalizując jej fizyczne mechanizmy na szersze klasy projektów.

Najważniejszy artefakt pochodzenia reguł

Critical Specification Addendum — ponieważ bezpośrednio mapuje rozwiązania z Execution Plane PUR na dyrektywy metodologii.

Najważniejszy artefakt analizy ryzyka

Ciąg Logiczny Działania + błędylog — ponieważ identyfikuje interpretacyjny dryft pozostający mimo plikowego stanu i pokazuje potrzebę osobnego Assurance Model.

Najlepsza baza dla nowego FS-ASM

Nie należy przyjmować żadnej wersji w całości.

Najlepszy rdzeń to:

v2.1:
task-as-code

v3.0:
control/state/execution separation

Bootstrap Protocol:
planning compiler

v4.0:
usage anchors, task memory, fingerprinting

v6.0:
modularization, input quality gate, DATA-GAP/PHYSICS patterns,
controlled dynamics for physics-critical tasks

v7.0:
strict role isolation

v7.1:
complete planning workflow and self-verification

---

21. Konkluzja

FS-ASM nie jest przede wszystkim zestawem promptów dla Coding Agenta.

Jest metodą:

«kompilowania wiedzy, ograniczeń, architektury i planu pracy do trwałego, audytowalnego i wykonywalnego stanu plikowego.»

Największą wartością projektu nie jest konkretny handshake, nazwa katalogu ".ai" ani liczba Hard Constraints.

Największą wartością jest odkrycie czterech zasad:

1. Stan agentowego procesu powinien być materializowany poza modelem.
2. Planowanie i wykonanie powinny być rozdzielone.
3. Każde działanie powinno mieć obiektywny dowód ukończenia.
4. Autonomia powinna być ograniczana przez jawne granice, retry budget i warunki eskalacji.

To właśnie te zasady powinny stanowić fundament następnej wersji.