# FS-ASM — wejście do repozytorium dla agentów

**Aktywny kierunek rozwoju: `Fsasm-experimental`.** `main` to odrębna linia historyczna; nie synchronizuj jej bez zgody. Na początku sesji sprawdź aktualny HEAD, stan PR i CI. Żaden datowany SHA w dokumentacji nie jest automatycznie aktualny.

## Hierarchia źródeł

1. **Jedyna zatwierdzona architektura docelowa:** [`fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md`](fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md). Przeczytaj CAŁOŚĆ, także części XIX i XX. Dokument przeniesiono bez zmian ze źródeł projektu ChatGPT; oczekiwany SHA-256: `56aeeb60c8c700c71dc3d395659127afbf511e1726e0ffd76270c848fd764808`. Jeżeli pliku nie ma albo hash jest inny, wstrzymaj zmianę architektoniczną i zgłoś problem.
2. [Późniejsze, jawne decyzje użytkownika](fsasm-first/docs/DEPLOYMENT_DECISIONS.md) doprecyzowują profil wdrożenia i transmisję danych, nie edytując kanonu.
3. [Status implementacji](fsasm-first/PROJECT_STATUS.md) to datowana migawka; aktualny Git, kod i rzeczywiście uruchomione testy rozstrzygają, co istnieje. Zamknięcie milestone'u wymaga odrębnej akceptacji użytkownika.
4. [Mapa dokumentacji](fsasm-first/docs/DOCUMENTATION_MAP.md), [polityka branchy](fsasm-first/docs/BRANCH_POLICY.md), [kontrakt implementacyjny](fsasm-first/AGENTS.md) i jawnie zaakceptowane zadanie określają proces.
5. Starsze modele, raporty, anchor, summary i historia Gita są kontekstem/dowodem datowanego stanu, a nie alternatywnym źródłem architektury lub upoważnieniem do pracy.

## Odpowiedzialności

Użytkownik i ChatGPT prowadzą architekturę, zatwierdzają taski i wykonują review. **Wyłącznie Mistral Vibe Code Web / GLM-5.2 implementuje KOD runtime'u.** Vibe jest zewnętrznym programistą systemu, nie lokalnym Executorem ani modelem Mistral API wewnątrz FS-ASM. Repozytorium służy rozwojowi i transferowi kodu, a nie jest wymaganą zależnością gotowego runtime'u.

Model nie posiada trwałego stanu ani prawa do własnego PASS; reguły, scheduler, scope, weryfikacja i stan należą do kodu. Nie traktuj `CURRENT_FSASM_MODEL.md`, tekstowego „zaczynamy M1”, stubów ani historycznego planu M1–M6 jako zatwierdzonego kontraktu v1.

## Wejście do pracy

Przeczytaj architekturę, decyzje wdrożeniowe, aktualny status, mapę dokumentacji i konkretne polecenie. Następnie sprawdź odpowiednie pliki/testy na bieżącym SHA. Dla SDK używaj `fsasm-first/.agents/skills/workflows/SKILL.md`; opcjonalny skill `.vibe/skills/fsasm-vibe-coding/` dotyczy metody programowania, nie funkcji runtime'u.

Pracuj nad jednym jawnie zaakceptowanym zadaniem. Bez odrębnej zgody nie rozpoczynaj M5, LLMC, integracji `main`, realnych testów 7B w chmurowym Vibe, merge ani usuwania branchy. Zmiana dokumentacji w tym pakiecie została osobno zlecona; nie jest zgodą na zmianę kodu. Weryfikuj rezultaty i raportuj SHA, rzeczywiste testy i znane ograniczenia.
