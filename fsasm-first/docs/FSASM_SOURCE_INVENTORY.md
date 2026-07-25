# Inventory materiałów źródłowych FS-ASM

Data audytu: 2026-07-25

## Lokalizacja źródeł

Oryginalne pliki znajdują się poza katalogiem kodu, w:

`C:\fsasm-training-lab\dokumentacja fsasm z clouda`

Nie zostały zmodyfikowane ani przeniesione podczas audytu.

## Zasady klasyfikacji

- **Źródło historyczne** — specyfikacja lub dodatek reprezentujący etap
  rozwoju metodologii.
- **Główne źródło analityczne** — najbardziej kompletna dostępna analiza
  porównawcza, ale nie automatycznie norma wykonawcza.
- **Materiał interpretacyjny** — opis lub analiza mechanizmu, a nie jego
  kanoniczna specyfikacja.
- **Duplikat dokładny** — identyczna zawartość SHA-256.
- **Wariant formatu** — ta sama treść merytoryczna zapisana inaczej.
- **Zastąpiony** — wcześniejsza analiza, której rozszerzona wersja jest
  dostępna.
- **Niekompletny** — plik fizycznie kończy się w środku treści.

## Zalecana hierarchia użycia

1. `FS-ASM_ANALIZA_POROWNAWCZA_FINALNA_PO_AUDYCIE_WSZYSTKICH_ARTEFAKTOW.md`
   jako główna mapa historii, sprzeczności i rekomendacji.
2. Oryginalne specyfikacje v2.1, v3.0, v4.0, v7.0 i v7.1 do sprawdzania
   konkretnych twierdzeń.
3. Critical Addendum i „Ciąg Logiczny” jako źródła pochodzenia mechanizmów
   v4 i katalogu failure modes.
4. Project Agent Bootstrap Protocol wyłącznie pomocniczo, ponieważ plik jest
   ucięty.
5. Duplikaty i wcześniejszą analizę pomijać podczas zwykłego odczytu.

Żadna historyczna wersja FS-ASM nie jest bieżącą specyfikacją wykonawczą
laboratorium. Aktualne decyzje projektu znajdują się w
`ORIGIN_AND_CURRENT_UNDERSTANDING.md`.

## Lista plików

| Plik | Rozmiar | SHA-256 (skrót) | Klasyfikacja | Rola i uwagi |
|---|---:|---|---|---|
| `FS-ASM v2.1 TECHNICAL SPECIFICATION_ TASK REGISTER DESIGN ARCHITECTURE.md` | 11 721 B | `097E8E2263A4` | Źródło historyczne; preferowany wariant | Najczystsza specyfikacja „TODO as Code”: atomowość, verifiability, task ISA i sekwencja FETCH–PLAN–EXECUTE–VERIFY–COMMIT. |
| `FS-ASM v2.1 TECHNICAL SPECIFICATION_ TASK REGISTER DESIGN ARCHITECTURE (1).txt` | 11 360 B | `4C2C8A28D244` | Wariant formatu | Merytorycznie odpowiada wersji Markdown; różnice dotyczą głównie formatowania i drobnej redakcji struktury. |
| `FS-ASM _ Majster_Method – Unified Methodology Specification v3.0.md` | 31 209 B | `B7631FA1ED25` | Źródło historyczne | Pierwszy pełny Control Plane, Bootstrap Mode, Protocol Zero, OODA, ADR i wspólna specyfikacja dla Planning oraz Coding Agenta. Zawiera również włączoną specyfikację v2.1. |
| `FS-ASM _ Majster_Method – Unified Methodology Specification v3.0 (1).md` | 31 209 B | `B7631FA1ED25` | Duplikat dokładny | Identyczna kopia pliku v3.0 bez sufiksu. |
| `FS-ASM _ Majster_Method – Unified Methodology Specification v4.0 (2).md` | 32 004 B | `EA8DC41F9F80` | Źródło historyczne | Hardening v4: Parent–Child, usage anchors, tooling-first, Task-Specific Memory, ręczna Symbol Table, Trap Task i specjalne reguły ML/OPT. Ma niespójne oznaczenia wersji wewnątrz pliku (`v4.0`, canonical `v3.1`, Task Spec `v3.1`). |
| `FS-ASM%20v4.0%20CRITICAL%20SPECIFICATION%20ADDENDUM.md` | 5 029 B | `60EFC1F827DA` | Historyczny patch normatywny | Łączy doświadczenia projektu PUR z fingerprintingiem, TSM, semantic task naming, usage anchors, tooling-first i twardą walidacją ML/OPT. |
| `FS-ASM%20_%20Majster_Method_%20Ci%C4%85g%20Logiczny%20Dzia%C5%82ania%2Bb%C5%82%C4%99dylog.md` | 10 967 B | `DF4248BFE9C2` | Materiał interpretacyjny | Mapa pięcioetapowego runtime v4 i analiza trzech failure modes. Mimo nazwy nie jest rzeczywistym, datowanym logiem błędów. |
| `PROJECT AGENT - Bootstrap Protocol dla Nowych Projektów FS-ASM (3).md` | 28 424 B | `42F4E5FE2EA5` | Źródło historyczne, niekompletne | Wprowadza Context Programming Language i proces Domain Analysis → Architecture Design → Task Decomposition → Materialization. Plik kończy się w połowie docstringa przykładowej funkcji, więc nie wolno traktować go jako kompletnego protokołu. |
| `FS-ASM_v7_Planning_Agent_Only.md` | 17 857 B | `240F51BDB636` | Źródło historyczne | v7.0: przełom w izolacji ról. Tylko Planning Agent czyta metodologię; Coding Agent dostaje samowystarczalny bundle. Wprowadza autonomię Child Tasks wewnątrz Parent i stop na granicy Parent. |
| `FS-ASM_v7_Planning_Agent_Only_Full_Detailed.md` | 22 264 B | `5798033D399C` | Źródło historyczne; najpełniejsza specyfikacja starej linii | v7.1 rozwija Quality Gate, Controlled Dynamics, typed tasks, logi i self-verification. Nadal zawiera mechanizmy nieprzyjmowane literalnie, m.in. obowiązkowy Trap Task i archiwizowanie logiki. |
| `FS-ASM_ANALIZA_POROWNAWCZA_FINALNA_PO_AUDYCIE_WSZYSTKICH_ARTEFAKTOW.md` | 50 003 B | `E465F9035C79` | Główne źródło analityczne | Najpełniejszy dostępny audyt wersji, artefaktów pomostowych, sprzeczności i rekomendacji dla następnej architektury. |
| `FS-ASM_ANALIZA_POROWNAWCZA_FINALNA_PO_AUDYCIE_WSZYSTKICH_ARTEFAKTOW (1).md` | 50 003 B | `E465F9035C79` | Duplikat dokładny | Identyczna kopia finalnego audytu. |
| `FS-ASM-—-analiza-porównawcza-wersji-i-ewolucji-metodologii(1).txt` | 45 662 B | `92FAD988C39F` | Zastąpiona analiza | Wcześniejsza wersja audytu. Finalny audyt ma 124 dodatkowe linie; tylko trzy linie starej wersji nie występują w finale i nie zmieniają wniosków. |
| `FS-ASM-—-analiza-porównawcza-wersji-i-ewolucji-metodologii(1) (1).txt` | 45 662 B | `92FAD988C39F` | Duplikat dokładny | Identyczna kopia wcześniejszej analizy. |

## Wykryte ograniczenia zbioru

- Nie ma bezpośrednich plików źródłowych v5.1 ani rozpakowanego pakietu
  v6.0. Informacje o tych wersjach pochodzą z finalnego audytu.
- Nie ma wszystkich najwcześniejszych artefaktów z projektu PUR.
- Project Agent Bootstrap Protocol jest ucięty.
- Nazwy z `%20` i kodowaniem URL pochodzą z eksportu chmurowego i nie
  odzwierciedlają nazw kanonicznych deklarowanych wewnątrz dokumentów.
- Wersje historyczne zawierają wzajemnie sprzeczne oznaczenia HC-05/HC-06
  oraz niejednoznaczne entrypointy.

## Decyzja dotycząca duplikatów

Duplikaty pozostawiono bez zmian jako materiał użytkownika. Nie są potrzebne
do bieżącego kontekstu i nie powinny być wielokrotnie ładowane do modelu.
