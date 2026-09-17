# fsasm-vibe-coding — umiejętność zewnętrznego agenta Vibe

To skill **agenta rozwijającego repozytorium**, nie FS-ASM Executor, nie niezależna architektura, nie status projektu i nie zgoda na pracę. Vibe Code Web ładuje materiały z GitHub checkoutu; nie zakładaj możliwości dołączenia pliku architektury w jego czacie. Pełny kanon musi istnieć w repo: [`fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md`](../../../fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md).

`SKILL.md` określa procedurę startu, routing do referencji i granice upoważnienia. `references/fsasm-implementation.md` zawiera krótki kontrakt kodowania; pozostałe referencje dotyczą ogólnego planowania, debugowania, review i handoffu. Zewnętrzne wytyczne SDK są osobno w `fsasm-first/.agents/skills/workflows/SKILL.md` — nie kopiuj ich do tego skilla.

Jeśli Vibe nie odkryje automatycznie skilla, może odczytać pliki jawnie po ścieżce. Samo znalezienie `SKILL.md` nie dowodzi działania autodiscovery. Nie instaluj nowego pluginu ani frameworka w celu obejścia tej kwestii. Testuj discovery wyłącznie na wyraźne polecenie użytkownika.

**Nie odtwarzaj usuniętego `.vibe/README.md` w root repo.** Rozwój kierujemy do `Fsasm-experimental`, a każda zmiana kodu wymaga zatwierdzonego zakresu, osobnego PR i review. Dane o konkretnym milestone'u sprawdzaj w `fsasm-first/PROJECT_STATUS.md` i na aktualnym SHA.
