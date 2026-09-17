# FS-ASM — repository handoff / jeden bieżący punkt statusowy

**Aktualizacja dokumentacji:** 17.09.2026. **Zweryfikowany punkt odniesienia:** `Fsasm-experimental` @ `31d6724c5551939de9e2dd22e4e9762a2f5bab06` (merge PR #25, T02 G4/G5 drain attribution). To datowany snapshot, nie gwarancja aktualnego HEAD. Każda kolejna sesja weryfikuje żywy HEAD, PR i CI przed rozpoczęciem zadania.

## Cel i uprawnienia

[Zatwierdzona architektura v1](../../../../fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md) jest jedynym kontraktem celu (SHA-256 `56aeeb60c8c700c71dc3d395659127afbf511e1726e0ffd76270c848fd764808`). [Decyzje wdrożeniowe](../../../../fsasm-first/docs/DEPLOYMENT_DECISIONS.md) doprecyzowują profil hybrydowy Workflows i zgodę na jawne dane/telemetrię. `Fsasm-experimental` jest linią integracyjną; `main` pozostaje osobno. Użytkownik + ChatGPT planują/review, Vibe Code Web pisze kod. Nie zmieniaj kanonu, kodu lub milestone'ów na podstawie samego handoffu.

## Potwierdzone na wskazanym punkcie odniesienia

- [PR #23](https://github.com/bmateuszideas/fsasm-training-lab/pull/23) (T00) scalony do `Fsasm-experimental` 17.09.2026; merge SHA `fae7bcf`. Kanoniczny TODO i pojedynczy handoff są w linii integracyjnej.
- [PR #24](https://github.com/bmateuszideas/fsasm-training-lab/pull/24) (T01) scalony 17.09.2026; merge SHA `de302b5`. T01 niezależnie odtworzyło G3, G4 i G5 na HEAD `a470cdd` — wszystkie `PRESENT` (G3: legacy consent reassignable across gates; G4/G5: rejection attribution/drain). Raport reprodukcji przypięty do SHA; bez zmian kodu produkcyjnego.
- [PR #25](https://github.com/bmateuszideas/fsasm-training-lab/pull/25) (T02) scalony 17.09.2026; merge SHA `31d6724`. T02 naprawiło G4/G5 (atrybucja i drain odrzuceń Human Gate) bez regresji RETRY_ONCE/ABORT; późne rejection nie ginie, `None` pozostaje `None`.
- M1–M3 historycznie CLOSED. M4 jest demonstratorem z retry i Human Gate, ale **OPEN**; T00–T02 go nie zamykają. M5 **NOT STARTED**. LLMC/fine-tuning odłożone.
- M4 wykonuje tylko `TASK-001` przez deterministyczny stub. Nie ma kompletnego schedulera, Tool Brokera, niezależnego Verifiera artefaktów, realnej pętli model–narzędzie–obserwacja, Gatewaya ani pełnego operacyjnego resume.
- Audyt Astry wskazał G3–G5 oraz szersze luki G1/G2 (revision i niezależne evidence). [Pełny datowany raport](../../../../fsasm-first/docs/reviews/FSASM_V1_ARCHITECTURE_GAP_ANALYSIS_AND_MIGRATION_PLAN_2026-09-17.md). T01 potwierdziło G3–G5 PRESENT; T02 naprawiło G4/G5.

## Jedyny bieżący krok i status decyzji

**Kanon kolejności:** [Kanoniczny program wykonawczy](../../../../fsasm-first/docs/FSASM_RUNTIME_V1_CANONICAL_TODO.md) (T00–T34 + bramki) jest jedynym aktywnym programem kolejności prac. Wczesna [kolejka migracji](../../../../fsasm-first/docs/MIGRATION_BACKLOG_V1.md) jest dokumentem historycznym zastąpionym przez kanoniczne TODO.

**Następny krok: T03 — warunkowa korekta tożsamości zgody Human Gate.** T01 potwierdziło G3 `PRESENT`, więc T03 jest wymagany. **Decyzja użytkownika (payload legacy):** runtime wymaga pełnych `run_id`, `task_id`, `gate_id`, `decision_id` na granicy; przyjazny klient pobiera aktualną bramkę i wysyła kompletny payload (zgodnie z rekomendacją). T03 jest `IN IMPLEMENTATION` w swoim PR (branch `vibe/t03-g3-legacy-consent-identity-4d91fb`): handler odrzuca niepełny/obcy/stary/przyszły payload jako `incomplete_payload` przed rezerwacją bramki, zachowuje first-valid-wins i stabilny `decision_id`, a testy legacy zostały zaktualizowane do kontraktu pełnych ID. Po ewentualnej akceptacji T03: sprawdź nowy HEAD i CI oraz przystąp do Gate AB (T00–T03 ACCEPTED lub warunkowe NOT REQUIRED + pełny pytest zielony). Nie rozpoczynaj T04 ani M5 bez odrębnej zgody.

## Jak aktualizować

Ten plik zawiera tylko aktualny stan, zatwierdzony następny krok, ważne ograniczenia i odnośniki. Przy kolejnym rzeczywistym zdarzeniu (merge, zaakceptowany task, wynik CI, decyzja o milestone) zmień datę, referencyjny SHA i odpowiednie fakty **w tym jednym pliku** w zatwierdzonym PR. Nie twórz równoległego `PROJECT_STATUS.md`, `CURRENT_DEVELOPMENT_ANCHOR.md`, dodatkowego globalnego `HANDOFF.md` ani opisów stanu w README. Sesyjny handoff pojedynczego zadania zapisuj w jego PR/branchu zgodnie z `session-handoff.md`. Fakty implementacji zawsze weryfikuj na Git i testach.
