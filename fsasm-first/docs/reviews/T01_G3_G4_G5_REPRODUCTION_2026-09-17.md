# T01 — Niezależna reprodukcja G3, G4 i G5 na aktualnym HEAD

**Task:** T01 (kanoniczne TODO `FSASM_RUNTIME_V1_CANONICAL_TODO.md`).
**Status:** `READY FOR REVIEW` — raport weryfikacyjny, **bez napraw kodu produkcyjnego**.
**Data:** 17.09.2026.

## Punkt odniesienia

- **Linia:** `Fsasm-experimental`.
- **SHA:** `fae7bcf2b3a5c5a6578e9d019dac8a66eda38510` (merge PR #23, po `ACCEPTED` T00).
- **CI na SHA:** zielony (`CI - fsasm-experimental`, `fae7bcf`).
- **Kanon architektury:** SHA-256 `56aeeb60c8c700c71dc3d395659127afbf511e1726e0ffd76270c848fd764808` — zgodny z kontraktem.
- **Audyt źródłowy:** [`FSASM_V1_ARCHITECTURE_GAP_ANALYSIS_AND_MIGRATION_PLAN_2026-09-17.md`](FSASM_V1_ARCHITECTURE_GAP_ANALYSIS_AND_MIGRATION_PLAN_2026-09-17.md), badany pierwotnie na `142db38`. Audyt wprost zaznacza (§5.5), że istniejące testy D6 sprawdzają bufor w pamięci i wewnętrzny rekord, a **nie** trwałą kopertę, więc nie wykrywają G4/G5.

## Metoda

Reprodukcje komponentowe zgodne z §11.2 audytu: bezpośrednie sterowanie klasą workflow `FsasmMilestoneFourWorkflow` i activity `persist_human_gate_rejections_activity` z kontrolowaną barierą (`monkeypatch`), bez workera Temporal. G3/G4/G5 to mechanizmy czysto w pamięci Pythona; bariera odtwarza okno między pobraniem batcha a aktualizacją kursora. Nie zmieniono żadnego kodu produkcyjnego; dodano wyłącznie nowy plik testu `tests/test_t01_g3_g4_g5_reproducers.py`.

Polecenie: `uv run pytest tests/test_t01_g3_g4_g5_reproducers.py -q -s`.

## Wyniki

| Przypadek | Wynik | Kod | Obserwacja |
|---|---|---|---|
| **G3** — brak `gate_id` pozwala ponownie przypisać starą zgodę | **PRESENT** | `tests/test_t01_g3_g4_g5_reproducers.py::TestG3LegacyConsentReassignedAcrossGates` | Identyczny legacy payload (`task_id=TASK-001`, `RETRY_ONCE`, `reason="one consent"`, bez `gate_id`/`decision_id`) przyjęty dla `gate-1`, a po zamknięciu `gate-1` i otwarciu `gate-2` przyjęty **ponownie** dla `gate-2` (`accepted_decisions` zawiera `gate-2`). Handler wiąże zgodę z `effective_gate_id = cg.gate_id` (bieżąca bramka), więc nieoznaczony payload nie ma wiązania z pierwszą bramką. `decision_id` pozostaje `None` (handler nie dosłownie wypisuje ID w ścieżce signal-handler; dopiero activity `validate_and_apply...` nadaje `decision_id`). To potwierdza lukę v1 §33: legacy zgoda autoryzuje kolejną bramkę. |
| **G4** — odrzucenie sprzed bramki przypisywane bieżącej bramce | **PRESENT** | `tests/test_t01_g3_g4_g5_reproducers.py::TestG4NoOpenGateRejectionMisattributedEnvelope` | `no_open_gate` ma własny `gate_id=None` w buforze (poprawnie), ale `_flush_pending_rejections` wywołuje `persist_human_gate_rejections_activity(run_id, task_id, tag if tag is not None else gate_id, batch)` — dla `tag=None` przekazuje zewnętrzną `gate_id` (otwartą bramkę). Trwała koperta logu (`envelope_gate_id`) = `gate-run-g4-TASK-001-attempt-1`, a **nie** `None`. Docstring twierdzi „flushed with gate_id None” — opis jest silniejszy od kodu. |
| **G5** — sygnał podczas flush pominięty przez kursor | **PRESENT** | `tests/test_t01_g3_g4_g5_reproducers.py::TestG5LateRejectionSkippedByCursorDuringAwait` | Podczas `await` zapisu pierwszego batcha (kontrolowana bariera w `persist_human_gate_rejections_activity`) dopisano drugie, **odrębne** odrzucenie (`reason="wrong_run"`, inny `rejection_id`). Po flush: 2 rekordy w pamięci, kursor = 2, ale tylko 1 `rejection_id` utrwalony; późne odrzucenie (`rej|...|wrong_run|...`) **nie** zostało zapisane. Drugi flush widzi `flushed_rejections >= len(pending)` i kończy wcześnie. Kod ustawia `self.flushed_rejections = len(self.pending_rejections)` po pętli, przeskakując za rekord dopisany podczas `await`. |

## Pełny szczegół obserwacji (stdout z `-s`)

```
[G3] result=PRESENT detail={'gate1': 'gate-run-g3-TASK-001-attempt-1', 'gate2': 'gate-run-g3-TASK-001-attempt-2', 'accepted_for_gate1_id': None, 'gate2_in_accepted_decisions': True, 'gate2_decision_id': None, 'gate2_decision_id_is_new': False, 'accepted_decisions_keys': ['gate-run-g3-TASK-001-attempt-2']}
[G4] result=PRESENT detail={'open_gate_id': 'gate-run-g4-TASK-001-attempt-1', 'inner_record_gate_id': None, 'envelope_gate_id': 'gate-run-g4-TASK-001-attempt-1', 'envelope_rejections_count': 1}
[G5] result=PRESENT detail={'in_memory_rejection_ids': ['rej|gate-run-g5-TASK-001-attempt-1|wrong_gate|TASK-001|||||||', 'rej|gate-run-g5-TASK-001-attempt-1|wrong_run|TASK-001|||||||'], 'persisted_rejection_ids': ['rej|gate-run-g5-TASK-001-attempt-1|wrong_gate|TASK-001|||||||'], 'late_rejection_id': 'rej|gate-run-g5-TASK-001-attempt-1|wrong_run|TASK-001|||||||', 'late_was_persisted': False, 'flushed_rejections_cursor': 2, 'num_log_entries': 1}
3 passed in 0.76s
```

## Wnioski dla kolejnych tasków (zgodnie z kanonicznym TODO)

- **G3 PRESENT** → T03 (warunkowa korekta tożsamości zgody) jest wymagany, ale **wymaga uprzedniej decyzji użytkownika** o polityce payloadów legacy (TODO §6, otwarta decyzja przed T03). Rekomendacja TODO: pełne `run_id`/`task_id`/`gate_id`/`decision_id` na granicy runtime'u.
- **G4 PRESENT i G5 PRESENT** → T02 (warunkowa korekta atrybucji i drain odrzuceń) jest wymagany, ponieważ T01 potwierdza G4 lub G5 (oba). T02 nie wymaga G3.
- T02 i T03 są **osobnymi, niezależnymi** taskami i nie są autoryzowane przez ukończenie T01. Każdy wymaga osobnej zgody użytkownika i własnego SHA startowego.

## Granice pewności

- Reprodukcje są komponentowe (sterowanie klasą + bariera), jak w §11.2 audytu. Udowadniają mechanizm luki w aktualnym kodzie, **nie** są pełnym testem drugiego wykonania przez produkcyjny worker (tego nie wykonano, zgodnie z granicami §11.3). Audyt już wprost stwierdza, że komponentowe próby wystarczą do Q1.
- Nie zmieniono chronionych oczekiwań istniejących testów. Reproduktory są **dodatkowym** plikiem; istniejące testy `test_m4_correction3_reproducers.py` pozostają nietknięte i zielone.
- `INCONCLUSIVE` nie wystąpiło — wszystkie trzy przypadki mają powtarzalny, deterministyczny wynik.

## Rekomendacja

`READY FOR REVIEW`. T01 jest taskiem weryfikacyjnym (raport + reproduktory, bez naprawy kodu). Po ewentualnej akceptacji T01, kolejne autoryzowane taski to T02 (G4/G5) i T03 (G3 + decyzja legacy) — każdy wymaga osobnej zgody.
