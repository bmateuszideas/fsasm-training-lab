# Audyt źródeł FS-ASM — wnioski dla Training Lab

Data: 2026-07-25

Ten dokument zapisuje wnioski wynikające z przeczytania materiałów
przeniesionych z projektu chmurowego. Pełne inventory i ocena wiarygodności
plików znajdują się w `FSASM_SOURCE_INVENTORY.md`.

## Co faktycznie znajduje się w zbiorze

Zbiór obejmuje:

- specyfikację Task Register v2.1,
- pełne specyfikacje v3.0 i v4.0,
- dwa artefakty pomostowe v4,
- niekompletny Project Agent Bootstrap Protocol,
- specyfikacje Planning-Agent-only v7.0 i v7.1,
- finalny audyt porównawczy oraz jego wcześniejszą wersję,
- dokładne duplikaty kilku plików.

Nie obejmuje bezpośrednich źródeł v5.1 i v6.0. Twierdzenia o tych wersjach
są obecnie oparte na finalnym audycie.

## Potwierdzona linia ewolucji

### v2.1 — stan jako program

Najtrwalszy wkład:

- `todo.md` jako wykonywalny rejestr stanu,
- zadanie jako kontrakt strukturalny,
- atomowość,
- obiektywna weryfikacja,
- zależności ułożone jako DAG,
- brak zależności od historii czatu.

### v3.0 — repozytorium jako Control Plane

Najtrwalszy wkład:

- rozdzielenie instrukcji, standardów, architektury, pamięci, strategii
  i bieżącego stanu,
- Bootstrap Mode,
- hierarchia źródeł prawdy,
- OODA jako czytelny model orientacji,
- ADR i write-ahead plan.

Problem: jeden dokument jednocześnie programuje Planning i Coding Agenta,
a obowiązkowy handshake i `Proceed` przed każdym zadaniem nadmiernie
ograniczają autonomię.

### Project Agent — Planning Agent jako kompilator

Najtrwalszy wkład:

```text
Domain Analysis
→ Architecture Design
→ Task Decomposition
→ Materialization
```

Pojęcie Context Programming Language trafnie opisuje pliki jako program
sterujący zachowaniem wykonawcy. Dostępny plik jest jednak ucięty i nie może
być używany jako kompletny protokół.

### v4.0 — hardening i pamięć wielowarstwowa

Warto zachować:

- Parent jako granicę kontekstu, Child jako jednostkę wykonawczą,
- usage anchors,
- tooling-first,
- Task-Specific Memory,
- fingerprinting artefaktów,
- mierzalne kryteria ML/OPT,
- semantyczne nazwy rejestrów.

Nie przyjmować literalnie:

- Trap Tasku w produkcyjnym backlogu,
- ręcznej globalnej Symbol Table,
- archiwizowania starego kodu zamiast korzystania z Git,
- wielkich liter i rytuałów jako substytutu walidacji,
- obowiązkowego TDD bez rozróżnienia typu pracy.

### v6.0 — jakość wejścia

Według finalnego audytu v6.0 porządkuje starszą linię i rozwija:

- Input Documentation Quality Gate,
- `INPUT_QUALITY_REPORT`,
- `[DATA-GAP]`, `[ASSUMPTION]`, `[PHYSICS-CRITICAL]`,
- Controlled Dynamics z retry budget i kryterium konwergencji.

To ustalenie ma obecnie status dowodu pośredniego, ponieważ źródła v6.0 nie
znajdują się w lokalnym zbiorze.

### v7.0/v7.1 — izolacja ról i bounded autonomy

Najtrwalszy wkład:

- tylko Planning Agent zna metodologię,
- wykonawca otrzymuje skompilowany, samowystarczalny pakiet,
- Child Tasks wykonują się autonomicznie w granicach Parent,
- granica Parent jest Human Gate,
- retry mają jawny budżet i warunki eskalacji,
- bundle podlega kontroli jakości przed przekazaniem.

Problemy pozostające w v7:

- obowiązkowy Trap Task,
- brak maszynowego schematu Task Register,
- niejednoznaczny wybór logów „relevant”,
- konflikt między niskim priorytetem czatu a `Proceed` jako sygnałem sterującym,
- założenie jednakowych możliwości wszystkich Coding Agentów,
- tekstowa self-verification bez mechanicznego validatora.

## Najważniejsze rozróżnienie dla tego projektu

Historyczne FS-ASM opisuje głównie handoff:

```text
Planning Agent → pliki → Coding Agent
```

FS-ASM Training Lab ma użyć tych doświadczeń do zbudowania działającego
runtime:

```text
Human Goal
→ Orchestrator
→ Planner
→ Task State
→ Executor
→ Verifier
→ Evidence
→ Human Gate
```

Nie implementujemy v7 jako szablonu dla lokalnego Codexa. Budujemy system,
który mechanicznie realizuje wartościowe idee FS-ASM i pozwala testować ich
skuteczność.

## Decyzje projektowe wynikające ze źródeł

### 1. Cztery płaszczyzny

Training Lab będzie rozróżniać:

- **Control Plane:** polityki, architektura i kontrakty.
- **State Plane:** graf zadań, statusy, próby i blokery.
- **Execution Plane:** wywołania agentów, narzędzia i artefakty.
- **Evidence Plane:** wyniki walidacji, logi, metryki i fingerprinty.

Evidence nie może być jedynie opisem Executora. Musi być osobnym,
sprawdzalnym rezultatem.

### 2. Maszynowy Task Contract

Markdown może być widokiem dla człowieka. Stan wykonawczy powinien być
walidowany przez Pydantic i zapisywany jako JSON.

Docelowy kontrakt Child Task powinien przewidywać:

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

Pierwszy edukacyjny workflow może zacząć od mniejszego podzbioru, ale model
danych nie powinien uniemożliwiać późniejszego rozszerzenia.

### 3. Stabilne identyfikatory polityk

Nie używać samych numerów HC-05/HC-06, ponieważ ich znaczenia zmieniały się
między wersjami. Preferowane identyfikatory semantyczne:

- `POLICY_TEST_INTEGRITY`,
- `POLICY_DEPENDENCY_ALLOWLIST`,
- `POLICY_COMPLETE_CHANGE`,
- `POLICY_ATOMIC_SCOPE`,
- `POLICY_ARTIFACT_FINGERPRINT`,
- `POLICY_REGRESSION_SAFETY`.

### 4. Rozdzielenie komunikatów człowieka

Nie klasyfikować całego czatu jako jednego, najniższego źródła. Orchestrator
powinien rozróżniać:

- polecenie zmieniające zakres pracy,
- sygnał sterujący (`PROCEED`, `PAUSE`, `STOP`),
- odpowiedź wyjaśniającą,
- awaryjne zatrzymanie.

### 5. Bounded autonomy

- automatyczna kontynuacja tylko wewnątrz jawnej granicy,
- Human Gate na granicy Parent lub innego etapu semantycznego,
- retry tylko dla zadania oznaczonego jako retryable,
- limit prób i kryterium eskalacji zapisane w stanie,
- brak obniżania Verification po nieudanych próbach.

### 6. Mechaniczne walidatory zamiast rytuałów

Preferować:

- walidację schematów,
- kontrolę dozwolonych przejść stanu,
- sprawdzanie zależności,
- uruchamianie testów,
- kontrolę zakresu zmian,
- walidację wymaganych dowodów,
- fingerprinting artefaktów.

Handshake może pozostać krótkim potwierdzeniem identyfikatora zadania i
wersji stanu, ale nie jest dowodem zgodności.

### 7. Pamięć rozdzielona według funkcji

- **Normative memory:** polityki, architektura, kontrakty.
- **Execution state:** bieżące zadanie, status, próby, blokery.
- **Decision memory:** ADR.
- **Evidence memory:** testy, metryki, logi, fingerprinty.
- **Input provenance:** źródła, założenia i luki.

Nie tworzyć ręcznej `py_lib.md` jako obowiązkowej bazy symboli. Korzystać
z wyszukiwania kodu i indeksów generowanych narzędziowo.

## Klasyfikacja Training Lab

Na podstawie kategorii z Project Agent Bootstrap Protocol:

- **Primary:** Workflow/Orchestration System.
- **Secondary:** Integration/API System, ponieważ role komunikują się
  przez kontrakty danych i dostawcę modelu.
- **Późniejszy eksperyment:** Analytical System, gdy pojawi się scoring
  ekspertów, analiza skuteczności i routing oparty na historii.

Ta klasyfikacja wspiera wybór małego, jawnego state machine zamiast
przedwczesnego projektowania rozbudowanej architektury domenowej.

## Wpływ na pierwszy kamień milowy

Pierwszy workflow nadal pozostaje mały:

```text
Goal
→ Planner
→ walidowany plan trzech kroków
→ zapis JSON
→ Verifier
→ evidence record
```

Po audycie doprecyzowano, że powinien on pokazać:

- schematy wejścia, planu, weryfikacji i dowodu,
- jawne przejścia stanu,
- oddzielenie deklaracji wyniku od dowodu,
- ograniczoną politykę retry,
- log wykonania możliwy do odczytania przez człowieka,
- testy bez płatnego wywołania modelu.

## Otwarte kwestie

- Bez źródeł v6.0 nie można lokalnie zweryfikować wszystkich twierdzeń
  finalnego audytu dotyczących tej wersji.
- Nie ustalono jeszcze dokładnego schematu JSON/Pydantic pierwszego MVP.
- Nie ustalono jeszcze, czy pierwszy Planner użyje prawdziwego Mistral API,
  czy najpierw kontrolowanego stubu.
- Nie określono jeszcze, gdzie przebiega pierwsza granica wymagająca Human
  Gate w edukacyjnym workflow.
