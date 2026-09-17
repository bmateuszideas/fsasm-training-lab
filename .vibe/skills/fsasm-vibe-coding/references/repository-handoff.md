# FS-ASM — repository handoff / jeden bieżący punkt statusowy

**Aktualizacja dokumentacji:** 17.09.2026. **Zweryfikowany punkt odniesienia:** `Fsasm-experimental` @ `a7788a18ba0d5df19ace567b627c55a4f23d3ebc` (merge PR #26, T03 Human Gate identity; Gate AB osiągnięta). To datowany snapshot, nie gwarancja aktualnego HEAD. Każda kolejna sesja weryfikuje żywy HEAD, PR i CI przed rozpoczęciem zadania.

## Cel i uprawnienia

[Zatwierdzona architektura v1](../../../../fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md) jest jedynym kontraktem celu (SHA-256 `56aeeb60c8c700c71dc3d395659127afbf511e1726e0ffd76270c848fd764808`). [Decyzje wdrożeniowe](../../../../fsasm-first/docs/DEPLOYMENT_DECISIONS.md) doprecyzowują profil hybrydowy Workflows i zgodę na jawne dane/telemetrię. `Fsasm-experimental` jest linią integracyjną; `main` pozostaje osobno. Użytkownik + ChatGPT planują/review, Vibe Code Web pisze kod. Nie zmieniaj kanonu, kodu lub milestone'ów na podstawie samego handoffu.

## Potwierdzone na wskazanym punkcie odniesienia

- [PR #23](https://github.com/bmateuszideas/fsasm-training-lab/pull/23) (T00) scalony do `Fsasm-experimental` 17.09.2026; merge SHA `fae7bcf`. Kanoniczny TODO i pojedynczy handoff są w linii integracyjnej.
- [PR #24](https://github.com/bmateuszideas/fsasm-training-lab/pull/24) (T01) scalony 17.09.2026; merge SHA `de302b5`. T01 niezależnie odtworzyło G3, G4 i G5 na HEAD `a470cdd` — wszystkie `PRESENT` (G3: legacy consent reassignable across gates; G4/G5: rejection attribution/drain). Raport reprodukcji przypięty do SHA; bez zmian kodu produkcyjnego.
- [PR #25](https://github.com/bmateuszideas/fsasm-training-lab/pull/25) (T02) scalony 17.09.2026; merge SHA `31d6724`. T02 naprawiło G4/G5 (atrybucja i drain odrzuceń Human Gate) bez regresji RETRY_ONCE/ABORT; późne rejection nie ginie, `None` pozostaje `None`.
- [PR #26](https://github.com/bmateuszideas/fsasm-training-lab/pull/26) (T03) scalony 17.09.2026; merge SHA `a7788a1`. T03 naprawiło G3 (tożsamość zgody Human Gate): runtime wymaga pełnych `run_id`/`task_id`/`gate_id`/`decision_id` na granicy, odrzuca niepełny/obcy/stary/przyszły payload jako `incomplete_payload` przed rezerwacją bramki, zachowuje first-valid-wins i stabilny `decision_id`. **Gate AB osiągnięta:** T00–T03 ACCEPTED, brak warunkowych NOT REQUIRED; pełny pytest zielony na `a7788a1`.
- M1–M3 historycznie CLOSED. M4 jest demonstratorem z retry i Human Gate, ale **OPEN**; T00–T03 go nie zamykają. M5 **NOT STARTED**. LLMC/fine-tuning odłożone.
- M4 wykonuje tylko `TASK-001` przez deterministyczny stub. Nie ma kompletnego schedulera, Tool Brokera, niezależnego Verifiera artefaktów, realnej pętli model–narzędzie–obserwacja, Gatewaya ani pełnego operacyjnego resume.
- Audyt Astry wskazał G3–G5 oraz szersze luki G1/G2 (revision i niezależne evidence). [Pełny datowany raport](../../../../fsasm-first/docs/reviews/FSASM_V1_ARCHITECTURE_GAP_ANALYSIS_AND_MIGRATION_PLAN_2026-09-17.md). T01 potwierdziło G3–G5 PRESENT; T02 naprawiło G4/G5.

## Jedyny bieżący krok i status decyzji

**Kanon kolejności:** [Kanoniczny program wykonawczy](../../../../fsasm-first/docs/FSASM_RUNTIME_V1_CANONICAL_TODO.md) (T00–T34 + bramki) jest jedynym aktywnym programem kolejności prac. Wczesna [kolejka migracji](../../../../fsasm-first/docs/MIGRATION_BACKLOG_V1.md) jest dokumentem historycznym zastąpionym przez kanoniczne TODO.

**Następny krok: T04 — Kompletny model domenowy snapshotu** (Faza C: Właścicielstwo stanu). Zależność Gate AB spełniona. **Decyzja użytkownika:** „Extend in place” — nowe pola dodane do istniejących `RunState`/`Plan`/`ChildTask` w `models.py` z bezpiecznymi domyśłami dla round-trip ze starszymi snapshotami M4; `Plan.validate_tasks` rozluźnione z „dokładnie 3” na „min 1”; `PlannerProposal` (wejście M1–M3) zachowuje min/max 3 jako semantyczne wejście, nie model domenowy; weryfikator „dokładnie 3 taski” pozostaje (demo M1, zastąpiony w T13). T04 jest `IN IMPLEMENTATION` na branchu `vibe/t04-snapshot-domain-model-4d91fb` z `a7788a1`: dodano `TaskBudget`/`RunBudget`/`GateOccurrence`, pola `schema_version`/`revision`/`needs_human_task_ids`/`gate`/`budget`, `allowed_tools`/`accepted_evidence_refs`/`budget` na `ChildTask`, walidator `validate_register_invariants` (leniwiony o stany przejściowe M4 do T07), detekcję cykli zależności oraz 7 deterministycznych helperów tożsamości (`task_id_for` … `decision_id_for`); `gate_id_for`/`decision_id_for` pokrywają `_gate_id`/`_decision_id` workflowu (jeden autorytet). Po ewentualnej akceptacji T04: sprawdź nowy HEAD i CI oraz przystąp do Gate C (T04–T06 ACCEPTED + kontrolny restart na stubie). Nie rozpoczynaj T05 ani M5 bez odrębnej zgody.

## Jak aktualizować

Ten plik zawiera tylko aktualny stan, zatwierdzony następny krok, ważne ograniczenia i odnośniki. Przy kolejnym rzeczywistym zdarzeniu (merge, zaakceptowany task, wynik CI, decyzja o milestone) zmień datę, referencyjny SHA i odpowiednie fakty **w tym jednym pliku** w zatwierdzonym PR. Nie twórz równoległego `PROJECT_STATUS.md`, `CURRENT_DEVELOPMENT_ANCHOR.md`, dodatkowego globalnego `HANDOFF.md` ani opisów stanu w README. Sesyjny handoff pojedynczego zadania zapisuj w jego PR/branchu zgodnie z `session-handoff.md`. Fakty implementacji zawsze weryfikuj na Git i testach.
