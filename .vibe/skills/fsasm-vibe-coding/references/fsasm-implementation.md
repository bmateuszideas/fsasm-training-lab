# FS-ASM — metody implementacji (nie architektura)

Pełny kontrakt: [`fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md`](../../../../fsasm-first/docs/FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md). Stan/aktualne zadanie: [`repository-handoff.md`](repository-handoff.md). Nie zastępuj tych dokumentów niniejszym skrótem.

Pracuj nad jednym zaakceptowanym zadaniem, sprawdź faktyczny branch/HEAD i bezpośrednio istotne funkcje oraz testy. Rozdziel: propozycję LLM od decyzji kodu, niezależny evidence od deklaracji wykonawcy, retry zadania od retry activity, techniczne Workflows od reguł domeny. Testuj rzeczywiste granice serializacji, stan na dysku oraz nieautoryzowany PASS; nie polegaj na współdzielonej tożsamości obiektów Pythona po przejściu przez activity. Wykorzystuj zabezpieczenia już istniejące, nie implementuj kolejnego frameworka orkiestracji.

Dla SDK czytaj `fsasm-first/.agents/skills/workflows/SKILL.md`; dla debugowania `systematic-debugging.md`, dla większych zmian `large-code-planning.md`, dla niezależnego review `code-review.md`. W razie sprzeczności kieruj się pełnym kanonem i jawną decyzją użytkownika. Zmieniaj wyłącznie zakres zaakceptowanego tasku, weryfikuj odpowiednie testy i rzeczywiste skutki, kończ PR bez merge.
