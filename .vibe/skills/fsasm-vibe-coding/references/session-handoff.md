# Handoff jednej sesji Vibe — tylko konkretne zadanie

Stosuj, gdy kończy się kontekst albo pracę ma kontynuować nowa sesja. **Repozytoryjny status i następna decyzja są tylko w [`repository-handoff.md`](repository-handoff.md)**; nie zakładaj drugiego globalnego `HANDOFF.md` ani nie aktualizuj historycznych snapshotów.

Przed przekazaniem zweryfikuj branch i HEAD, `git status --short`, diff, odpowiednie testy, push i PR. Zapisuj rzeczywiście wykonane czynności, nie obietnice.

W opisie/komentarzu PR albo w pliku na branchu konkretnego zadania umieść:

```markdown
# Task handoff
- Cel i kryteria odbioru:
- Branch integracyjny / base SHA:
- Task branch / HEAD SHA / PR URL:
- Zatwierdzony zakres / poza zakresem:
- Zmodyfikowane pliki i dowody:
- Testy: komenda, wynik i środowisko:
- CI: link, SHA i status lub niewykonane:
- Aktualny blocker / pierwsza błędna wartość:
- Następne ZATWIERDZONE działanie:
- Zmiany tylko lokalne, jeszcze niewypchnięte:
```

Jeżeli handoff jest w pliku, zapisz i wypchnij go na task branch, kiedy jest bezpieczny. Handoff niewysłany z sandboxa Vibe może zniknąć. Przy wznowieniu: odczytaj root `AGENTS.md`, kanon, `repository-handoff.md`, zweryfikuj stan Git/PR/CI, a potem kontynuuj pierwszą niewykonaną zatwierdzoną czynność.
