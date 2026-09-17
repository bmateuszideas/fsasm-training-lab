# FS-ASM — model historyczny i jego miejsce po zatwierdzeniu v1

**Status: HISTORYCZNE UZASADNIENIE, NIE AKTUALNA ARCHITEKTURA.** Ten plik zachowuje nawigację pod dawną nazwą `CURRENT_FSASM_MODEL.md`, ale nie jest źródłem docelowego kontraktu runtime'u. Oryginał z okresu przed decyzją v1 pozostaje odzyskiwalny z Git history, blob `d7dd9acf93cb9b05ef490456ff4a06ac91eaaf5c`. Nie wolno powoływać się na jego starą listę milestone'ów ani zakres pierwszego MVP jako na nowszą decyzję użytkownika.

## Co jest historycznie ważne

FS-ASM powstał podczas rzeczywistej pracy programistycznej z ChatGPT jako Plannerem i Codexem w VS Code jako Executorem. Użytkownik ręcznie przekazywał zadania i wyniki między nimi przez pliki. Celem był trwały kontekst projektu, kontrola wykonania małych zadań i możliwość bezpiecznej kontynuacji po utracie okna kontekstowego. `TODO as Code` oznaczał program małych, weryfikowalnych kroków, nie luźną checklistę. Późniejsze v7 rozwinęło separację planowania i wykonania, ale nie stworzyło jej od zera.

Współczesny runtime zastępuje ręczny transport kontrolowanym programem: deterministyczny Domain Core, zewnętrzny stan, Context Builder, Tool Broker i niezależny Verifier. Historyczne Markdowny są materiałem badawczym, a nie instrukcją ich dosłownego odtworzenia.

## Gdzie znaleźć obowiązujące informacje

- [Pełna zatwierdzona architektura v1](FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md) — jedyne źródło celu i podziału odpowiedzialności; SHA-256 `56aeeb60c8c700c71dc3d395659127afbf511e1726e0ffd76270c848fd764808`.
- [Decyzje wdrożeniowe](DEPLOYMENT_DECISIONS.md) — profil hybrydowy i świadome udostępnianie danych Mistralowi.
- [Stan obecny](../PROJECT_STATUS.md) — implementacja na datowanych SHA, nie architektura.
- [Audyt i mapa migracji](reviews/FSASM_V1_ARCHITECTURE_GAP_ANALYSIS_AND_MIGRATION_PLAN_2026-09-17.md) — datowany przegląd kodu, a nie automatyczna zgoda na każdy task.

**Reguła:** żadna wcześniejsza reprezentacja `plan.json` jako samodzielnego źródła prawdy, wymóg dokładnie trzech Child Tasks ani polecenie „zaczynaj M1/M5” nie nadpisuje dokumentu v1 i jawnej zgody użytkownika.
