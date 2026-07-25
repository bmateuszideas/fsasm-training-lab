# FS-ASM — origin and current understanding

## Cel dokumentu

Ten plik jest przenośnym snapshotem kontekstu projektu FS-ASM. Ma pozwolić
lokalnemu agentowi kontynuować pracę bez odtwarzania całej historii rozmów
z projektu ChatGPT.

Nie zastępuje dokumentów źródłowych FS-ASM. Dokumentuje aktualne decyzje,
ograniczenia, stan lokalnego projektu i najbliższy kierunek.

Szczegółowe wyniki audytu przeniesionych dokumentów:

- `docs/FSASM_SOURCE_INVENTORY.md` — lista, duplikaty, kompletność
  i wiarygodność źródeł,
- `docs/FSASM_SOURCE_AUDIT.md` — wnioski merytoryczne i ich wpływ na
  Training Lab.

## Cel projektu

FS-ASM ma służyć jako materiał badawczy i edukacyjny do praktycznej nauki:

- projektowania workflowów agentowych i multi-agentowych,
- orkiestracji ról,
- utrzymywania stanu poza kontekstem modelu,
- weryfikacji wyników,
- kontrolowania retry i zatrzymań,
- rejestrowania przebiegu wykonania.

Nie tworzymy teraz kolejnej „ostatecznej” wersji metodologii ani pełnej
implementacji FS-ASM v7. Najpierw budujemy mały, lokalny i obserwowalny
workflow, który pozwoli zrozumieć mechanizmy.

## Geneza i ewolucja FS-ASM

FS-ASM powstało jako sposób organizowania pracy bezstanowego Coding Agenta
przez pliki w repozytorium. Główne założenie: historia czatu nie jest
niezawodną pamięcią projektu, więc instrukcje, decyzje, zadania i stan
operacyjny muszą być utrzymywane poza modelem.

Pierwotny układ obejmował:

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

`todo.md` miał być programem wykonawczym i rejestrem stanu, nie zwykłą listą
zadań.

### Wersje istotne dla dalszej pracy

- **v2.1 — TODO as Code:** zadania atomowe, możliwie jednoznaczne,
  uporządkowane i zakończone obiektywnym kryterium `Verification`.
- **v3/v4:** Control Plane, Protocol Zero, OODA, hierarchia konfliktów,
  scratchpad jako write-ahead log i zewnętrzna pamięć decyzji. Wersje te
  pokazały również koszt nadmiernie rozbudowanych i imperatywnych instrukcji.
- **v6:** według finalnego audytu była modularną finalizacją v5.1,
  wzmacniającą Input Documentation Quality Gate, jawne luki i Controlled
  Dynamics. Bezpośrednie pliki źródłowe v6.0 nie znajdują się jednak
  w obecnie przeniesionym zbiorze, więc jest to ustalenie pośrednie.
- **v7/v7.1:** rozdzielenie Planning Agenta od Coding Agenta. Planner czyta
  metodologię i tworzy samowystarczalny pakiet wykonawczy. Rozwinięto Parent
  Tasks, Child Tasks, bounded retries, task-specific logs, quality gate
  dokumentacji wejściowej i zatrzymania na granicach Parent Tasks.

Najnowsza wersja dokumentu nie jest automatycznie wersją kanoniczną. Źródła
mają być materiałem do porównania i testów.

## Przyjęty model pierwszego systemu

```text
Human Input
    ↓
Orchestrator
    ↓
Planner
    ↓
Task Register
    ↓
Executor
    ↓
Verifier
    ↓
Persistent State / Audit Log
    ↓
Human Gate
```

Historyczne FS-ASM opisywało przede wszystkim handoff Planning Agent → pliki
→ Coding Agent. Training Lab nie implementuje tego handoffu literalnie.
Buduje działający runtime, w którym Planner, Executor i Verifier są rolami
wywoływanymi przez Orchestrator.

Pierwsze MVP ma najwyżej cztery logiczne role:

- **Orchestrator:** routing, przejścia stanu, retry, błędy, zatrzymania
  i bramki zatwierdzenia.
- **Planner:** zamiana celu użytkownika na plan, zadania i kryteria
  zakończenia.
- **Executor:** wykonanie dokładnie jednego aktywnego zadania i zwrócenie
  ustrukturyzowanego wyniku albo jawnego błędu.
- **Verifier:** niezależna ocena wyniku i decyzja `PASS`, `FAIL` albo
  `NEEDS_HUMAN`.

Role mogą początkowo korzystać z tego samego modelu Mistral, ale muszą mieć
oddzielne prompty, dane wejściowe, schematy wyjścia, odpowiedzialności
i granice decyzyjne.

## Mechanizmy zachowane z FS-ASM

- **Externalized state:** stan nie może zależeć od pamięci modelu.
- **Task register:** aktywne zadania istnieją jako dane.
- **Atomicity:** jedno zadanie odpowiada jednemu spójnemu przejściu stanu.
- **Verification gate:** deklaracja Executora nie jest dowodem ukończenia.
- **Role separation:** planowanie, wykonanie i weryfikacja są rozdzielone.
- **Structured outputs:** wyniki agentów są walidowane przez schemat.
- **Audit trail:** zapisujemy wejście, wyjście, decyzję, błąd, retry, czas
  i użyty model.
- **Evidence plane:** deklarowany rezultat i dowód jego poprawności są
  osobnymi danymi.
- **Bounded retries:** workflow nie może naprawiać się w nieskończoność.
- **Human gates:** wybrane przejścia wymagają decyzji użytkownika.

## Hipotezy wymagające testów

Nie przyjmować bez pomiarów:

- bezwzględnego odrzucania poleceń z czatu,
- obowiązkowego handshake przed każdym krokiem,
- Trap Tasks w produkcyjnym rejestrze — nie będą elementem pierwszego
  runtime,
- założenia, że imperatywny język zapewnia posłuszeństwo modelu,
- kopiowania pełnych instrukcji do każdego wywołania,
- założenia o deterministyczności uzyskiwanej wyłącznie promptem,
- archiwizowania każdej starej implementacji zamiast korzystania z Git,
- ręcznie utrzymywanej globalnej Symbol Table.

## Mixture of Experts

Neuralne Mixture of Experts nie jest celem pierwszego etapu. Późniejszym
eksperymentem może być routing ekspertów na poziomie workflow:

```text
Task
├── architecture   → Architecture Agent
├── implementation → Coding Agent
├── verification   → Verification Agent
└── research       → Research Agent
```

Kolejne możliwe eksperymenty: router regułowy, router LLM, kilku ekspertów
pracujących równolegle, judge wybierający wynik, różne modele dla różnych ról
i routing na podstawie historii skuteczności.

## Stan i formaty wykonawcze

Markdown jest warstwą czytelną dla człowieka, ale nie powinien być jedynym
formatem runtime. Początkowo stan ma być przechowywany w JSON; SQLite można
rozważyć później.

Schematy mają być walidowane przez Pydantic. Pełniejszy docelowy kontrakt
zadania powinien przewidywać: `id`, `parent_id`, `action`, `target`, `inputs`,
`constraints`, `dependencies`, `allowed_files`, `verification`,
`expected_evidence`, `retry_policy`, `escalation`, `memory_updates`
i `status`.

Minimalny rekord zadania:

```json
{
  "task_id": "TASK-001",
  "parent_id": "PARENT-001",
  "status": "pending",
  "assigned_role": "planner",
  "input": {},
  "constraints": [],
  "verification": {
    "type": "schema",
    "expected": "valid_plan"
  },
  "attempt": 0,
  "max_attempts": 3
}
```

## Środowisko i ograniczenia

- System: Windows.
- Lokalny projekt: `C:\fsasm-training-lab\fsasm-first`.
- Język: Python; projekt deklaruje Python `>=3.12`.
- Zarządzanie środowiskiem i zależnościami: `uv`.
- Dostawca modelu na początek: Mistral API.
- Framework do pierwszego eksperymentu: Mistral Workflows, bez zobowiązania
  do użycia go w całej późniejszej architekturze.
- Testy: `pytest`; logikę workflow testować głównie z mockami.
- Stan runtime: początkowo JSON.
- Budżet Mistral API: około 10 EUR miesięcznie.

Z tego wynikają zasady kosztowe:

- krótkie prompty,
- kontrolowana liczba wywołań,
- brak niepotrzebnej pracy równoległej agentów,
- rzeczywiste wywołania API głównie w testach integracyjnych,
- testy logiki bez wywoływania płatnego modelu, gdy to możliwe.

## Zweryfikowany stan lokalnego projektu — 2026-07-25

Wbrew starszemu snapshotowi środowisko lokalne zostało już utworzone:

- istnieje scaffold projektu Mistral Workflows,
- istnieją `pyproject.toml`, `uv.lock`, `.venv` i pliki startowe,
- zainstalowane środowisko zawiera `mistralai-workflows` 3.9.0,
- plik `.env` istnieje i zawiera nazwy zmiennych konfiguracyjnych; wartości
  pozostają tajne,
- istnieje minimalny workflow `hello-world` w `src/workflows/hello.py`,
- istnieją przykładowe cookbooki Mistral w `src/examples/`,
- nie wykryto jeszcze repozytorium Git w `fsasm-first`,
- nie utworzono jeszcze właściwego workflow FS-ASM, schematu stanu ani testów
  projektu,
- zinwentaryzowano i przeanalizowano 14 plików przeniesionych z projektu
  chmurowego,
- wykryto trzy pary dokładnych duplikatów, równoważne warianty v2.1,
  zastąpioną wersję analizy oraz ucięty Project Agent Bootstrap Protocol,
- utworzono `docs/FSASM_SOURCE_INVENTORY.md` i
  `docs/FSASM_SOURCE_AUDIT.md`.

Nie traktować cookbooków w `src/examples/` jako architektury FS-ASM. Są
materiałem referencyjnym dostarczonym przez generator.

## Profil współpracy z użytkownikiem

Projekt jest laboratorium edukacyjnym. Agent powinien:

- wyjaśniać sens każdego istotnego kroku prostym językiem,
- nie zakładać zaawansowanej wiedzy programistycznej,
- prowadzić przez małe, uruchamialne eksperymenty,
- pokazywać, gdzie fizycznie znajdują się pliki i stan,
- unikać przedwczesnego dokładania frameworków i infrastruktury,
- nie wykonywać kosztownych wywołań Mistral bez wyraźnej potrzeby.

## Pierwszy kamień milowy

Uruchomić lokalnie jeden prosty, obserwowalny przepływ:

```text
Użytkownik podaje cel
    ↓
Planner tworzy plan trzech kroków
    ↓
Plan jest walidowany przez schemat
    ↓
Plan jest zapisywany do JSON
    ↓
Verifier sprawdza kompletność
    ↓
Wynik i osobny evidence record trafiają do run logu
```

Kryteria ukończenia:

- użytkownik potrafi wskazać pliki workflow i dane runtime,
- wejście i wyjście mają jawne schematy,
- zapis stanu jest widoczny na dysku,
- wynik weryfikacji jest jednoznaczny,
- przejścia stanu są jawne i walidowalne,
- deklaracja wyniku jest oddzielona od dowodu,
- testy logiki działają bez płatnego wywołania modelu,
- co najmniej jeden kontrolowany test integracyjny może użyć Mistral API.

## Poza zakresem pierwszego etapu

Nie budować teraz:

- własnego modelu ani neuralnego MoE,
- kilkunastu agentów,
- bazy wektorowej,
- interfejsu webowego,
- rozproszonej infrastruktury lub Kubernetesa,
- kilku frameworków agentowych jednocześnie,
- literalnej implementacji całego FS-ASM v7,
- kolejnej wielkiej specyfikacji przed działającym workflow.

## Następne działania

1. Przejrzeć uruchomienie istniejącego `hello-world`, bez modyfikowania
   przykładów referencyjnych.
2. Ustalić minimalne schematy wejścia, planu i wyniku weryfikacji.
3. Zaimplementować pierwszy edukacyjny workflow obok `hello-world`.
4. Zapisywać plan, weryfikację i metadane wykonania w lokalnym katalogu
   runtime.
5. Dodać testy schematów i przejść stanu z mockowanym modelem.
6. Dopiero potem uruchomić kontrolowany test z Mistral API.
7. Jeśli zostaną dodane brakujące źródła v5.1/v6.0, uzupełnić inventory
   i ponownie sprawdzić wnioski o tych wersjach.

## Instrukcja dla kolejnego agenta

1. Przeczytaj ten dokument przed planowaniem zmian.
2. Zweryfikuj bieżący stan plików zamiast ufać starszym opisom.
3. Nie zakładaj, że najnowsza wersja FS-ASM jest najlepsza.
4. Nie implementuj pełnego v7 bez osobnej decyzji użytkownika.
5. Utrzymuj stan, decyzje i wyniki w lokalnych plikach.
6. Chroń sekrety z `.env`; nigdy nie umieszczaj ich w dokumentacji ani logach.
7. Preferuj najmniejszy eksperyment, który daje obserwowalny i testowalny
   rezultat.
8. Nie czytaj dokładnych duplikatów źródeł; korzystaj z inventory.
9. Nie przedstawiaj twierdzeń o v6.0 jako lokalnie zweryfikowanych na
   źródłach pierwotnych, dopóki pakiet v6.0 nie zostanie dodany.
