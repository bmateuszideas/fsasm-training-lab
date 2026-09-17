# FS-ASM — wejście dla agenta pracującego w repozytorium

1. Pracuj na `Fsasm-experimental` jako linii integracyjnej; przed zmianami sprawdź rzeczywisty HEAD, PR i CI. Zmiany proponuj na krótkim branchu zadaniowym i przez PR do `Fsasm-experimental`, bez samodzielnego merge.
2. Przeczytaj **w całości** [`fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md`](fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md). To jedyny zatwierdzony kontrakt docelowej architektury; nie zastępuj go skrótem ani wcześniejszym modelem. Sprawdź SHA-256: `56aeeb60c8c700c71dc3d395659127afbf511e1726e0ffd76270c848fd764808`.
3. Przeczytaj [późniejsze decyzje](fsasm-first/docs/DEPLOYMENT_DECISIONS.md), [repozytoryjny handoff](.vibe/skills/fsasm-vibe-coding/references/repository-handoff.md), a następnie zaakceptowane polecenie konkretnego zadania. Handoff jest jedynym bieżącym punktem statusowym dokumentacji; fakty wdrożenia weryfikuj na kodzie, commitach i testach.
4. Dla Vibe użyj [skilla procesu](.vibe/skills/fsasm-vibe-coding/SKILL.md); dla zmian Mistral Workflows użyj osobnego [`fsasm-first/.agents/skills/workflows/SKILL.md`](fsasm-first/.agents/skills/workflows/SKILL.md). Skill nie udziela upoważnienia do nowych zadań.
5. Użytkownik z ChatGPT zatwierdzają plan i review; Vibe Code Web pisze kod. Vibe nie jest wewnętrznym Executorem FS-ASM. Nie rozpoczynaj samodzielnie kolejnego etapu, nie zamykaj M4/M5, nie usuwaj branchy i nie modyfikuj `main`.

Nie dodawaj kolejnych `AGENTS.md`, globalnych handoffów ani kopii architektury. Nie wolno zrównywać deklaracji modelu z dowodem wykonania. Gdy dokumenty i kod są sprzeczne, zgłoś różnicę zamiast ją ukrywać.
