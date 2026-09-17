# Review kodu FS-ASM — procedura

Użyj dla konkretnego commita/PR. Rozpoznaj branch, bazę, HEAD, diff i kryteria odbioru; sprawdź realny Git/CI. [Architektura v1](../../../../fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md) jest kontraktem docelowym, a [repository-handoff](repository-handoff.md) datowanym stanem, nie dowodem poprawności kodu.

Sprawdzaj w kolejności: poprawność i inwarianty, stan/persystencję, evidence i PASS, autoryzację narzędzi, retry/odtwarzanie, testy regresyjne, granice architektury, jakość utrzymania. Dla każdej usterki podaj ścieżkę/funkcję, zaobserwowany efekt, dowód/reprodukcję i ograniczenia. Sprawdź serializację workflow↔activity, state↔plan, run↔task↔attempt, Human Gate↔audit, tool observation↔Verifier.

Odróżniaj stub od realnego wykonania, CI od lokalnej reprodukcji, samoocenę wykonawcy od niezależnego review. Nie zatwierdzaj merge ani zamknięcia milestone'u bez osobnej decyzji użytkownika.
