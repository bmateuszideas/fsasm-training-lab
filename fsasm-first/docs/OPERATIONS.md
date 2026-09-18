# FS-ASM Runtime v1  Operacje i profil hybrydowy

> **Zakres:** operacyjne uycie FS-ASM Runtime v1 na laptopie uytkownika.
> **Architektura:** [Kanon v1](../FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md) SHA-256 `56aeeb60c8c700c71dc3d395659127afbf511e1726e0ffd76270c848fd764808`.
> **Wymagania:** Python 3.12+, `uv`, pakiet z `uv.lock` (mistralai-workflows 3.x).

## 1. Profil hybrydowy: co dziaaa lokalnie, co przez Mistral

FS-ASM Runtime v1 uywa **profilu hybrydowego**:

| Komponent | Lokalnie | Przez Mistral API | Uwagi |
|---|---|---|---|
| **Planner** (tworzenie planu) | [31mNie[0m | [32mTak[0m | Wy105cznie przez Mistral (rola PLANNER) |
| **Executor** (ptla modelowa) | [32mTak[0m | [31mNie[0m | Domylnie lokalny model (T19) |
| **Consultation** (konsultacja) | [31mNie[0m | [32mTak[0m | Rola API_A, owner NIEzmieniony |
| **Handover** (przekazanie) | [31mNie[0m | [32mTak[0m | Rola API_B, wski scope |
| **Tool Broker** (narzdzia) | [32mTak[0m | [31mNie[0m | Operacje plikowe na workspace |
| **Verifier** (weryfikacja) | [32mTak[0m | [31mNie[0m | Czyta RZECZYWISTE artefakty |
| **State Repository** (stan) | [32mTak[0m | [31mNie[0m | `state.json` autorytet |
| **Human Gate** (decyzje) | [32mTak[0m | [31mNie[0m | Przechowywany w snapshocie |

### 1.1 rda sieciowe

| Usuga | Wymagana | Port | Uwagi |
|---|---|---|---|
| **Temporal Server** (Workflows) | [32mTak[0m | 7242 | `MISTRAL_WORKFLOWS_HOST` |
| **Mistral API** | Opcjonalnie | 443 | Tylko dla Planner/Consultation/Handover |
| **Local Model Server** | Opcjonalnie | 1234 | Tylko dla lokalnego Executora (LM Studio) |

> **Bez Vibe/GitHub:** Runtime **NIE wymaga** Vibe ani GitHuba podczas normalnej pracy.
> **Bez internetu:** Tryb lokalny (tylko Executor + Tool Broker + Verifier) dziaaa **offline** (bez Planner/Consultation/Handover).

## 2. Konfiguracja rodowiska

### 2.1 Zmienne rodowiskowe (wszystkie opcjonalne)

| Zmienna | Opis | Domylna | Wymagana dla |
|---|---|---|---|
| `MISTRAL_WORKFLOWS_HOST` | URL serwera Temporal | `http://localhost:7242` | Worker |
| `MISTRAL_API_KEY` | Klucz API Temporal | - | Worker |
| `FSASM_RUNS_DIR` | Katalog runw | `./runtime/runs` | CLI |
| `FSASM_WORKSPACE_ROOT` | Root workspace | `<cwd>` | CLI |
| `FSASM_LOCAL_MODEL_ENDPOINT` | Endpoint lokalnego modelu | - | Local Executor |
| `FSASM_MISTRAL_API_KEY` | Klucz API Mistral | - | Planner/Consultation/Handover |
| `FSASM_INCLUDE_HISTORICAL` | Rejestruj M1-M4/hello | `""` (wy05czone) | Research |

> **Bezpieczestwo:** Nigdy nie komituj sekretw. Uyj `.env` (w `.gitignore`).

### 2.2 Plik konfiguracyjny

Minimalna konfiguracja dla trybu lokalnego (tylko Executor + Tools):

```bash
# .env
FSASM_WORKSPACE_ROOT=./my-workspace
FSASM_RUNS_DIR=./my-workspace/runtime/runs
```

Pena konfiguracja hybrydowa (Planner + Local Executor + Mistral roles):

```bash
# .env
MISTRAL_WORKFLOWS_HOST=http://localhost:7242
MISTRAL_API_KEY=your-temporal-key
FSASM_WORKSPACE_ROOT=./my-workspace
FSASM_RUNS_DIR=./my-workspace/runtime/runs
FSASM_LOCAL_MODEL_ENDPOINT=http://localhost:1234
FSASM_MISTRAL_API_KEY=your-mistral-key
```

## 3. Komendy CLI

Runtime udostpnia 4 operacje przez CLI:

### 3.1 `start_new`  Rozpocznij nowy run

**Przeznaczenie:** Utworzenie nowego runu z Human Goal.

```bash
# JSON input (stdin lub plik)
echo '{"goal": "Dodaj obs\u00142ug\u0011 test\u0014w dla modu\u00142u auth"}' | uv run python -m fsasm start_new

# Z run_id (opcjonalne)
echo '{"run_id": "RUN-001", "goal": "..."}' | uv run python -m fsasm start_new

# Z pliku
uv run python -m fsasm start_new < input.json

# Tryb czytelny (human mode)
uv run python -m fsasm start_new --human < input.json
```

**Wejcie:** JSON zgodny z `GoalInput` (patrz [Architektura](../FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md)).

**Wyjcie (JSON):**
```json
{
  "status": "ok",
  "run_id": "RUN-xxxx",
  "revision": 0,
  "state": {"phase": "PLANNING", "active_task_id": null, ...},
  "domain_status": {"phase": "PLANNING", ...}
}
```

**Exit codes:**
- `0`: Sukces (run utworzony)
- `2`: Niepoprawne argumenty/JSON
- `1`: B0d wykonania

**Ograniczenia:**
- Istniejący `run_id` **nie zostanie nadpisany** (b0d `run_id already exists`)
- Planner wymaga `FSASM_MISTRAL_API_KEY` (lub stub jeli nie skonfigurowany)

---

### 3.2 `resume`  Wznw istniejący run

**Przeznaczenie:** Kontynuacja przerwanego runu.

```bash
# Wznw run RUN-001
echo '{"run_id": "RUN-001"}' | uv run python -m fsasm resume

# Tryb czytelny
uv run python -m fsasm resume --human < input.json
```

**Wejcie:** JSON z `run_id` (obowi05zkowy).

**Wyjcie (JSON):**
```json
{
  "status": "ok",
  "run_id": "RUN-001",
  "resumed_from_revision": 5,
  "current_revision": 5,
  "state": {...},
  "domain_status": {...}
}
```

**Exit codes:**
- `0`: Sukces
- `2`: Brak `run_id`
- `1`: Run nie istnieje / niespjny snapshot

**Ograniczenia:**
- Rozstrzyga niepewny skutek **przed** ponowieniem (T23)
- Nigdy nie re-aplikuje starej decyzji Human Gate

---

### 3.3 `status`  Sprawd status runu

**Przeznaczenie:** Odczyt autorytatywnego snapshotu (tylko read).

```bash
# Sprawd status RUN-001
echo '{"run_id": "RUN-001"}' | uv run python -m fsasm status

# Tryb czytelny
uv run python -m fsasm status --human < input.json
```

**Wejcie:** JSON z `run_id` (obowi05zkowy).

**Wyjcie (JSON):**
```json
{
  "status": "ok",
  "run_id": "RUN-001",
  "revision": 5,
  "domain_status": {
    "phase": "RUNNING",
    "active_task_id": "TASK-002",
    "task_status": "RUNNING",
    "needs_human": false,
    "gate": null
  },
  "service_status": {
    "workflows_connected": true,
    "local_model_connected": false
  }
}
```

**Exit codes:**
- `0`: Sukces (run istnieje)
- `2`: Brak `run_id`
- `1`: Run nie istnieje

**Rozrnienie:**
- `domain_status`: Stan domenowy z autorytatywnego snapshotu
- `service_status`: Stan techniczny usug (Temporal, lokalny model)

---

### 3.4 `signal`  Wyle decision Human Gate

**Przeznaczenie:** Wysanie decyzji dla otwartej bramki.

```bash
# RETRY_ONCE dla RUN-001, TASK-002, gate GATE-001, decision DEC-001
echo '{
  "run_id": "RUN-001",
  "task_id": "TASK-002",
  "gate_id": "GATE-001",
  "decision_id": "DEC-001",
  "action": "RETRY_ONCE",
  "reason": "Poprawi b0d kompilacji"
}' | uv run python -m fsasm signal

# ABORT
echo '{
  "run_id": "RUN-001",
  "task_id": "TASK-002",
  "gate_id": "GATE-001", 
  "decision_id": "DEC-002",
  "action": "ABORT",
  "reason": "Poza scope"
}' | uv run python -m fsasm signal
```

**Wejcie:** JSON z pen tosamoci:
- `run_id` (obowi05zkowy)
- `task_id` (obowi05zkowy)
- `gate_id` (obowi05zkowy)
- `decision_id` (obowi05zkowy)
- `action` (obowi05zkowy): `RETRY_ONCE` lub `ABORT`
- `reason` (opcjonalny)

**Wyjcie (JSON):**
```json
{
  "status": "ok",
  "run_id": "RUN-001",
  "gate_id": "GATE-001",
  "decision_id": "DEC-001",
  "action": "RETRY_ONCE",
  "applied": true,
  "new_revision": 6
}
```

**Exit codes:**
- `0`: Sukces (decyzja zaakceptowana i zastosowana)
- `2`: Niepoprawne argumenty / niepena tosamo
- `1`: Brak otwartej bramki / stara/obca/przysza decyzja

**Ograniczenia:**
- CLI **NIE zgaduje** `gate_id` ani `decision_id`
- Waliduje przeciw autorytatywnemu snapshotowi
- Stara/obca/przysza/niepena/duplikowana/sprzeczna decyzja **zostanie odrzucona**
- Dokadnie jedna poprawna `RETRY_ONCE` daje **dokadnie jedno** dodatkowe uprawnienie

## 4. Worker (usuga Temporal)

### 4.1 Uruchomienie workera

```bash
# Zainstaluj pakiet
uv sync --frozen

# Uruchom workera (rejestruje FS-ASM Runtime v1)
uv run python -m entrypoints.worker
```

**Co robi worker:**
- Rejestruje **tylko** FS-ASM Runtime v1 (M1-M4/hello **wykluczone** z domylnego discovery)
- Obsuguje workflow: Human Goal  Planner  Compiler  Scheduler  Executor  Verifier  Evidence  State
- Wymaga `MISTRAL_WORKFLOWS_HOST` i `MISTRAL_API_KEY` (Temporal)

**Opcje:**
- `FSASM_INCLUDE_HISTORICAL=1`: Rejestruj historyczne demonstratory (tylko dla research)

### 4.2 Uruchomienie workera z historycznymi (research)

```bash
FSASM_INCLUDE_HISTORICAL=1 uv run python -m entrypoints.worker
```

## 5. Workflow (przebieg)

### 5.1 Peny przebieg (hybrydowy)

```
Human Goal 
  [34m[0m
  Planner (Mistral API, rola PLANNER) 
    [34m[0m
    PlannerProposal (niezaufane) 
      [34m[0m
      Task Compiler (runtime-owned) 
        [34m[0m
        Plan (autorytatywny) 
          [34m[0m
          State Repository (revision 0) 
            [34m[0m
            Scheduler (wybiera Child Task) 
              [34m[0m
              Context Builder (ograniczony kontekst) 
                [34m[0m
                Model Gateway (lokalny model) 
                  [34m[0m
                  Executor Loop 
                    [34m[0m
                    Tool Broker (operacje plikowe) 
                      [34m[0m
                      ToolObservation 
                        [34m[0m
                        Verifier (rzeczywisty artefakt) 
                          [34m[0m
                          Evidence (utrwalone) 
                            [34m[0m
                            Domain Core (zatwierdza PASS) 
                              [34m[0m
                              State Repository (revision N+1) 
                                [34m[0m
                                Nastepny Child Task...
```

### 5.2 Consultation (konsultacja)

```
Executor (lokalny) 
  [34m[0m
  Model Router (consultation) 
    [34m[0m
    Mistral Adapter (rola API_A) 
      [34m[0m
      Wskazwka (do kontekstu) 
        [34m[0m
        Executor (lokalny, owner NIEzmieniony)
```

### 5.3 Handover (przekazanie)

```
Executor (lokalny) 
  [34m[0m
  Model Router (handover) 
    [34m[0m
    Mistral Adapter (rola API_B) 
      [34m[0m
      Nowy Executor (wski scope) 
        [34m[0m
        ... (ptla modelowa) 
          [34m[0m
          Wynik 
            [34m[0m
            Domain Core (zatwierdza)
```

### 5.4 Human Gate (decyzja czoweka)

```
Wyczerpanie prób / blokada 
  [34m[0m
  Gate (w snapshocie) 
    [34m[0m
    Decyzja (RETRY_ONCE / ABORT) 
      [34m[0m
      Domain Core (aplikuje) 
        [34m[0m
        State Repository (revision N+1)
```

## 6. Retry i budety

| Typ retry | Kiedy | `task_attempt` | Budet |
|---|---|---|---|
| **Techniczny** (transport) | B0d sieci/timeout | [31mNie[0m | `TransportRetryBudget` |
| **Merytoryczny** (FAIL) | Negatywna weryfikacja | [32mTak[0m | `max_attempts` |
| **Agent Step** | Iteracja modelowa | [31mNie[0m | `ModelCallBudget` |

**Limity:**
- `max_attempts`: Maksymalna liczba prb merytorycznych (konfigurowalny, T29)
- `max_escalations_per_run`: Maksymalna liczba eskalacji (T21)
- `max_handovers_per_task`: Maksymalna liczba handoverw (T21)
- `max_consultations_per_task`: Maksymalna liczba konsultacji (T21)
- `model_call_count`: Maksymalna liczba wywoa modelu w jednej prbie (T16)
- `tool_call_count`: Maksymalna liczba wywoa narzdzi w jednej prbie (T16)

## 7. Dane wychodz ce (Data Egress)

### 7.1 Co jest wysyane do Mistral API

| Typ | Dane | Cel |
|---|---|---|
| Planner | Human Goal + constraints | Generowanie planu |
| Consultation | Context (ograniczony) + pytanie | Wskazwka |
| Handover | Context (ograniczony) + task | Przekazanie |

**Ograniczenia:**
- Kontekst jest **ograniczony** (Context Builder, T15)
- Kady fragment ma **provenance** (sk d rdo)
- Sekrety s  **redagowane** (RedactionPolicy, T25)
- Pliki spoza scope **nie s  wysyane**

### 7.2 Co NIE jest wysyane

- Pene pliki repo (tylko fragmenty z provenance)
- Sekrety (klucze, tokeny, hasa)
- Pliki spoza `allowed_files`
- Historia niezwi zana z bie c prb 
- Stan wewntrzny (snapshot jest autorytetem lokalnym)

## 8. Diagnostyka (doctor)

```bash
# Uruchom doctor (sprawdza rodowisko)
uv run python -m entrypoints.doctor

# Sprawd konkretne elementy
uv run python -m entrypoints.doctor --check python
uv run python -m entrypoints.doctor --check packages
uv run python -m entrypoints.doctor --check workflows
```

**Co sprawdza doctor:**

| Check | Opis | Wymagane |
|---|---|---|
| Python | Wersja >= 3.12 | [32mTak[0m |
| uv | Dostpno | [32mTak[0m |
| Packages | fsasm-first, mistralai-workflows, pydantic, httpx | [32mTak[0m |
| Workflows | Po0czenie z Temporal | Nie (opcjonalne) |
| Local Model | Po0czenie z endpointem | Nie (opcjonalne) |
| Mistral API | Po0czenie z API | Nie (opcjonalne) |
| Filesystem | Uprawnienia workspace/runs | [32mTak[0m |
| Workspace | Struktura katalogw | [32mTak[0m |

## 9. Przykady

### 9.1 Peny scenariusz (lokalny + Mistral)

```bash
# 1. Skonfiguruj rodowisko
cp .env.example .env
# Edytuj .env: MISTRAL_WORKFLOWS_HOST, MISTRAL_API_KEY, FSASM_MISTRAL_API_KEY

# 2. Uruchom doctor
uv run python -m entrypoints.doctor

# 3. Uruchom workera (w oddzielnym terminalu)
uv run python -m entrypoints.worker

# 4. Rozpocznij nowy run
cat <<EOF | uv run python -m fsasm start_new
{
  "goal": "Stwrz modu2 auth z testami jednostkowymi",
  "constraints": {
    "max_tasks": 5,
    "allowed_files": ["src/auth/**", "tests/**"],
    "workspace_scope": "src/"
  }
}
EOF

# 5. Sprawd status
# (pobierz run_id z wyjcia start_new)
echo '{"run_id": "RUN-xxxx"}' | uv run python -m fsasm status

# 6. W przypadku bramki, wyle decision
# (pobierz gate_id/decision_id z statusu)
echo '{
  "run_id": "RUN-xxxx",
  "task_id": "TASK-002",
  "gate_id": "GATE-001",
  "decision_id": "DEC-001",
  "action": "RETRY_ONCE",
  "reason": "Popraw b0d w testach"
}' | uv run python -m fsasm signal

# 7. Wznw po restarcie
echo '{"run_id": "RUN-xxxx"}' | uv run python -m fsasm resume
```

### 9.2 Tryb lokalny (tylko Executor + Tools)

```bash
# 1. Tylko lokalne komponenty (bez Planner/Mistral)
cat <<EOF | uv run python -m fsasm start_new
{
  "goal": "Prosty patch w pliku",
  "constraints": {
    "max_tasks": 1,
    "allowed_files": ["src/module.py"],
    "workspace_scope": "src/"
  }
}
EOF

# 2. Uruchom workera z lokalnym modelem
FSASM_LOCAL_MODEL_ENDPOINT=http://localhost:1234 \
  uv run python -m entrypoints.worker
```

## 10. Rozwi zywanie problemw

### 10.1 B0d: "run_id already exists"

**Przyczyna:** Prba nadpisania istniejecego runu.
**Rozwi zanie:** Uyj innego `run_id` lub usu stary run z `FSASM_RUNS_DIR`.

### 10.2 B0d: "no open gate for run"

**Przyczyna:** Prba wysania signal bez otwartej bramki.
**Rozwi zanie:** Sprawd status runu (`status`) i poczekaj na bramk.

### 10.3 B0d: "stale revision"

**Przyczyna:** Prba wznowienia z nieaktualn  revision.
**Rozwi zanie:** Upewnij si, e masz najnowszy stan (inny proces mg zosta zaktualizowany).

### 10.4 B0d: "policy blocked"

**Przyczyna:** Operacja poza dozwolonym scope.
**Rozwi zanie:** Sprawd `allowed_files` i `workspace_scope` w konfiguracji.

### 10.5 B0d: "model unavailable"

**Przyczyna:** Lokalny model nie jest dostpny.
**Rozwi zanie:** Sprawd `FSASM_LOCAL_MODEL_ENDPOINT` i uruchom serwer modelu.

### 10.6 B0d: "workflows disconnected"

**Przyczyna:** Brak po0czenia z Temporal.
**Rozwi zanie:** Sprawd `MISTRAL_WORKFLOWS_HOST` i `MISTRAL_API_KEY`.

## 11. Limity i gwarancje

### 11.1 Gwarancje

- [32mJeden snapshot[0m: Autorytatywny stan (plan + Task Register + gate + counters + evidence refs)
- [32mJeden Domain Core[0m: Tylko on zatwierdza PASS/retry/gate
- [32mRzeczywiste artefakty[0m: PASS tylko z rzeczywistego artefaktu i checku aktualnej prby
- [32mDeterministyczne przejcia[0m: Ten sam state+event  ten sam wynik
- [32mBounded retry[0m: Transport retry NIE zwiksza `task_attempt`
- [32mBez Vibe/GitHub[0m: Normalna praca NIE wymaga Vibe ani GitHuba

### 11.2 Ograniczenia (fikcyjne exactly-once)

- [31mNIE gwarantujemy[0m exactly-once dla zewntrznych skutkw (np. zewntrzne API)
- [31mNIE gwarantujemy[0m at-least-once dla crashy przed commit
- [31mNIE gwarantujemy[0m brak duplikatw w niekontrolowanym rodowisku

**Co robimy:**
- Checkpointy (BEFORE_EFFECT, EFFECT_APPLIED, EVIDENCE_PERSISTED, COMMITTED)
- Reconciliation (inspekcja artefaktu + snapshotu przed ponowieniem)
- Idempotency (stara decyzja Human Gate NIE zostanie ponowiona)

### 11.3 Znane ograniczenia

- Tylko **jeden aktywny task** naraz (T09)
- Tylko **sekwencyjne** wykonanie (nie rwnolege)
- **Brak** Web UI (tylko CLI)
- **Brak** fine-tuningu / LLMC
- **Brak** vector DB (Context Builder uywa jawnego search)

## 12. Bezpieczestwo

### 12.1 Redakcja sekretw

Wszystkie sekrety s  **automatycznie redagowane** w:
- Promptach modelu
- Observations (ToolObservation)
- stdout/stderr
- Raportach

**Wzorce redagowane:**
- GitHub PAT: `ghp_*`, `github_pat_*`
- Mistral API Key: `sk-*`, `api_key=*`
- Bearer token: `Bearer *`
- Oglne: `<SECRET:...>`

### 12.2 Ograniczenia scope

- **Workspace root**: Wszystkie operacje s  relative do workspace root
- **Allowed files**: Tylko pliki z `allowed_files` mog  by odczytane/zapisane
- **Containment**: Traversal `..` i symlink escape s  blokowane
- **Tool Broker**: Niedozwolone operacje s  odrzucane **przed** skutkiem

### 12.3 Izolacja procesw

- **run_checks**: Wykonuje zaufane argv (allowlista)
- **Env allowlist**: Tylko `PATH`, `PYTHONPATH`, `HOME`, `LANG`, `LC_ALL`
- **Timeout**: Kade wywoanie ma limit czasu
- **Output limit**: stdout/stderr s  truncowane z markerem
- **Shell=False**: Brak shell interpolation (argv list)

## 13. Monitorowanie i logi

### 13.1 Trajektoria (audit)

Kady run ma **trajektori** (append-only audit projection):

```
task  context  model_call  tool_call  observation  verification  evidence  state_transition
```

**Co jest rejestrowane:**
- `run_id`, `task_id`, `attempt`, `step`
- `operation_id`, `artifact_id`, `evidence_id`
- backend, liczniki, czas
- tokeny/koszt (jeli dostpne)

**Co NIE jest rejestrowane:**
- PASS (autorytetem jest snapshot)
- Sekrety (redagowane)
- Pene pliki (tylko fragmenty z provenance)

### 13.2 Logi

**Poziomy logowania:**
- `DEBUG`: Szczegowe informacje (rozwijanie)
- `INFO`: Gwne zdarzenia (produkcja)
- `WARNING`: Ostrzeenia (np. truncation)
- `ERROR`: Bdy (np. policy block)

**Format:**
```
[YYYY-MM-DD HH:MM:SS] [LEVEL] [component] message
```

## 14. Weryfikacja instalacji

```bash
# 1. Pene testy
uv run pytest

# 2. Diagnostyka rodowiska
uv run python -m entrypoints.doctor

# 3. Sprawd jako kodu
uv run ruff check src/workflows/ src/fsasm/
uv run ruff format --check src/workflows/ src/fsasm/
uv run mypy src/workflows/ src/fsasm/

# 4. Sprawd Makefile
make check
```

## 15. Czyszczenie

```bash
# Usu rodowisko wirtualne
rm -rf .venv

# Usu build artifacts
rm -rf __pycache__ *.egg-info dist/

# Usu runy
rm -rf runtime/runs/*
```

---

**Pytania:** Patrz [Architektura](../FSASM_ARCHITEKTURA_RUNTIME_V1_ZATWIERDZONA_2026-09-17.md) i [Kanoniczne TODO](../FSASM_RUNTIME_V1_CANONICAL_TODO.md).

**Bdy:** Otwrz issue w repozytorium z reproduktorem (bez sekretw).

**Wersja:** v1 (17.09.2026), zaktualizowano: T28.
