# FS-ASM — repository handoff / jeden bieżący punkt statusowy

**Aktualizacja dokumentacji:** 17.09.2026. **Zweryfikowany punkt odniesienia:** `Fsasm-experimental` @ `3f1c12f04538ecf77fc729f86919eb0a83d21214` (merge PR #21). To datowany snapshot, nie gwarancja aktualnego HEAD. Każda kolejna sesja weryfikuje żywy HEAD, PR i CI przed rozpoczęciem zadania.

## Cel i uprawnienia

[Zatwierdzona architektura v1](../../../../fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md) jest jedynym kontraktem celu (SHA-256 `56aeeb60c8c700c71dc3d395659127afbf511e1726e0ffd76270c848fd764808`). [Decyzje wdrożeniowe](../../../../fsasm-first/docs/DEPLOYMENT_DECISIONS.md) doprecyzowują profil hybrydowy Workflows i zgodę na jawne dane/telemetrię. `Fsasm-experimental` jest linią integracyjną; `main` pozostaje osobno. Użytkownik + ChatGPT planują/review, Vibe Code Web pisze kod. Nie zmieniaj kanonu, kodu lub milestone'ów na podstawie samego handoffu.

## Potwierdzone na wskazanym punkcie odniesienia

- [PR #20](https://github.com/bmateuszideas/fsasm-training-lab/pull/20) został scalony 17.09.2026; merge SHA `f600ed210501030398740ce87006364dd78a034f`. Następnie przygotowano dokumentację v1 w `6bf60db`.
- [PR #21](https://github.com/bmateuszideas/fsasm-training-lab/pull/21) został scalony do `Fsasm-experimental` 17.09.2026; merge SHA `3f1c12f04538ecf77fc729f86919eb0a83d21214`. Konsolidacja dokumentacji i pojedynczy handoff repozytorium są już w linii integracyjnej, a nie zadaniem oczekującym na PR/merge. CI dla head PR #21 (`31d121f3b3e30cca99c3fb876137a5f8a8313730`) zakończyło się sukcesem; nie jest to wynik testów ponownie wykonanych na merge SHA.
- M1–M3 historycznie CLOSED. M4 jest demonstratorem z retry i Human Gate, ale **OPEN**; scalenie PR #20 ani PR #21 go nie zamyka. M5 **NOT STARTED**. LLMC/fine-tuning odłożone.
- M4 wykonuje tylko `TASK-001` przez deterministyczny stub. Nie ma kompletnego schedulera, Tool Brokera, niezależnego Verifiera artefaktów, realnej pętli model–narzędzie–obserwacja, Gatewaya ani pełnego operacyjnego resume.
- Audyt Astry przebadał kandydata `142db38`, wskazując G3–G5 (tożsamość bramki i audyt sygnałów) oraz szersze luki G1/G2 (revision i niezależne evidence). [Pełny datowany raport](../../../../fsasm-first/docs/reviews/FSASM_V1_ARCHITECTURE_GAP_ANALYSIS_AND_MIGRATION_PLAN_2026-09-17.md). Wyniki 625 passed / 3 skipped odnoszą się do tego kandydata, nie do dowolnego przyszłego HEAD. Status G3–G5 na HEAD po merge PR #20 nie został jeszcze niezależnie potwierdzony.

## Jedyny bieżący krok i status decyzji

**Następny krok: niezależna weryfikacja G3–G5 na aktualnym `Fsasm-experimental`.** Najpierw sprawdź nowy HEAD i CI, odtwórz trzy przypadki Human Gate opisane w audycie Astry na rzeczywistym aktualnym kodzie i testach oraz zapisz dla każdego wynik, reprodukcję i SHA. Nie zakładaj ani naprawienia G3–G5 przez PR #20, ani ich dalszego występowania bez reprodukcji. To krok weryfikacyjny, nie automatyczne zlecenie zmian kodu ani zgoda na zamknięcie M4.

**Nierozstrzygnięta decyzja użytkownika:** czy nadal dopuszczać sygnały legacy Human Gate bez jawnego `gate_id`. Przed taskiem kodowym zmieniającym tę semantykę uzyskaj osobną decyzję użytkownika, korzystając z ustaleń reprodukcji. Nie rozpoczynaj M5 ani innych pozycji backlogu bez odrębnej zgody.

[Backlog migracji](../../../../fsasm-first/docs/MIGRATION_BACKLOG_V1.md) jest propozycją, nie automatycznym upoważnieniem do realizacji Q1–Q11. G3–G5 to reprodukcje komponentowe, nie dowód produkcyjnego przejęcia ani automatycznie zamknięte defekty.

## Jak aktualizować

Ten plik zawiera tylko aktualny stan, zatwierdzony następny krok, ważne ograniczenia i odnośniki. Przy kolejnym rzeczywistym zdarzeniu (merge, zaakceptowany task, wynik CI, decyzja o milestone) zmień datę, referencyjny SHA i odpowiednie fakty **w tym jednym pliku** w zatwierdzonym PR. Nie twórz równoległego `PROJECT_STATUS.md`, `CURRENT_DEVELOPMENT_ANCHOR.md`, dodatkowego globalnego `HANDOFF.md` ani opisów stanu w README. Sesyjny handoff pojedynczego zadania zapisuj w jego PR/branchu zgodnie z `session-handoff.md`. Fakty implementacji zawsze weryfikuj na Git i testach.
