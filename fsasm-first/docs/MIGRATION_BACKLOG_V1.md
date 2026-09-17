# FS-ASM v1 — kolejka migracji do zatwierdzenia

> **DOKUMENT HISTORYCZNY.** Ten plik jest wczesną propozycją kolejności migracji, **zastąpioną przez kanoniczny program wykonawczy** [`FSASM_RUNTIME_V1_CANONICAL_TODO.md`](FSASM_RUNTIME_V1_CANONICAL_TODO.md) (ustanowiony 17.09.2026). Kanoniczne TODO jest jedynym aktywnym programem kolejności; tabela Q0–Q11 oraz etap laptop poniżej pozostają wyłącznie jako odniesienie historyczne i **nie upoważniają** do rozpoczęcia żadnego taska. Źródłowy audyt pozostaje ważnym dowodem historycznym: [audyt Astry](reviews/FSASM_V1_ARCHITECTURE_GAP_ANALYSIS_AND_MIGRATION_PLAN_2026-09-17.md), badany na `142db38`.

**Status: PROPOZYCJA, nie polecenie implementacji. Aktualizacja 17.09.2026 po merge PR #20.** Jedyna architektura: [pełny dokument v1](FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md). Źródło szczegółowych reprodukcji i pierwotnych Q1–Q12: [audyt Astry](reviews/FSASM_V1_ARCHITECTURE_GAP_ANALYSIS_AND_MIGRATION_PLAN_2026-09-17.md), badany na `142db38`. Ten plan koryguje jedynie datowane fakty i kolejność startową; nie jest audytem każdego późniejszego SHA.

| Etap | Cel | Granica odbioru |
|---|---|---|
| **Q0 — dokumentacja** | Przenieść pełną v1 do repo bez zmian; przepisać wszystkie aktywne README/AGENTS/mapy/status/skill, zapisać decyzje o hybrydzie i jawnych danych | SHA-256 kanonu `56aeeb60...`, brak sprzecznych instrukcji i brak zmian runtime; sprawdzona lista plików |
| **Q1 — korekta po merge PR #20** | Na aktualnym HEAD odtworzyć i naprawić G3/G4/G5; odrębna zgoda na wycofanie legacy decyzji bez ID | Stara decyzja nie otwiera następnej bramki; `None` w audycie pozostaje `None`; sygnał przy `await` jest zapisany; chronione F3/F4/F5/F8 bez regresji |
| **Q2 — snapshot/domain** | Parent/Child, Task Register, `revision`, referencje evidence, zdarzenia i jeden punkt przejścia | nieaktualny zapis nie nadpisuje nowszego, spójny stan, nielegalne przejścia odrzucone |
| **Q3 — persistence/activities** | One commit per run snapshot, projekcje, expected revision, start_new/resume foundation | F3/F4/F5 zachowane; fault injection nie daje false PASS ani dodatkowej próby |
| **Q4 — pełny plan** | Task Compiler, scheduler DAG i agregacja Parent/run na stubie | 1, 3 i N zadań z zależnościami, jeden aktywny task, sukces dopiero po całym wymaganym planie |
| **Q5 — narzędzia i dowody** | Tool Broker izoluje realne operacje; Verifier sprawdza rzeczywisty efekt | niedozwolone zapisy blokowane; realny patch/check; stare/syntetyczne evidence nie dają PASS |
| **Q6 — context i gateway** | Mały TaskContext, neutralne typy odpowiedzi, scripted backend, limity | brak uzależnienia domeny od konkretnego API, powtarzalne tool calls/usage/errors |
| **Q7 — pętla Executora** | model→Broker→observation→model, dwa poziomy retry | co najmniej dwie iteracje ze skutkiem narzędziowym, limity i terminal reasons |
| **Q8 — adaptery** | Interfejs jednego lokalnego protokołu i Mistral A/B na fixture'ach, bez laptopa i live modeli | kontraktowe testy backendów i konfiguracji bez realnego 7B w CI |
| **Q9 — routing** | lokalny default, consultation vs handover, limity eskalacji | router egzekwuje budżet i nie przyznaje modelom dodatkowych uprawnień |
| **Q10 — gate/resume** | Trwała semantyka decyzji w snapshot, bezpieczna kontynuacja niepewnych skutków | bez ponownej autoryzacji przez duplikat; start_new nie nadpisuje runu; resume nie powtarza skutku na ślepo |
| **Q11 — integracja i pakiet** | Jeden runtime zamiast czterech aktywnych demonstratorów; instalacja/CLI/worker | full stub end-to-end: plan→tool→Verifier→retry/gate→resume→terminal; dokumentacja profilu hybrydowego |
| **Etap laptop** | Po ukończeniu Q11 przenieść projekt, uruchomić lokalny ~7B Q4, potem Mistral A/B | osobne testy rzeczywistych modeli, nie kryterium odbioru wcześniejszego CI |

Numeracja Q2–Q11 w tym dokumencie jest przesunięciem względem Q3–Q12 Astry po włączeniu dawnego Q2 do Q0. Nie oznacza zmiany treści audytu. Najpierw review aktualnego kodu oraz osobne zatwierdzenie Q1; dopiero potem precyzyjne taski dla Vibe.

**Żadnego automatycznego merge, zamknięcia M4, startu M5, reinstalowania LLMC, „szyfrowania dla prywatności”, nowego frameworka ani ogromnej nowej matrycy mikrotestów.** Testować istotne inwarianty i realne skutki, nie liczbę testów.
