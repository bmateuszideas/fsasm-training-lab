# FS-ASM — polityka branchy i integracji

**17 września 2026.** `Fsasm-experimental` jest aktywną linią prac nad v1. `main` jest starszym, rozbieżnym branchem, a nie automatycznym wydaniem. Przed każdym działaniem odczytaj live HEAD i PR/CI zamiast przepisywać datowany inwentarz SHA.

## Zwykła praca nad kodem

1. Po osobnej akceptacji jednego zadania utwórz krótkotrwały branch od **bieżącego** `Fsasm-experimental`; PR kieruj do `Fsasm-experimental`.
2. PR dokumentuje pełny diff względem bazy, start/head SHA, testy i rzeczywisty CI, wyłączenia oraz niezakończone kwestie. Nie opisuj tylko ostatniego commita, jeśli PR obejmuje więcej.
3. Reviewer sprawdza faktyczny kod i dowody. Sam `pytest green` ani `merged=true` nie zamykają milestone'u. Scalanie wymaga jawnego zatwierdzenia.
4. Bez osobnej zgody nie zmieniaj `main`, jego statusu default, nie force-pushuj, nie kasuj branchy ani nie przenoś historii. Nie resetuj M4 tylko dlatego, że architektura v1 jest nowsza.
5. Aktualizuj krótki `PROJECT_STATUS.md` przy rzeczywistej zmianie stanu; datowane historyczne dokumenty pozostają oznaczone jako historia.

## Wyjątkowa aktualizacja dokumentacji

Bieżące jednorazowe uporządkowanie kontekstu zostało jawnie zlecone przez użytkownika do `Fsasm-experimental`. Może zostać wdrożone oddzielnym, wyłącznie dokumentacyjnym commitem lub PR bez zmiany `src/`, `tests/`, workflow CI czy innych branchy. Ta zgoda nie rozciąga się na następne prace programistyczne.

## Fakt historyczny

PR [#20](https://github.com/bmateuszideas/fsasm-training-lab/pull/20) scalono 17.09.2026 o 04:53 UTC; badany head `142db38079d2e15c4c65a4a3c9481bb4cdab81fd`, merge commit `f600ed210501030398740ce87006364dd78a034f`. M4 NIE zostało tym automatycznie zamknięte, a raport Astry opisuje G3–G5. Status zmian po tej dacie trzeba potwierdzić przez GitHub.
