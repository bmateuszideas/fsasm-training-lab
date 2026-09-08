# FS-ASM — aktualny model projektu, cel i kierunek rozwoju

**Status:** aktualne źródło prawdy dla dalszego rozwoju projektu  
**Nazwa:** FS-ASM — File System as State Machine  
**Charakter projektu:** edukacyjny, badawczy i eksperymentalny  
**Cel dokumentu:** opisać uzgodniony sens projektu, jego genezę, zasady architektoniczne, docelowy kierunek techniczny oraz kolejność dalszego rozwoju.

---

## 1. Cel projektu

FS-ASM nie ma być kolejnym frameworkiem agentowym budowanym dla samego frameworka.

Celem projektu jest zbadanie i praktyczne zbudowanie systemu, w którym:

- stan projektu istnieje poza LLM-em,
- zadania są atomowe i jednoznaczne,
- modele pełnią ograniczone role,
- twarde reguły są egzekwowane przez zwykły kod,
- wynik pracy modelu nie jest uznawany za prawdę bez Verification i Evidence,
- runtime kontroluje routing, retry, statusy, limity i Human Gates,
- kontekst dla modelu jest budowany tylko z informacji rzeczywiście potrzebnych dla aktualnego taska,
- różne modele mogą być dobierane do różnych rodzajów pracy,
- lokalny, wyspecjalizowany model może być tanim workerem,
- większe modele API mogą przejmować planowanie, trudne decyzje i eskalacje,
- człowiek pozostaje nadzorcą systemu, a nie ręcznym routerem między modelami.

Najkrócej:

> **FS-ASM ma utrzymywać stan, kontrolę i weryfikację w deterministycznym runtime, a LLM wykorzystywać jako wymienny komponent poznawczy wykonujący precyzyjnie ograniczone role.**

---

## 2. Geneza FS-ASM

FS-ASM powstało z praktycznego problemu podczas hobbystycznego projektu programistycznego.

Pierwotny workflow wyglądał funkcjonalnie tak:

```text
Użytkownik
    ↓
ChatGPT
Planner / Architect
    ↓
projektuje program, architekturę,
TODO i instrukcje wykonawcze
    ↓
ręczny handoff
Ctrl+C / Ctrl+V
    ↓
filesystem projektu
    ↓
Codex w VS Code
Coding Executor
    ↓
kod / testy / stan / log
```

Człowiek pełnił funkcję:

```text
orchestratora
+
routera
+
transportu między modelami
+
Human Gate
+
nadzorcy
```

Planner i Executor byli więc funkcjonalnie rozdzieleni już od początku:

```text
ChatGPT
= Planner / Architect

filesystem
= persistent state + handoff

Codex
= Coding Executor
```

Późniejsze wersje FS-ASM nie stworzyły tego podziału od zera. Zaczęły go formalizować i dostosowywać do współczesnej architektury agentowej.

---

## 3. Problem, który doprowadził do powstania FS-ASM

Głównym ograniczeniem nie była niezdolność modelu do napisania kodu.

Problemem była utrata spójnego kontekstu projektu w czasie.

Typowy mechanizm awarii wyglądał tak:

```text
Codex tworzy kod
    ↓
projekt rośnie
    ↓
starsze założenia wypadają z kontekstu
    ↓
model traci obraz wcześniejszej architektury
    ↓
pojawia się błąd
    ↓
model wykonuje lokalną poprawkę
    ↓
nie pamięta wszystkich zależności
    ↓
naprawa jednego elementu
psuje kolejne
```

Z tego wynikła podstawowa intuicja FS-ASM:

> **stan projektu nie może istnieć wyłącznie w kontekście LLM-a.**

Historia czatu nie jest niezawodną pamięcią projektu.

Instrukcje, decyzje, zadania, stan wykonania i dowody powinny istnieć poza modelem.

---

## 4. Pierwotny filesystem jako substytut brakującego runtime'u

W pierwotnym środowisku nie było własnej programowej warstwy, która mogłaby twardo sterować Codexem.

Filesystem zaczął więc jednocześnie pełnić funkcję:

```text
filesystem
=
persistent state
+
pamięć
+
handoff
+
instrukcje
+
control plane
+
task register
+
audit log
```

Historycznie pojawiły się warstwy odpowiadające później:

```text
Control Plane
.ai/INSTRUCTIONS.md
.ai/STANDARDS.md
.ai/ARCHITECTURE.md
.ai/MEMORY.md

State Register
todo.md

Execution Plane
src/
tests/
admin/
```

`todo.md` nie było zwykłą listą rzeczy do zrobienia.

Było traktowane jako wykonywalny program kroków i rejestr stanu.

---

## 5. TODO as Code i atomowość zadań

Jedną z podstaw FS-ASM było rozbicie dużego celu na małe, jednoznaczne zadania.

Schemat:

```text
TASK-001
↓
wykonaj jeden precyzyjny zakres
↓
zweryfikuj
↓
zapisz wynik i stan
↓
TASK-002
```

Dobry task powinien określać:

- konkretny cel,
- konkretny zakres,
- plik lub komponent,
- funkcję lub element do zmiany,
- ograniczenia,
- oczekiwany rezultat,
- Verification,
- wymagane Evidence.

Przykład:

```text
Zmodyfikuj validate_config()
w config_validator.py,
aby brak pressure_limit
powodował ValidationError.

Nie zmieniaj publicznego API.

Verification:
test_missing_pressure_limit musi przejść.
```

Atomowość pozostaje jednym z fundamentów współczesnego FS-ASM.

---

## 6. Stary FS-ASM jako tekstowa emulacja programu

Pierwotny FS-ASM próbował słownie emulować program sterujący, którego technicznie nie można było wtedy podłączyć do modelu.

Dzisiejsze:

```python
if verification_failed:
    stop()
```

musiało wtedy istnieć jako instrukcja dla LLM-a:

```text
Jeżeli Verification zakończy się błędem:
- nie oznaczaj zadania jako DONE,
- zapisz błąd,
- nie przechodź dalej.
```

LLM był jednocześnie:

```text
wykonawcą
+
interpreterem reguł
+
częścią control flow
+
strażnikiem własnego zachowania
```

To było rozwiązanie wynikające z ówczesnych ograniczeń, a nie docelowy model architektury.

---

## 7. Fundamentalna wada starego podejścia

Instrukcja zapisana w promptach nie jest twardą regułą programu.

```text
"Nie przechodź dalej przy FAIL"
```

oznaczało jedynie:

```text
model powinien tego przestrzegać
```

a nie:

```text
przejście jest technicznie niemożliwe
```

Z tego wynika kluczowa zasada współczesnego FS-ASM:

> **model nie powinien być jednocześnie wykonawcą oraz jedynym strażnikiem reguł, którym sam podlega.**

---

## 8. Koszt kontekstowy starego FS-ASM

Stary system wymagał od modelu ciągłego przetwarzania zasad samego FS-ASM.

Był to duży „control tax” płacony tokenami i kontekstem.

Nowy FS-ASM ma przenieść tę logikę do zwykłego kodu.

---

## 9. Najważniejsza zasada współczesnego FS-ASM

Stary model:

```text
LLM
pilnuje systemu
i samego siebie
```

Nowy model:

```text
SYSTEM / RUNTIME
pilnuje LLM-a
```

Podstawowa zasada:

> **Jeżeli coś można jednoznacznie i niezawodnie rozstrzygnąć kodem, nie należy pytać o to LLM-a.**

Przykłady:

```text
Czy plik istnieje?
→ kod

Czy test przeszedł?
→ kod

Czy retry_count osiągnął limit?
→ kod

Czy EvidenceRecord istnieje?
→ kod

Czy model próbuje edytować niedozwolony plik?
→ kod

Jak naprawić funkcję?
→ LLM

Jak rozbić niejednoznaczny cel?
→ LLM

Jak zinterpretować nietypowy problem?
→ LLM
```

CPU/runtime realizuje rzeczy deterministyczne.

LLM jest komponentem poznawczym.

---

## 10. LLM, Runtime, Agent i Orchestrator

### LLM

Model neuronowy:

```text
input
↓
LLM
↓
output
```

### Runtime

Zwykły program komputerowy odpowiedzialny za:

- pętlę wykonania,
- state,
- tool calling,
- retry,
- timeout,
- routing,
- uprawnienia,
- walidację,
- zapis wyników.

### Agent

Agent jest komponentem/systemem używającym LLM-a w pętli:

```text
state
↓
LLM
↓
action
↓
runtime wykonuje action
↓
observation
↓
LLM
↓
kolejna action
```

### Orchestrator

Orchestrator steruje przepływem pomiędzy rolami.

Może być całkowicie deterministyczny.

Nie musi być LLM-em.

---

## 11. Planner

Planner jest rolą, a nie runtime'em.

Może być zrealizowany jako:

```text
zwykły algorytm
```

lub:

```text
jedno wywołanie LLM
```

lub:

```text
pełny Planner Agent
=
LLM + tools + state + własna pętla
```

Pierwszy sensowny wariant:

```text
Runtime
↓
Planner
↓
Mistral
↓
structured Plan
↓
runtime waliduje Plan
```

---

## 12. Docelowe role logiczne

Minimalny system powinien zawierać cztery logiczne role:

```text
Orchestrator
Planner
Executor
Verifier
```

Role mogą korzystać z tego samego modelu lub różnych modeli.

Mają jednak różne:

- prompty,
- wejścia,
- wyjścia,
- uprawnienia,
- zakres odpowiedzialności.

---

## 13. Docelowy rdzeń architektury

```text
                   HUMAN
                     │
                     ▼
             FS-ASM RUNTIME
             / ORCHESTRATOR
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
     PLANNER      EXECUTOR      VERIFIER
        │            │            │
        ▼            ▼            ▼
      LLM          LLM          LLM
        │            │            │
        └────────────┼────────────┘
                     │
               PERSISTENT STATE
                     │
          ┌──────────┼───────────┐
          │          │           │
       TASKS      EVIDENCE    AUDIT LOG
```

Pełniejsza ścieżka:

```text
Human Goal
↓
Planner
↓
Plan / Parent Tasks / Child Tasks
↓
Schema Validation
↓
Task Register
↓
Context Builder / Retrieval
↓
Executor
↓
Tools
↓
Result
↓
Deterministic Verification
+
optional LLM Verifier
↓
PASS
FAIL
RETRY
ESCALATE
NEEDS_HUMAN
↓
Persistent State
```

---

## 14. Twarda logika runtime'u

Runtime powinien kontrolować co najmniej:

- dozwolone przejścia statusów,
- kolejność tasków,
- zależności,
- maksymalną liczbę retry,
- allowed files,
- timeouty,
- limity kosztowe,
- dostęp do tools,
- walidację structured outputs,
- zapis state,
- zapis evidence,
- zatrzymania,
- Human Gates.

Kluczowa zasada:

```text
Executor:
"DONE"

runtime:
sprawdza Evidence i Verification

FAIL
→ task NIE może dostać PASS
```

Deklaracja modelu nie jest źródłem prawdy.

---

## 15. State, Memory i Retrieval

### State

Opisuje to, co dzieje się teraz.

### Memory

Opisuje trwałą wiedzę: decyzje, ograniczenia, przyczyny wcześniejszych wyborów i informacje potrzebne w kolejnych uruchomieniach.

### Retrieval / RAG

Odpowiada na pytanie:

```text
który fragment wiedzy
jest potrzebny modelowi TERAZ?
```

---

## 16. LLM jako stateless worker

LLM może być traktowany jako praktycznie bezstanowy worker.

```text
call #1
fresh context
↓
LLM
↓
result
↓
runtime zapisuje state

call #2
fresh context
↓
runtime podaje aktualny state
↓
LLM
```

Najważniejsza zasada:

> **LLM nie pamięta procesu. System pamięta proces.**

---

## 17. Context Builder i RAG

Model nie powinien otrzymywać całego repozytorium ani całej dokumentacji.

Dla dokumentów:

```text
documents
↓
chunks
↓
embeddings
↓
vector search
↓
relevant text
↓
LLM
```

Dla kodu retrieval powinien być hybrydowy:

```text
semantic vector search
+
exact text search
+
symbol search
+
AST / Tree-sitter
+
imports
+
LSP
+
dependency / call graph
```

Docelowy pakiet kontekstu:

```text
ChildTask
+
relevant source code
+
relevant tests
+
relevant interfaces
+
relevant architectural decisions
+
minimalne potrzebne logi
```

---

## 18. Mistral jako pierwszy dostawca modeli

Mistral API jest preferowanym pierwszym środowiskiem eksperymentalnym.

FS-ASM powinien jednak pozostać:

```text
model-agnostic
+
możliwie framework-agnostic
```

Mistral może początkowo pełnić role takie jak:

- Planner,
- Expert,
- trudniejszy Executor,
- Replanner,
- semantic Verifier.

Mistral Workflows może służyć jako framework pierwszych eksperymentów, ale nie jest celem samym w sobie.

---

## 19. Routing modeli

FS-ASM nie powinien zakładać, że jeden model wykonuje wszystko.

Docelowo runtime może dobierać model według:

- roli,
- trudności,
- kosztu,
- modalności,
- historii skuteczności.

Przykład:

```text
planning / architecture
→ większy Mistral

prosty coding task
→ lokalny coding model

trudniejszy coding task
→ tani Mistral coder

bardzo trudny reasoning
→ większy model

OCR
→ OCR model

vision
→ vision model
```

Najlepsza zasada:

> **użyj najtańszego modelu, który ma wystarczające kompetencje dla danego kroku.**

---

## 20. Lokalny wyspecjalizowany Coding Worker

Jednym z ważnych dalszych kierunków jest lokalny model około 6–9B.

Nie jako ogólny „mały ChatGPT”.

Jako:

```text
wyspecjalizowany Coding Worker
```

Powinien wykonywać małe, dobrze określone zadania:

- edycja jednej funkcji,
- poprawa jednego testu,
- prosty refactor,
- analiza małego fragmentu kodu,
- klasyfikacja błędu,
- structured tool call,
- prosty retry po FAIL.

Warunki skuteczności:

```text
atomowy task
+
dobry context builder
+
code retrieval
+
tools
+
zewnętrzna Verification
```

---

## 21. Lokalny worker nie musi znać wszystkiego

Jeśli lokalny model nie posiada potrzebnej wiedzy:

```text
LOCAL WORKER
↓
NEEDS_INFORMATION
```

runtime może zdecydować:

```text
czy informacja jest lokalna?
→ retrieval

czy potrzebna dokumentacja?
→ docs search

czy potrzebny internet?
→ web search

czy potrzebny mocniejszy reasoning?
→ Mistral API

czy potrzebna decyzja człowieka?
→ Human Gate
```

Mistral może również działać jako narzędzie eksperckie:

```text
ask_expert(question)
```

---

## 22. Hierarchia ekonomiczna modeli

Potencjalny docelowy układ:

```text
LOCAL CODER
↓
domyślny worker

brak informacji
↓
RAG / code search / docs

zewnętrzna wiedza
↓
web / API

problem przekracza kompetencje
↓
tani Mistral

bardzo trudny problem
↓
większy Mistral

decyzja krytyczna
↓
HUMAN
```

Celem nie jest maksymalizacja liczby agentów.

Celem jest efektywne wykorzystanie odpowiednich kompetencji.

---

## 23. Fine-tuning przyszłego FS-ASM Workera

Fine-tuning lokalnego modelu nie jest elementem pierwszej implementacji.

Przyszły model może być dostrojony nie tylko do kodowania, ale do konkretnego protokołu FS-ASM.

Może znać:

- swoją rolę,
- format ChildTask,
- format structured output,
- dostępne rodzaje tools,
- procedurę `NEEDS_CONTEXT`,
- procedurę `ESCALATE`,
- zasady ograniczania scope,
- fakt, że nie jest Plannerem,
- fakt, że nie decyduje sam o PASS,
- sposób reagowania na tool results,
- sposób raportowania błędów.

Wagi modelu powinny zawierać:

```text
JAK działać w FS-ASM
```

ale nie:

```text
CO obecnie dzieje się w projekcie
```

Dynamiczny state pozostaje poza modelem.

---

## 24. Dataset z realnych trajektorii

Działający FS-ASM będzie produkował trajektorie:

```text
ChildTask
↓
retrieved context
↓
tool call
↓
tool result
↓
kolejna decyzja
↓
patch
↓
test
↓
Verifier
↓
Evidence
↓
PASS / FAIL
```

Z takich trajektorii można później wybrać najlepsze przykłady i przygotować dataset:

```text
dobry bazowy coder 7B/8B
↓
SFT / LoRA / QLoRA
↓
FS-ASM trajectories
↓
FS-ASM Worker
↓
quantization
↓
lokalne wykonanie
```

Fine-tuning poprawia zachowanie modelu.

Runtime nadal egzekwuje twarde reguły.

---

## 25. Human Gate

Człowiek pozostaje częścią systemu.

Agent może działać autonomicznie tylko w określonych granicach.

Human Gate powinien pojawiać się przy:

- dużej zmianie architektury,
- przekroczeniu scope,
- konflikcie wymagań,
- kosztownej operacji,
- ryzykownej operacji,
- wyczerpaniu retry,
- niepewnym wyniku Verification.

To jest bounded autonomy, nie pełna autonomia.

---

## 26. Evidence Plane

FS-ASM musi rozdzielać deklarację wyniku od dowodu wyniku.

Przykład:

```text
Executor:
"naprawiłem funkcję"

Evidence:
- diff
- wynik testów
- typecheck
- lint
- output narzędzia
```

Stan `PASS` wynika z Verification i Evidence.

Nie z deklaracji LLM-a.

---

## 27. Structured Outputs

Komunikacja pomiędzy rolami powinna być możliwie strukturalna.

Przykładowy ChildTask może zawierać:

```text
id
parent_id
action
target
inputs
constraints
dependencies
allowed_files
verification
expected_evidence
retry_policy
escalation
memory_updates
status
```

Na początku stan powinien być przechowywany w JSON i walidowany przez Pydantic.

SQLite może pojawić się później.

---

## 28. FS-ASM nie jest luźną debatą agentów

Nie chodzi o:

```text
Planner ↔ Executor ↔ Reviewer
luźno rozmawiają
```

Chodzi o:

```text
Human Knowledge
↓
Planning
↓
structured artifact
↓
validation
↓
handoff
↓
execution
↓
evidence
↓
state transition
```

Automatyzowany jest historyczny ręczny handoff.

Nie likwiduje się separacji kontekstów.

Executor nie potrzebuje pełnej historii rozumowania Plannera.

Dostaje samowystarczalny pakiet wykonawczy.

---

## 29. Aktualny charakter projektu

FS-ASM Training Lab jest projektem:

```text
edukacyjnym
+
badawczym
+
eksperymentalnym
```

Projekt ma również służyć nauce:

- programowania agentów,
- runtime'ów,
- orkiestracji,
- state machines,
- tool calling,
- retrieval,
- RAG,
- Verification,
- API,
- pracy z lokalnymi i zewnętrznymi modelami.

---

## 30. Aktualny punkt projektu

Projekt znajduje się pomiędzy:

```text
zakończoną rekonstrukcją
historycznego FS-ASM
```

a:

```text
pierwszą właściwą
implementacją runtime'u
```

Do zbudowania pozostają przede wszystkim:

- deterministyczny rdzeń FS-ASM,
- Pydantic schemas,
- Task Register,
- właściwy persistent state,
- Evidence Records,
- run log,
- Planner/Executor/Verifier runtime,
- testy,
- retrieval,
- później lokalny worker i routing modeli.

---

# Plan dalszego rozwoju

## Etap 0 — aktualne źródło prawdy

Ten dokument pełni rolę aktualnego opisu celu i kierunku projektu.

Starsze materiały pozostają ważne historycznie, ale nie powinny automatycznie narzucać obecnej architektury.

---

## Etap 1 — deterministyczny rdzeń bez LLM

Minimalne obiekty:

```text
GoalInput
Plan
ChildTask
VerificationResult
EvidenceRecord
RunState
```

Do tego:

- state transitions,
- atomic JSON write,
- load/save,
- dependencies,
- retry,
- expected evidence,
- schema validation,
- unit tests.

Cel:

> najpierw sprawdzić, czy sama maszyna działa.

---

## Etap 2 — pierwszy pionowy workflow ze stubem

```text
Goal
↓
Planner Stub
↓
Plan
↓
Schema Validation
↓
JSON State
↓
Verifier
↓
EvidenceRecord
↓
PASS / FAIL
↓
Run Log
```

Jeszcze bez płatnego LLM.

---

## Etap 3 — prawdziwy Planner Mistral

Po działającym stubie:

```text
Planner Stub
↓
Mistral Planner
```

Wymagania:

- structured output,
- model/version w logu,
- prompt version,
- limity liczby wywołań,
- kontrola kosztu,
- test integracyjny.

---

## Etap 4 — Executor + Verifier + retry + Human Gate

```text
Orchestrator
↓
Planner
↓
Executor
↓
Verifier
↓
PASS
RETRY
NEEDS_HUMAN
```

Początkowo na małych, bezpiecznych i kontrolowanych artefaktach.

---

## Etap 5 — Context Builder i retrieval

```text
Task
↓
code search
+
semantic retrieval
+
state
↓
Context Builder
↓
minimalny context
↓
Executor
```

Najpierw:

```text
grep
symbol search
AST
file relationships
```

Dopiero później pełny vector RAG.

---

## Etap 6 — lokalny Coding Worker

Po działającym runtime:

```text
Executor = Mistral
```

może zostać zamieniony lub uzupełniony o:

```text
Executor = Local Coder 6B–9B
```

Celem będzie zbadanie, ile użyteczności można uzyskać z małego, wyspecjalizowanego modelu przy atomowych taskach, dobrym kontekście i zewnętrznej Verification.

---

## Etap 7 — routing modeli i eskalacja

```text
simple task
→ local coder

medium task
→ tani model API

complex task
→ mocniejszy Mistral

missing knowledge
→ retrieval / web

architecture issue
→ Planner

critical ambiguity
→ Human
```

Routing początkowo powinien być możliwie prosty i regułowy.

---

## Etap 8 — eksperyment porównawczy

Ten sam kontrolowany projekt wykonać:

```text
bez FS-ASM
```

oraz:

```text
z FS-ASM
```

Mierzyć między innymi:

- liczbę interwencji człowieka,
- naruszenia scope,
- błędne deklaracje DONE,
- kompletność Evidence,
- możliwość wznowienia po przerwaniu,
- liczbę retry,
- koszt API,
- liczbę wywołań,
- skuteczność lokalnego workera.

---

## Etap 9 — fine-tuning lokalnego FS-ASM Workera

Po zebraniu realnych trajektorii:

```text
base coding model
↓
FS-ASM dataset
↓
agentic/tool-use SFT
↓
FS-ASM Worker
↓
quantization
↓
local runtime
```

---

## Etap 10 — plugin

Plugin jest późniejszym opakowaniem działającego rdzenia.

Możliwy późniejszy przepływ:

```text
ChatGPT
↓
planning / rozmowa projektowa
↓
FS-ASM compiler
↓
validated artifact bundle
↓
Human Gate
↓
MCP bridge
↓
FS-ASM runtime
↓
Coding Executor
↓
Evidence / State
```

Plugin ma korzystać ze sprawdzonego rdzenia.

Nie odwrotnie.

---

# Czego obecnie nie robić

Na tym etapie nie należy:

- budować kilkunastu agentów,
- trenować własnego modelu,
- budować neuralnego MoE,
- stawiać vector DB zanim istnieje potrzeba,
- dodawać kilku frameworków agentowych naraz,
- budować web UI,
- tworzyć rozproszonej infrastruktury,
- implementować literalnie całej historycznej metodologii,
- kopiować wszystkich starych rytuałów FS-ASM,
- zakładać, że prompt może zapewnić deterministyczność,
- próbować od razu budować system produkcyjny.

Najpierw ma powstać mały, sprawdzalny rdzeń.

---

# Pierwszy właściwy milestone

Lokalne polecenie powinno:

```text
1. przyjąć Goal
2. utworzyć trzy ChildTasks
3. zwalidować schema
4. zapisać RunState do JSON
5. utworzyć osobny EvidenceRecord
6. wykonać Verification
7. zakończyć jednoznacznie PASS albo FAIL
```

Początkowo:

```text
bez API
bez Mistrala
bez lokalnego LLM
```

Dopiero potem modele są wkładane w gotowe miejsca systemu.

---

# Najważniejsze zasady FS-ASM

1. **Stan należy do systemu, nie do LLM-a.**
2. **LLM może być stateless workerem.**
3. **Task ma być możliwie atomowy.**
4. **Kod egzekwuje to, co jest deterministyczne.**
5. **LLM jest używany do problemów semantycznych i decyzyjnych.**
6. **Deklaracja modelu nie jest dowodem.**
7. **PASS wymaga Verification i Evidence.**
8. **Retry musi być bounded.**
9. **Context powinien być konstruowany dla taska, nie kopiowany w całości.**
10. **Planner i Executor mają różne odpowiedzialności.**
11. **Model nie musi być jeden.**
12. **Najtańszy wystarczająco kompetentny model powinien wykonywać dany krok.**
13. **Mocniejszy model może być eskalacją, a nie domyślnym workerem wszystkiego.**
14. **Człowiek pozostaje Human Gate dla decyzji przekraczających zdefiniowaną autonomię.**
15. **FS-ASM ma być model-agnostic i możliwie framework-agnostic.**
16. **Model nie powinien być strażnikiem własnych reguł tam, gdzie regułę może egzekwować kod.**
17. **Wiedza o tym, jak działa FS-ASM, może być później częściowo przeniesiona do fine-tuningu workera, ale aktualny state pozostaje poza modelem.**

---

# Docelowa wizja

```text
                           HUMAN
                             │
                             ▼
                    FS-ASM ORCHESTRATOR
                    deterministic runtime
                             │
          ┌──────────────────┼───────────────────┐
          │                  │                   │
          ▼                  ▼                   ▼
       STATE             RETRIEVAL             RULES
    JSON / DB       code + docs + RAG      transitions
          │                  │                   │
          └──────────────────┼───────────────────┘
                             │
                             ▼
                           PLANNER
                       Mistral / other
                             │
                             ▼
                     Parent / Child Tasks
                             │
                             ▼
                       CONTEXT BUILDER
                             │
                             ▼
                          EXECUTOR
               Local specialized coder 6B–9B
                    lub model przez API
                             │
                             ▼
                            TOOLS
               files / git / tests / web /
                 MCP / APIs / expert model
                             │
                             ▼
                           RESULT
                             │
                             ▼
                         VERIFIER
                   deterministic checks
                     + optional LLM
                             │
              ┌──────────────┼─────────────┐
              ▼              ▼             ▼
             PASS           RETRY        ESCALATE
              │                            │
              ▼                            ▼
           EVIDENCE                  Mistral / Human
              │
              ▼
             STATE
              │
              └──────────→ następny ChildTask
```

---

# Ostateczne znaczenie aktualnego kierunku

Pierwotny FS-ASM próbował za pomocą tekstu osiągnąć to, czego nie można było wtedy technicznie wymusić kodem.

Współczesny FS-ASM zachowuje logikę tamtego rozwiązania, ale przenosi odpowiedzialności do właściwych warstw:

```text
tekstowe reguły
→ runtime policy

TODO
→ structured Task Register

MEMORY / dashboard
→ persistent state

changelog
→ audit / evidence log

ręczny handoff
→ orchestrator

ręczne czytanie plików
→ Context Builder / retrieval

Codex pamiętający proces
→ stateless worker

"nie wolno ci przejść dalej"
→ niedozwolone transition w kodzie

"sprawdź czy zrobiłeś"
→ Verification Gate
```

To jest obecnie uzgodniony cel, sens i kierunek dalszego rozwoju projektu FS-ASM.
