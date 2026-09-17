# FS-ASM — historyczny development anchor (zakończony)

**Status: ARCHIWALNE.** Oryginalny długi zapis z 9–16.09.2026, w tym stare pauzy na LLMC, priorytety M4 i kolejne „current stop points”, znajduje się w historii Git (blob `9cb2700b2f4544f7a9859f2355793288f47d621a`). Nie jest aktywnym backlogiem, punktowym poleceniem implementacji ani architekturą. Zamiana zawartości tego pliku na krótką notę usuwa konkurencyjny punkt startowy z obecnego drzewa, ale nie usuwa jego pochodzenia z Git.

**Bieżący punkt wejścia:** [PROJECT_STATUS.md](PROJECT_STATUS.md) → [zatwierdzona architektura v1](docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md) → [decyzje wdrożeniowe](docs/DEPLOYMENT_DECISIONS.md) → [kolejka migracji](docs/MIGRATION_BACKLOG_V1.md) → konkretne polecenie użytkownika i aktualny kod.

Fakty historyczne przydatne do interpretacji starszych analiz: M1–M3 zamknięto jako ograniczone etapy demonstratora; M4 implementował retry i Workflows Human Gate dla stuba. Eksperyment LLMC został odłożony, nie wdrożony jako zależność. PR #20 został scalony 17.09.2026, ale zamknięcie M4 wymaga odrębnej akceptacji; G3–G5 z audytu pozostają osobną kwestią do weryfikacji na aktualnym kodzie. M5 nie zostało automatycznie rozpoczęte.

Nie dodawaj tutaj nowych raportów sesji, dyrektyw ani kolejnych datowanych „kotwic”. Aktualizuj wyłącznie krótki `PROJECT_STATUS.md` po zweryfikowanej zmianie stanu projektu; szczegółowy handoff należy do pojedynczego PR lub zadania.
