# FS-ASM — rekonstrukcja genezy i obecnego kierunku

> **Wersja finalna po audycie v6.0, v4.0 Critical Addendum oraz dokumentu „Ciąg Logiczny Działania + błędylog”.**  
> Dokument rozdziela fakty źródłowe, wnioski audytowe i obecne rekomendacje rozwojowe.

## 1. Skąd powstał FS-ASM

FS-ASM nie powstał jako plan stworzenia rozbudowanego frameworka agentowego.

Powstał jako praktyczna odpowiedź na problemy podczas rozwijania projektu **PUR Silnik Fizyczno-Chemiczny** przy użyciu dostępnych wtedy narzędzi AI.

Głównym problemem był Coding Agent działający w VS Code, przede wszystkim GitHub Copilot, który miał ograniczony kontekst i podczas dłuższej pracy:

* zapominał wcześniejsze decyzje architektoniczne,
* nie pamiętał istniejących modułów i pipeline’ów,
* tworzył równoległe rozwiązania dla funkcji, które już istniały,
* dodawał niepotrzebne pliki,
* zmieniał kierunek implementacji w połowie pracy,
* powtarzał wcześniejsze, nieskuteczne próby,
* tracił informację o stanie projektu po zmianie sesji,
* wykonywał lokalnie sensowne zmiany, które globalnie naruszały architekturę.

FS-ASM był próbą nadania agentowi zewnętrznej, trwałej pamięci oraz jednoznacznego protokołu działania.

## 2. Pierwotna architektura systemu

Historyczny FS-ASM nie składał się wyłącznie z jednego Coding Agenta.

Był to workflow obejmujący co najmniej dwa różne środowiska agentowe oraz człowieka pełniącego funkcję orkiestratora.

### Planning Agent

Planning Agent działał w webowej wersji ChatGPT, najczęściej wewnątrz projektu zawierającego dokumentację użytkownika.

Otrzymywał:

* luźne notatki,
* dokumenty techniczne,
* przemyślenia dotyczące programu,
* wymagania funkcjonalne,
* ograniczenia,
* informacje domenowe,
* decyzje podejmowane podczas rozmowy.

Jego zadaniem było przekształcenie tych materiałów w uporządkowany pakiet wykonawczy dla środowiska VS Code.

Planning Agent generował między innymi:

* opis projektu,
* architekturę,
* standardy,
* instrukcje pracy dla Coding Agenta,
* listy zadań,
* kryteria weryfikacji,
* pliki pamięci,
* plik startowy wskazujący kolejność odczytywania dokumentacji.

Planning Agent działał więc jak warstwa analizy, formalizacji i kompilacji projektu.

### Ręczny handoff

Wygenerowane przez Planning Agenta pliki były ręcznie kopiowane do repozytorium otwartego w VS Code.

Człowiek pełnił funkcję:

* message busa pomiędzy agentami,
* orkiestratora,
* bramki zatwierdzającej,
* obserwatora jakości,
* źródła korekt i eskalacji.

Ręczne przekazywanie plików nie było przypadkowym ograniczeniem. Stanowiło część rzeczywistego workflow wynikającą z dostępnych wtedy narzędzi i braku płatnych API.

### Coding Agent

Coding Agent działał w VS Code i miał dostęp do:

* kodu źródłowego,
* terminala,
* testów,
* struktury repozytorium,
* plików wygenerowanych przez Planning Agenta.

Użytkownik wskazywał mu jeden plik startowy. Plik ten określał, jakie dokumenty agent ma przeczytać, w jakiej kolejności oraz jak ma odnaleźć aktualne zadanie.

Coding Agent miał:

* odtworzyć stan projektu,
* przeczytać architekturę i standardy,
* znaleźć pierwsze niewykonane zadanie,
* wykonać ograniczony zakres zmian,
* przeprowadzić testy,
* zapisać changelog,
* oznaczyć zadanie jako wykonane albo zablokowane,
* pozostawić stan umożliwiający kontynuację przez następną sesję.

## 3. Pełny historyczny przepływ

```text
Dokumenty, pomysły i wiedza użytkownika
                ↓
Planning Agent w ChatGPT
                ↓
Analiza i formalizacja projektu
                ↓
Bootstrap Pack dla repozytorium
                ↓
Ręczne zatwierdzenie i kopiowanie
                ↓
Coding Agent w VS Code
                ↓
Implementacja, testy i logi
                ↓
Aktualizacja trwałego stanu projektu
                ↓
Informacja zwrotna użytkownika
                ↺
Planning Agent
```

FS-ASM był więc plikowym protokołem komunikacji i utrzymywania stanu pomiędzy Planning Agentem, Coding Agentem i człowiekiem.

## 4. Rola repozytoriów PUR

Repozytorium **PUR-Silnik-fiz-chem** przedstawia wcześniejszy, roboczy etap projektu oraz ślady walki z ograniczeniami Coding Agenta.

Repozytorium **PUR-SILNIK-FIZ-CHEM-v.2** jest późniejszym snapshotem tego samego projektu rozwijanego lokalnie za pomocą tego workflow.

Nie są to dwa niezależne projekty.

Chronologia wygląda w przybliżeniu tak:

```text
pierwszy stan repozytorium
        ↓
rozwój lokalny z użyciem FS-ASM
        ↓
kolejne TODO, testy, changelogi i poprawki
        ↓
późniejszy snapshot zapisany jako v2
```

Repozytoria dokumentują głównie Execution Plane, czyli część obsługiwaną przez Coding Agenta.

Planning Agent działał poza repozytorium, w projektach i rozmowach ChatGPT. Z tego powodu jego historia jest słabiej widoczna i musi zostać odtworzona z zachowanych plików użytkownika.

## 5. Co FS-ASM robił w praktyce

System wprowadził między innymi:

* jeden plik startowy dla Coding Agenta,
* określoną kolejność ładowania dokumentów,
* architekturę jako źródło prawdy,
* standardy jako zbiór ograniczeń,
* listę TODO jako licznik programu,
* atomowe zadania,
* kryteria weryfikacji,
* ograniczanie zakresu modyfikowanych plików,
* obowiązkowe testy,
* statusy DONE i BLOCKED,
* changelogi dla wykonanych zadań,
* logowanie nieudanych prób,
* trwałą pamięć projektu niezależną od sesji czatu,
* możliwość kontynuowania pracy przez inny model lub nową sesję.

Pierwszy niezaznaczony punkt TODO pełnił funkcję wskaźnika aktualnej instrukcji.

Pliki instrukcji określały protokół wykonania.

Testy określały warunek zakończenia.

Changelogi i logi błędów tworzyły historię wykonania.

## 6. Jak powstawały kolejne zasady — korekta po audycie

Wiele elementów FS-ASM było reakcją na konkretne awarie Coding Agenta:

```text
Agent zapomniał istniejący pipeline
→ architektura jako źródło prawdy

Agent stworzył równoległy moduł
→ ograniczenie zakresu zmian, usage anchors i tooling first

Agent nie pamiętał bieżącego celu
→ task register i program counter

Agent powtarzał błędną próbę
→ failure log i Task-Specific Memory

Agent ogłaszał sukces bez dowodu
→ verification gate, testy, metryki i progi

Nowa sesja nie znała stanu projektu
→ bootstrap protocol i plikowy handoff

Agent improwizował przy brakujących danych
→ DATA-GAP, ASSUMPTION i Input Quality Report

Model lub dane traciły zgodność z pipeline’em
→ fingerprinting i manifesty

Projekt tracił spójność między dokumentacją a kodem
→ Planning Agent jako compiler, a następnie izolacja ról w v7
```

FS-ASM wyrastał więc z obserwowanych failure modes i rozwiązań wypracowanych w realnym repozytorium, a nie wyłącznie z teoretycznego projektowania.

## 7. Artefakty pomostowe z projektu PUR

Audyt dwóch dodatkowych dokumentów pozwala dokładniej odtworzyć przejście między praktyką PUR a formalną metodologią.

### v4.0 Critical Specification Addendum

Addendum jest normatywnym patchem, który jawnie przekształca dowody z Execution Plane PUR w reguły metodologii.

Formalizuje między innymi:

- model/data fingerprinting,
- Task-Specific Memory w `admin/`,
- semantyczne nazwy Task Registers,
- `.ai/ARCHITECTURE.md` jako źródło prawdy dla ORIENT,
- usage anchoring,
- tooling first,
- `Metric` i `Threshold` dla ML/OPT.

Dokument jest najważniejszym zachowanym mostem:

```text
praktyczne rozwiązanie lub awaria w PUR
        ↓
dyrektywa metodologiczna
        ↓
integracja w Unified Methodology v4
```

### Ciąg Logiczny Działania + błędylog

Ten dokument nie jest kolejną wersją ani rzeczywistym logiem błędów.

Jest interpretacyjną mapą v4, która układa system w pięć etapów:

1. Bootstrap,
2. Protocol Zero,
3. OODA,
4. kontrola zgodności,
5. audyt i pamięć.

Jego najważniejszy wniosek brzmi:

> File-system state nie usuwa halucynacji. Przenosi część ryzyka na interpretację reguł, pozorne deklarowanie zgodności oraz pomijanie aktualizacji pamięci i dowodów.

Dokument wprowadza zatem zalążek osobnego Assurance Model — analizy, gdzie tekstowe protokoły mogą zawieść i gdzie potrzebne są walidatory mechaniczne.

Nie da się na podstawie samych plików ustalić, który model wygenerował te artefakty ani dokładnej daty ich powstania.

## 8. Ewolucja wersji — stan skorygowany

### v2.1

Ustanowiła `todo.md` jako program wykonawczy:

- deterministyczny,
- atomowy,
- weryfikowalny,
- niezależny od historii czatu.

### v3.0

Dodała:

- pełny Control Plane,
- Bootstrap Mode,
- Protocol Zero,
- konfliktową hierarchię źródeł prawdy,
- Human Approval Gate.

### Bootstrap Protocol dla Project Agenta

Rozwinął Planning Agenta do roli compilera wykonującego:

```text
Domain Analysis
→ Architecture Design
→ Task Decomposition
→ Materialization
```

### v4 i Addendum

Dodały lub skodyfikowały:

- Hierarchical Lock,
- Trap Task,
- usage anchors,
- tooling first,
- Task-Specific Memory,
- Symbol Table,
- fingerprinting,
- metryki i progi ML/OPT,
- hardening istniejących repozytoriów.

Część tych mechanizmów pochodziła bezpośrednio z rozwiązań i problemów projektu PUR.

### v5.1 / v6.0

Pełny audyt pakietu v6 wykazał, że nie była ona całkiem nową architekturą.

v6 była przede wszystkim:

- modularną finalizacją linii v5.1,
- zgodną runtime z poprzednikiem,
- bez deklarowanych breaking changes.

Jej potwierdzone przyrosty to:

- modularizacja dokumentacji,
- silniejszy, domenowy Input Documentation Quality Gate,
- kanoniczny `docs/INPUT_QUALITY_REPORT.md`,
- dopracowane `[DATA-GAP]` i `[PHYSICS-CRITICAL]`,
- Controlled Dynamics dla zadań fizyczno-krytycznych,
- rozszerzona autoweryfikacja bootstrapu.

Fingerprinting, TSM, usage anchors, tooling first i ML/OPT thresholds nie powstały dopiero w v6 — ich wyraźne źródła są obecne już w Addendum i Unified v4.

### v7.0 / v7.1

Wprowadziły właściwy przełom architektoniczny:

- metodologia jest wyłącznie dla Planning Agenta,
- Coding Agent nie zna FS-ASM ani Planning Agenta,
- otrzymuje samowystarczalny, skompilowany bundle,
- działa autonomicznie wewnątrz Parent Task,
- zatrzymuje się na granicy Parent Task,
- bundle jest minimalizowany do plików rzeczywiście używanych w runtime.

## 9. Najważniejszy obecny wniosek

FS-ASM nie jest jedynie pamięcią dla Coding Agenta ani zestawem promptów.

Trafniejsze określenie:

> FS-ASM jest plikowym, audytowalnym protokołem kompilowania wiedzy, ograniczeń i planu pracy do wykonywalnego stanu projektu, przekazywanego pomiędzy Planning Agentem i Coding Agentem, z człowiekiem pełniącym funkcję orkiestratora, bramki zatwierdzającej i źródła eskalacji.

Pełny model obejmuje obecnie cztery warstwy:

```text
Compilation Model
- wiedza użytkownika → bundle projektu

Runtime Model
- task lock → wykonanie → verification → aktualizacja stanu

Memory Model
- polityki, decyzje, task state, evidence, provenance

Assurance Model
- failure modes, walidatory, gates, retry budget, escalation
```

## 10. Obecny cel projektu

Celem nie jest budowanie dużej platformy SaaS ani deklarowanie pełnej autonomii.

FS-ASM powinien służyć jako osobiste laboratorium do nauki i testowania:

- agentów AI,
- workflowów wieloagentowych,
- pamięci trwałej,
- handoffu,
- selekcji i kompilacji kontekstu,
- walidacji wyjść modeli,
- checkpointów i recovery,
- sterowania narzędziami,
- bounded autonomy,
- ewaluacji jakości pracy agentów.

Pierwotny ręczny workflow pozostaje ważnym baseline’em eksperymentalnym.

## 11. Następny etap po zakończeniu rekonstrukcji

Etap gromadzenia i podstawowej rekonstrukcji historycznej jest zasadniczo zakończony.

Nie należy teraz pisać kolejnej wielkiej specyfikacji metodologicznej.

Następne działania powinny być małe i mierzalne:

1. Ustalić kanoniczny `CURRENT_FSASM_MODEL.md`.
2. Zdefiniować minimalny schema bundle i Child Task.
3. Zbudować parser oraz validator artefaktów Planning Agenta.
4. Przygotować katalog failure modes i testy walidatora.
5. Przeprowadzić jeden kontrolowany eksperyment:
   - ten sam mały projekt,
   - ten sam Coding Agent,
   - wariant bez FS-ASM,
   - wariant z minimalnym FS-ASM,
   - porównanie błędów, liczby interwencji i jakości dowodów.

Priorytetem jest zweryfikowanie mechanizmów, nie dalsze zwiększanie objętości instrukcji.

## 12. Stan archiwum i materiały opcjonalne

Do głównej rekonstrukcji zabezpieczono:

- v2.1,
- v3.0,
- Bootstrap Protocol dla Project Agenta,
- v4 Unified,
- v4 Critical Addendum,
- `Ciąg Logiczny Działania + błędylog`,
- pełny pakiet v6,
- v7.0,
- v7.1,
- porównanie wersji,
- audyt v6,
- dokument genezy.

Dodatkowe materiały nadal mogą zwiększyć precyzję chronologii, zwłaszcza:

- pierwotne eksporty rozmów Planning Agenta,
- lokalna historia Git repozytoriów PUR,
- stare TODO i pliki przed kopiowaniem do VS Code,
- daty utworzenia oryginalnych plików,
- pełne logi konkretnych awarii Coding Agenta.

Nie są one jednak wymagane do rozpoczęcia następnego etapu.

## 13. Status końcowy

Na obecnym etapie wiadomo z wysoką pewnością, że:

- FS-ASM powstał z praktycznych problemów podczas pracy nad PUR,
- historyczny system obejmował Planning Agenta, Coding Agenta i człowieka,
- człowiek był message busem, approval gate’em i operatorem eskalacji,
- repozytoria PUR dokumentują przede wszystkim Execution Plane,
- Addendum dokumentuje przejście od dowodów w PUR do reguł metodologii,
- `Ciąg Logiczny` dokumentuje interpretacyjny model runtime i jego ryzyka,
- v6 była modularną konsolidacją starej linii, nie przełomem runtime,
- v7 dokonała najważniejszego rozdzielenia ról,
- dalsza praca powinna przejść od rekonstrukcji do małych eksperymentów i walidacji mechanicznej.

**Status rekonstrukcji historycznej: ZASADNICZO ZAMKNIĘTA.**

Nowo odnalezione artefakty mogą być dopisywane jako korekty, ale nie blokują już syntezy obecnego modelu ani rozpoczęcia eksperymentów.
