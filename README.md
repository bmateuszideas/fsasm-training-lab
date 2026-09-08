# FS-ASM Training Lab

**FS-ASM (File System as State Machine)** to projekt badawczo-edukacyjny rozwijający koncepcję trwałego, zewnętrznego stanu dla agentów AI oraz deterministycznego runtime'u kontrolującego ich pracę.

Projekt wyrósł z praktycznego workflow, w którym **ChatGPT pełnił rolę Plannera/Architekta, Codex w VS Code rolę Coding Executora, filesystem przechowywał stan i kontrakt wykonawczy, a człowiek ręcznie wykonywał orkiestrację i handoff**.

Obecny kierunek nie polega na odtwarzaniu starego FS-ASM 1:1. Celem jest przeniesienie jego najważniejszych zasad do współczesnej architektury agentowej, w której twarda logika jest egzekwowana przez kod, a modele LLM są wymiennymi komponentami poznawczymi.

## Główna idea

Najważniejsza zasada współczesnego FS-ASM:

> **Stan, kontrola i weryfikacja należą do systemu. LLM wykonuje ograniczone zadania wewnątrz reguł egzekwowanych przez runtime.**

W praktyce oznacza to między innymi:

- stan projektu poza kontekstem modelu,
- atomowe `ChildTask` zamiast dużych, nieprecyzyjnych poleceń,
- deterministyczne przejścia statusów,
- bounded retry,
- `Verification` i `Evidence` oddzielone od deklaracji modelu,
- role takie jak `Planner`, `Executor` i `Verifier`,
- `Human Gate` dla decyzji przekraczających zakres autonomii,
- budowanie minimalnego kontekstu dla aktualnego taska,
- możliwość używania różnych modeli zależnie od kosztu i kompetencji,
- docelowo możliwość wykorzystania lokalnego, wyspecjalizowanego Coding Workera.

## Docelowy model

```text
Human Goal
    ↓
FS-ASM Runtime / Orchestrator
    ↓
Planner
    ↓
Plan / Parent Tasks / Child Tasks
    ↓
Schema Validation
    ↓
Task Register + Persistent State
    ↓
Context Builder / Retrieval
    ↓
Executor
    ↓
Tools
    ↓
Result
    ↓
Verification + Evidence
    ↓
PASS / RETRY / ESCALATE / NEEDS_HUMAN
    ↓
Persistent State / Audit Log
```

FS-ASM ma być możliwie **model-agnostic** i **framework-agnostic**. Mistral API i Mistral Workflows są obecnie naturalnym środowiskiem pierwszych eksperymentów, ale nie są docelowym ograniczeniem architektury.

## Repozytorium

```text
fsasm-training-lab/
├── README.md
├── fsasm-first/
├── dokumentacja fsasm z clouda/
└── stare dokumenty rozwojowe fsasm/
```

### `fsasm-first/`

Pierwszy poligon doświadczalny współczesnej implementacji FS-ASM.

Zawiera środowisko oparte na Mistral Workflows, kod eksperymentalny, przykłady workflow oraz dokumenty używane podczas pierwszych prób implementacyjnych.

To **nie jest całe FS-ASM** i nie należy traktować jego aktualnej struktury jako ostatecznej architektury projektu.

### `stare dokumenty rozwojowe fsasm/`

Historyczne wersje metodologii, specyfikacje, addenda, analizy porównawcze i materiały pokazujące ewolucję koncepcji FS-ASM.

Są ważnym materiałem badawczym i źródłem historii projektu, ale **nie są aktualnymi instrukcjami implementacyjnymi**.

### `dokumentacja fsasm z clouda/`

Materiały przeniesione z wcześniejszego środowiska chmurowego. Część zawartości pokrywa się ze zbiorem dokumentów historycznych.

Ten katalog również należy traktować jako **źródło historyczne / archiwalne**, a nie source of truth dla bieżącej implementacji.

## Aktualny status

Projekt znajduje się na granicy pomiędzy:

```text
rekonstrukcją i audytem historycznego FS-ASM
                     ↓
pierwszą właściwą implementacją deterministycznego runtime'u
```

Najbliższy etap nie polega na budowaniu rozbudowanego systemu multi-agentowego.

Najpierw ma powstać mały, testowalny rdzeń bez LLM:

- `GoalInput`,
- `Plan`,
- `ChildTask`,
- `VerificationResult`,
- `EvidenceRecord`,
- `RunState`,
- walidacja schematów,
- dozwolone state transitions,
- persistent JSON state,
- bounded retry,
- unit tests.

Pierwszy milestone:

```text
Goal
↓
Planner Stub
↓
3 ChildTasks
↓
Schema Validation
↓
RunState JSON
↓
Verification
↓
EvidenceRecord
↓
PASS / FAIL
```

Dopiero po działaniu tej ścieżki będą kolejno dokładane:

1. prawdziwy Planner przez Mistral API,
2. Executor,
3. Verifier i retry loop,
4. Human Gate,
5. Context Builder i retrieval,
6. lokalny wyspecjalizowany Coding Worker,
7. routing modeli i eskalacja,
8. eksperymenty porównawcze,
9. ewentualny fine-tuning własnego FS-ASM Workera,
10. późniejsze opakowanie systemu jako plugin / integracja z ChatGPT.

## Zasady projektowe

1. **Stan należy do systemu, nie do LLM-a.**
2. **LLM może być stateless workerem.**
3. **Task powinien być możliwie atomowy.**
4. **Kod egzekwuje wszystko, co może zostać rozstrzygnięte deterministycznie.**
5. **Deklaracja modelu nie jest dowodem wykonania.**
6. **PASS wymaga Verification i Evidence.**
7. **Retry musi być ograniczone.**
8. **Model dostaje kontekst potrzebny do aktualnego taska, a nie cały projekt.**
9. **Planner i Executor mają różne odpowiedzialności i rozdzielone konteksty.**
10. **System może korzystać z wielu modeli i dobierać najtańszy wystarczająco kompetentny model do danego kroku.**
11. **Mocniejszy model może być eskalacją zamiast domyślnym wykonawcą każdego zadania.**
12. **Człowiek pozostaje Human Gate tam, gdzie kończy się bezpieczna autonomia systemu.**

## Dokumentacja historyczna a aktualna architektura

Historyczne dokumenty są zachowywane po to, aby:

- odtworzyć genezę koncepcji,
- porównywać kolejne rozwiązania,
- identyfikować mechanizmy, które przetrwały ewolucję projektu,
- prowadzić audyt decyzji projektowych.

Nie należy jednak implementować starej wersji tylko dlatego, że znajduje się w repozytorium.

Przy konflikcie pomiędzy dokumentacją historyczną a aktualnym kierunkiem projektu pierwszeństwo ma **bieżący model projektu i aktualny kod eksperymentalny**.

## Dalsze porządkowanie repozytorium

Docelowo warto rozdzielić repo na czytelne warstwy:

```text
fsasm-training-lab/
├── README.md
├── CURRENT_FSASM_MODEL.md        # aktualny source of truth
├── docs/
│   ├── history/                  # zachowane wersje historyczne
│   ├── audits/                   # analizy i rekonstrukcje
│   └── research/                 # materiały pomocnicze
├── experiments/
│   └── fsasm-first/              # pierwszy poligon implementacyjny
└── ...                           # przyszły aktywny runtime
```

Porządkowanie dokumentacji nie powinno oznaczać kasowania historii. Warto ją zachować, ale wyraźnie oddzielić od dokumentów sterujących aktualnym rozwojem.

---

**FS-ASM Training Lab** jest miejscem, w którym historyczna idea filesystemu jako zewnętrznej maszyny stanu jest przekształcana w rzeczywisty, testowalny runtime dla współczesnych agentów AI.
