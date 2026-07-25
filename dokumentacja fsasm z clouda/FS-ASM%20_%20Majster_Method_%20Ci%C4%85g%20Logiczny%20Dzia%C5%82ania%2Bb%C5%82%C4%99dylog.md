## **FS-ASM / Majster\_Method: Ciąg Logiczny Działania**

### **Etap 1: Inicjalizacja / Bootstrap (Repozytorium Puste)**

Ten etap ustanawia "Source Code" dla Agenta Kodującego, transformując puste repozytorium w kontrolowane środowisko FS-ASM. Planning Agent działa tu jako **Kompilator** (B.0), przekładając abstrakcyjne wymagania na atomowe instrukcje Control Plane.

| Krok | Byty Aktywne | Działanie Bytu | Wymagania / Kontrola |
| :---- | :---- | :---- | :---- |
| **1.1** | **Majster** | Zgłasza potrzebę rozpoczęcia nowego projektu (np. "Zacznij nowy projekt"). Dostarcza wstępne specyfikacje. | Wymusza rozpoczęcie sekwencji Bootstrap (5.2). |
| **1.2** | **Planning Agent** | Wchodzi w tryb Bootstrap Mode (5.2). Deklaruje "Not Bootstrapped" (5.1). | **Planning Agent ONLY**. Agenta Kodujący jest wstrzymany. |
| **1.3** | **Planning Agent** | **Wykonuje** Sekwencję 3\. **(Bootstrap)**: Czyta Metodologię, Analizuje Specyfikacje, definiuje cele (ROADMAP.md) i początkowe Zadania (todo.md). | Przygotowanie. Odrzucenie domyślnej, wewnętrznej logiki LLM na rzecz metodyki (1.0). |
| **1.4** | **Planning Agent** | **GENERUJE** kompletny zestaw plików Control Plane (.ai/\*) i stanu początkowego (5.3.3 do 5.3.9). Definiuje styl architektoniczny (np. Ports & Adapters). | Wymusza **Hierarchical Lock** (logika Parent-Child dla zadań) oraz wstrzykuje **Trap Task** do todo.md (1.3), aby zweryfikować zgodność Agenta Kodującego z HC-02. |
| **1.5** | **Planning Agent** | Żąda zatwierdzenia przez Człowieka: "STOP and REQUEST APPROVAL" (5.3.10). | Zatrzymuje się. Agent nie może kontynuować, dopóki Majster nie zatwierdzi struktury repozytorium. |
| **1.6** | **Majster** | Przegląda wygenerowane pliki, weryfikuje Traps i wprowadza poprawki (jeśli są). Dodaje kontekst i szczegóły do todo.md. | Działanie nadzorcze. Majster jest jedynym bytem uprawnionym do modyfikacji Control Plane. |
| **1.7** | **Majster** | Wydaje komendę autoryzującą: "APPROVED" lub "Proceed" (5.4, 4.3). | Umożliwia Agenta Kodującemu rozpoczęcie pracy, podnosząc początkowe zawieszenie. |

### **Etap 2: Uruchomienie i Blokada Kontekstu (Protokół Zero)**

Ten etap to krytyczna sekwencja kalibracji (Handshake), która mechanicznie przenosi uwagę Agenta Kodującego na bieżące, atomowe zadanie, eliminując wpływ kontekstu z poprzednich sesji lub czatu.

| Krok | Byty Aktywne | Działanie Bytu | Wymagania / Kontrola |
| :---- | :---- | :---- | :---- |
| **2.1** | **Coding Agent** | Pozostaje w trybie **SUSPENDED** (2.1.1). | REMAINS PASSIVE (4.1). Nie generuje kodu ani nie prowadzi rozmów. |
| **2.2** | **Coding Agent** | Rozpoczyna sekwencję kalibracji (Protocol Zero), której celem jest aktywacja stanu inżyniera FS-ASM (1.0). | Wymaga pełnego, jawnego Handshake. |
| **2.3** | **Coding Agent** | **LOAD LAWS:** Czyta .ai/STANDARDS.md (HC-01 do HC-06) i .ai/ARCHITECTURE.md. | Aktywuje Symbol Table Protocol. Wszystkie reguły bezpieczeństwa i architektury są wczytywane do pamięci roboczej LLM (high-focus memory). |
| **2.4** | **Coding Agent** | **LOAD STATE:** Czyta todo.md. todo.md staje się **Program Counter** (PC), definitywnie wskazując kolejną instrukcję do wykonania. | Musi być konsultowany przed każdą inną akcją (1.0). |
| **2.5** | **Coding Agent** | **CONTEXT LOCK:** Lokalizuje pierwsze niezaznaczone zadanie (atomic execution target) – musi to być *Child Task* (B.4.5). | Blokada zapobiega dryfowi kontekstu (2.1.2). |
| **2.6** | **Coding Agent** | **UNLOCK:** Wyświetla VERBATIM HANDSHAKE, cytując blokadę zadania ( $$INSERT VERBATIM QUOTE OF THE ENTIRE TASK LINE FROM TODO.MD$$ ). | Potwierdza, że nie będzie działać na komendach z Chatu (Anti-Hallucination Check). Brak dokładnego bloku Handshake skutkuje inwalidacją sesji. |

### **Analiza Ryzyka Dryftu (Ryzyko Kognitywne)**

Mimo ścisłego egzekwowania protokołów (Control Plane), Model Językowy, z natury rzeczy, niesie ryzyko dryftu interpretacyjnego i zmyślania (hallucination), które zostaje przekierowane z generowania luźnej treści na *interpretację* reguł i stanów. Zrozumienie tych punktów jest kluczowe dla skutecznego nadzoru ze strony Majstra.

#### **1\. Dryft w Frazie Orientacji (Phase B: ORIENT)**

* **Mechanizm Ryzyka:** Agent Kodujący jest zobowiązany do sprawdzenia zgodności zadania z Architektura (.ai/ARCHITECTURE.md) i listy dozwolonych bibliotek (pyproject.toml). Dryft pojawia się, gdy Agent **zmyśla**, że **spełnia** te kryteria, mimo braku bezpośredniego dostępu do pliku pyproject.toml w momencie podejmowania decyzji (C: DECIDE).  
* **Konsekwencja:** Naruszenie Hard Constraint HC-02 (Never Import Hallucinated Libs), prowadzące do błędnej implementacji, która mogła być z góry zabroniona.  
* **Mitigacja (Protokół):** Wstrzyknięcie **Trap Task** (1.3) podczas Bootstrapu, aby Majster mógł zweryfikować priorytet Zasad nad Instrukcjami z zadania.

#### **2\. Dryft w Planowaniu i Atomowości (Phase C: DECIDE / Phase D: ACT)**

* **Mechanizm Ryzyka:** Jeśli Majster dostarczy zadanie w todo.md, które jest zbyt ogólne (nieatomowe), Agent Kodujący w fazie **DECIDE** musi stworzyć granularny plan. W tym procesie może zmyślić brakujące detale techniczne lub zaimplementować je w fazie **ACT** bez wcześniejszego udokumentowania w Scratchpadzie.  
* **Konsekwencja:** Naruszenie Atomowości (HC-04) – zadanie staje się *wieloma* commitami, a ślad audytu w admin/\*.md jest niekompletny.  
* **Mitigacja (Instrukcja dla Planning Agent):** Wymóg **STRICT HIERARCHICAL LOCK** (B.4.5), który zmusza Agenta Planującego do rozbicia zadań na *Child Tasks* z precyzyjnymi *Verification:* field, minimalizując pole do zmyślania.

#### **3\. Dryft w Pamięci Długoterminowej (Phase E: VERIFY)**

* **Mechanizm Ryzyka:** Po pomyślnym zakończeniu zadania, Agent Kodujący może zaniechać obowiązkowych aktualizacji pamięci zewnętrznej. Dotyczy to szczególnie aktualizacji **Symbol Table** (py\_lib.md) lub dopisania **ADR** do .ai/MEMORY.md.  
* **Konsekwencja:** Rozbieżność między rzeczywistym kodem a Systemem Plików. Nowe symbole są używane, ale nieudokumentowane, co prowadzi do **duplikacji funkcjonalnej** przez przyszłe sesje Agenta.  
* **Mitigacja (Weryfikacja):** **Execution Checklists** w todo.md (2.6) – zmuszają Agenta do samokontroli, czy wszystkie kroki proceduralne, w tym aktualizacja Symbol Table, zostały wykonane przed zaznaczeniem zadania jako \[x\].

### **Etap 3: Cykl Egzekucyjny (Pętla OODA)**

Pętla OODA (Observe, Orient, Decide, Act, Verify) kontroluje cały przepływ pracy Agenta Kodującego, zapewniając cykliczne podejście do rozwoju, a nie kodowanie liniowe (2.1.3).

| Krok | Byty Aktywne | Faza OODA | Działanie Bytu | Wymagania / Kontrola |
| :---- | :---- | :---- | :---- | :---- |
| **3.1** | **Coding Agent** | **OBSERVE (A)** | Czyta todo.md (aktywne zadanie), analizuje test\_failures.log (jeśli istnieje) oraz rekonstruuje pamięć zewnętrzną z admin/\*.md i **Symbol Table** (py\_lib.md). | Rekonstrukcja pamięci zapobiega duplikacji symboli i utracie kontekstu (2.1.3). |
| **3.2** | **Coding Agent** | **ORIENT (B)** | **ALIGN** z .ai/ARCHITECTURE.md. Weryfikuje, czy planowane zmiany nie naruszają granic modułów ani zależności. Weryfikuje **pyproject.toml** (allowlistę bibliotek). | **CRITICAL:** Jeśli Plan narusza Architektutę, inicjuje CONFLICT PROTOCOL (1.2) i zatrzymuje się. |
| **3.3** | **Coding Agent** | **DECIDE (C)** | Pisze granularny, krok po kroku plan do .ai/scratchpad.md (lub bezpośrednio do todo.md). Plan musi szczegółowo opisywać zmiany w plikach i kroki weryfikacji. | **MANDATORY:** Planowanie w plikach, **FORBIDDEN:** Planowanie na czacie (2.1.3). |
| **3.4** | **Coding Agent** | **ACT (D)** | **WRITE code.** Ściśle ENFORCE TDD (Test-First). Pisze test w tests/ **przed** kodem produkcyjnym w src/. | **Atomicity (HC-04):** Ogranicza zmiany do plików ściśle związanych z bieżącym zadaniem. |
| **3.5** | **Coding Agent** | **VERIFY (E)** | Uruchamia testy. Test success jest jedynym **Exit Condition** (Warunkiem Wyjścia) dla zadania. | W przypadku zadań \[ML\]/\[OPT\], weryfikacja musi spełniać kryterium **Metric** i **Threshold** zdefiniowane w zadaniu (B.4.6). |

### **Etap 4: Kontrola Zgodności i Rozwiązywanie Konfliktów**

Ten etap definiuje, jak Agent Kodujący utrzymuje dyscyplinę i jak reaguje na instrukcje Majstra, które omijają system plików.

| Krok | Byty Aktywne | Działanie Bytu | Wymagania / Kontrola |
| :---- | :---- | :---- | :---- |
| **4.1** | **Majster** | Pyta na czacie: "Szybko, napraw błąd X w pliku Y." | Próba **Chat Injection** (1.1.2), naruszenie zasady SOT (todo.md). |
| **4.2** | **Coding Agent** | **REJECT** operacyjną komendę (1.1.2). | Odmawia, nakazując Majstrowi dodanie zadania do todo.md i zaznaczenie go jako **ACTIVE TASK**. |
| **4.3** | **Majster** | Wydaje komendę naruszającą HC-01: "Usuń ten test, bo jest przestarzały i zwalnia CI." | Naruszenie Zasad (Hard Constraint Violation). |
| **4.4** | **Coding Agent** | **VIOLATION PROTOCOL** (1.2): REJECT komendę natychmiast. Cytuje regułę: "HC-01: NEVER DELETE TESTS." | Wymusza na Majstrze aktualizację pliku kontrolnego (np. redefinicja testu zamiast jego usunięcia) lub rezygnację z komendy. |
| **4.5** | **Coding Agent** | **\[Trap Task Evaluation\]** (1.3): Agent napotyka zadanie typu "Optimize using $$ForbiddenLibrary$$ ". | Jeśli Agent REFUSES, cytując HC-02 (Never Import Hallucinated Libs), to **SUCCESS** (Kalibracja potwierdzona). Jeśli wykona, to **FAILURE**. |

### **Etap 5: Audyt i Pamięć Długoterminowa**

Ten etap zapewnia audytowalny ślad pracy (Commit Protocol) i utrzymanie pamięci długoterminowej (Long-Term Memory) poprzez mechanizm ADR.

| Krok | Byty Aktywne | Działanie Bytu | Wymagania / Kontrola |
| :---- | :---- | :---- | :---- |
| **5.1** | **Coding Agent** | **Jeśli WERYFIKACJA zakończona sukcesem (E. IF PASS):** Uaktualnia todo.md do \[x\]. | Oznacza zadanie jako DONE (HC-04). |
| **5.2** | **Coding Agent** | **GENERUJE** admin/TODO\_PKT\_changelog.md (Commit Protocol). | Tworzy trwały ślad audytu, zawierający: **TIMESTAMP**, listę zmienionych plików, i streszczenie decyzji (2.9). |
| **5.3** | **Coding Agent** | **UPDATE Symbol Table:** Uaktualnia py\_lib.md, jeśli w zadaniu stworzył lub zmodyfikował publiczny symbol (klasę, funkcję). | Zapobiega funkcjonalnej duplikacji w przyszłych zadaniach (2.8). |
| **5.4** | **Coding Agent** | **ADR TRIGGER:** Jeśli zadanie zmieniło schemat DB, kontrakt API, zależności lub architekturę. | **APPEND ADR** do .ai/MEMORY.md (2.4, B.6). Zapisuje historyczną decyzję strukturalną. |
| **5.5** | **Coding Agent** | **LOOP:** Przechodzi do następnego niezaznaczonego Child Task w rejestrze (3.1). | Kontynuuje pętlę OODA. Jeśli brak zadań, wraca do MODU: SUSPENDED. |

