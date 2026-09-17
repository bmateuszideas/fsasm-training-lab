# FS-ASM — jawne decyzje po zatwierdzeniu architektury v1

**Status: decyzje użytkownika z 17.09.2026.** Ten dokument jest uzupełnieniem profilu wdrożenia; nie przerabia ani nie zastępuje pełnego kanonu.

## D1. Profil hybrydowy Workflows

Użytkownik wybiera wdrożenie: lokalnie na swoim komputerze działają worker FS-ASM, kod runtime'u, workspace, pliki, trwały stan domenowy i model około 7B Q4. Mistral Workflows może wykorzystywać chmurową orkiestrację, historię techniczną i dystrybucję zadań; dostępność podstawowego workflow może zatem wymagać internetu. Offline nie jest wymogiem v1. Nie zamieniać samodzielnie Workflows na inny framework z powodu hybrydowego profilu.

Dwa modele przez Mistral API będą dodatkową, limitowaną warstwą eskalacji. Dokładnych nazw, backendu lokalnej inferencji, ról obu modeli i progów budżetowych jeszcze nie wybrano. Podłączenie prawdziwych modeli następuje dopiero po ukończeniu kompletnego runtime'u, sprawdzeniu na stubach i przeniesieniu na komputer użytkownika. Chmurowy Vibe Code nie ma dostępu do laptopa.

## D2. Świadoma zgoda na dane

Użytkownik aktywnie korzysta z Mistral AI i świadomie udzielił zgód dotyczących wykorzystywania swoich danych z Vibe App, Vibe Code, Studio oraz z poziomu organizacji. Akceptuje przesyłanie jawnych danych Workflows i telemetrii. **Nie dodawać obowiązkowego szyfrowania payloadów, wyłączania telemetrii ani dodatkowego filtrowania danych wyłącznie z przyczyn prywatnościowych.** Zgoda użytkownika nie jest technicznym dowodem, jak dostawca wykorzystuje dane w poszczególnych usługach.

Zgoda na transmisję nie znosi bezpieczeństwa działania: nie umieszczaj kluczy API w repo ani logach; respektuj scope narzędzi, izolację plików, retry i obiektywny Verification. Redukcja wielkich payloadów pomiędzy activities może wynikać z kontroli wersji stanu i wydajności, a nie z założenia, że użytkownik nie chce udostępniać danych Mistralowi.

## Czego ten dokument nie oznacza

Nie zamyka M4, nie zatwierdza migracyjnych tasków, nie uruchamia M5 i nie oznacza rzeczywistego przetestowania profilu na laptopie. Wymagania Workflows do start/worker/signal/resume i rzeczywisty zakres przesyłanych danych mogą być doprecyzowane jako fakty techniczne bez narzucania dodatkowych zabezpieczeń prywatności.
