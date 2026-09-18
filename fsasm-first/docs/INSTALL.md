# FS-ASM Runtime v1 — Installacja

> **Zakres:** pakiet Python 3.12+, `uv`, `mistralai-workflows` 3.x (zgodnie z lockfile).
> **Zalecnoci sieciowe:** Temporal (Mistral Workflows) opcjonalnie lokalnie, Mistral API dla eskalacji.
> **Bez Vibe/GitHub:** normalna praca nie wymaga Vibe ani GitHuba.

## 1. Wymagania wstpne

- **Python 3.12 lub nowszy** (3.12, 3.13, 3.14).
- **uv** (meneder pakietw, zamiennik pip):
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Temporal server** (Mistral Workflows) — opcjonalnie dla lokalnego workera.
  Mona uruchomi lokalnie lub uywa zdalnego hosta.

## 2. Instalacja pakietu

### 2.1 Klonowanie repozytorium

```bash
# Klonuj repozytorium (nie w sandboxie Vibe)
git clone https://github.com/bmateuszideas/fsasm-training-lab.git
cd fsasm-training-lab/fsasm-first
```

### 2.2 ci0gnij zalecnoci z uv.lock (zamroony profil)

```bash
# Zainstaluj dokadnie to, co jest w uv.lock (Python 3.12+, mistralai-workflows 3.x)
uv sync --frozen
```

> **Uwaga:** `uv.lock` jest autorytatywnym rdem wersji. Nie aktualizuj SDK bez uzasadnionej przyczyny (T28).

### 2.3 Sprawd,  instancja dziaa

```bash
# Uruchom doctor (diagnostyka rodowiska)
uv run python -m entrypoints.doctor

# Sprawd,  pakiet jest importowalny
uv run python -c "import fsasm; print('FS-ASM OK')"
```

## 3. Konfiguracja rodowiska

### 3.1 Kopiuj .env.example i dostosuj

```bash
cp .env.example .env
# Edytuj .env i wypenij potrzebne ustawienia (patrz poniej)
```

### 3.2 Zmienne rodowiskowe (opcjonalne)

| Zmienna | Opis | Wymagana | Domylna |
|---|---|---|---|
| `MISTRAL_WORKFLOWS_HOST` | URL serwera Temporal (Workflows) | Nie | `http://localhost:7242` |
| `MISTRAL_API_KEY` | Klucz API Temporal | Nie | - |
| `FSASM_INCLUDE_HISTORICAL` | Rejestruj historyczne demonstratory (M1–M4, hello) | Nie | `""` (wy05czone) |
| `FSASM_LOCAL_MODEL_ENDPOINT` | Endpoint lokalnego modelu (T19/T29) | Nie | - |
| `FSASM_MISTRAL_API_KEY` | Klucz API Mistral (eskalacja) | Nie | - |

> **Bezpieczestwo:** Nigdy nie komituj kluczy ani tokenw do Git. Plik `.env` jest w `.gitignore`.

## 4. Budowa wheel (opcjonalnie)

```bash
# Zbuduj wheel w czystym rodowisku
uv pip install hatchling
uv pip wheel . --no-deps

# Zainstaluj wheel w nowym rodowisku testowym
python -m venv /tmp/test-venv
source /tmp/test-venv/bin/activate
uv pip install dist/fsasm_first-*.whl
uv run python -m entrypoints.doctor
```

## 5. Weryfikacja instalacji

```bash
# 1. Pene testy (bez Temporal/real model)
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

## 6. Rozwi05zywanie problemw

### 6.1 uv: command not found

```bash
# Zainstaluj uv
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 6.2 Python version < 3.12

```bash
# Zainstaluj Python 3.12+ (np. pyenv)
pyenv install 3.12.0
pyenv local 3.12.0
```

### 6.3 Missing dependencies

```bash
# ci0gnij z uv.lock (zamroony profil)
uv sync --frozen
```

### 6.4 Workflows connectivity failure

```bash
# Sprawd,  Temporal dziaa lokalnie
# Uruchom lokalny Temporal server lub ustaw MISTRAL_WORKFLOWS_HOST
```

## 7. Czyszczenie

```bash
# Usu rodowisko wirtualne i build artifacts
rm -rf .venv __pycache__ *.egg-info dist/
```
