# **FS-ASM v4.0 CRITICAL SPECIFICATION ADDENDUM**

## **Integracja Wniosków z Projektu PUR-Silnik-fiz-chem**

Status: CONTROL PLANE STANDARD (Mandatory Extension for v3.3)  
Przeznaczenie: Zestaw dyrektyw, które Planning Agent MUSI wdrożyć w plikach .ai/\* i todo.md (zgodnie z metodologią v3.3) na podstawie dowodów z Execution Plane.

## **1\. NOWE PROCESY BEZPIECZEŃSTWA (HARDENING)**

### **1.1. Hard Constraint HC-05: DATA INTEGRITY FINGERPRINT**

Lokalizacja: Must be added to .ai/STANDARDS.md  
Wymagany mechanizm (Dowód z kodu): tests/test\_ml\_manifest\_fingerprint.py

| ID | Nazwa | Dyrektywa dla Coding Agent (Ang. Imperative) |
| :---- | :---- | :---- |
| **HC-05** | **MODEL/DATA FINGERPRINTING** | Directive: The Coding Agent MUST generate a manifest (JSON/YAML) for every trained model/calibration. Content: Manifest MUST include a unique hash (fingerprint) of the input dataset and the feature pipeline used. Prohibition: The Agent is FORBIDDEN from executing prediction if the manifest hash is inconsistent with the data hash. |

### **1.2. Task-Specific Memory (TSM) Protocol**

Lokalizacja: Must be formally defined in a new section (e.g., 2.4. TSM) within the Unified Methodology Specification and referenced in .ai/INSTRUCTIONS.md.  
Wymagany mechanizm (Dowód z kodu): admin/\*\_changelog.md

| Wymóg | Specyfikacja dla Planning Agent (Ang. Imperative) |
| :---- | :---- |
| **TSM Folder** | The admin/ folder is designated as **Task-Specific Memory (TSM)**. It is subordinate to .ai/MEMORY.md (ADR). |
| **Trigger** | TSM MUST be initialized after the **3rd failed OODA loop retry** or upon explicit human instruction to pause a complex task. |
| **Format** | The TSM file MUST follow the naming convention: admin/TODO\[X\]\_PKT\[Y\]\_changelog.md. The content MUST document the \[TIMESTAMP\], \[ROOT CAUSE OF FAILURE\], and the \[DECISION: DECOMPOSITION OR NEXT STEP\]. |

### **1.3. Ujednolicenie Task Register Naming Convention**

**Lokalizacja:** Must be enforced in **TASK REGISTER DESIGN ARCHITECTURE** (Specification of todo.md).

| Status | Zasada Nazewnictwa (Ang. Directive) |
| :---- | :---- |
| **Dozwolone** | Task files MUST use semantic naming based on modules: todo\_engine.md, todo\_ml.md, todo\_cli.md, or sequential phase naming: todo\_phaseX.md. |
| **Zakazane** | Task files MUST NOT use ambiguous numeric naming (e.g., todo1.md, todo2.md) or mixed naming (e.g., DEV\_DASHBOARD\_TODO3.md). **(Reason: State Register ambiguity)** |

## **2\. WYKONYWALNE INNOWACJE (CODIFIED USAGE)**

### **2.1. Ustanowienie .ai/ARCHITECTURE.md**

**Wymóg (Dowód z kodu):** docs/STRUCTURE.md, docs/MODEL\_OVERVIEW.md

| Plik | Akcja dla Planning Agent | Treść (Source) |
| :---- | :---- | :---- |
| **.ai/ARCHITECTURE.md** | Planning Agent MUST generate this file during BOOTSTRAP. | Content MUST be a synthesis of the architectural diagrams and module dependencies found in docs/STRUCTURE.md and docs/MODEL\_OVERVIEW.md. |
| **Wpływ** | Directive: This file becomes the single source of truth for the OODA ORIENT phase (Architectural Alignment check). |  |

### **2.2. Imperatywy Obchodzenia Się z Kodem**

**Lokalizacja:** Must be added to .ai/INSTRUCTIONS.md (AGENT KERNEL).

| Imperatyw | Dyrektywa dla Coding Agent (Ang. Imperative) | Wpływ na Logikę (Redukcja Search Space) |
| :---- | :---- | :---- |
| **USAGE ANCHORING** | Directive: For functional usage examples and API interaction, the Agent MUST prioritize reading tests/test\_smoke\_e2e.py over abstract documentation. | **CZYSTOŚĆ LOGIKI:** Skrypt testowy jest czystą, wykonywalną instrukcją API. Agent uczy się, jak używać modułu pur\_mold\_twin bez halucynowania składni. |
| **TOOLING FIRST** | Directive: The Agent MUST utilize pre-existing executable scripts in the scripts/ folder (e.g., calibrate\_model.py) for high-level operations. Prohibition: The Agent is FORBIDDEN from re-implementing logic contained in scripts/ in src/ modules (unless the task is REFECTOR). | **OSZCZĘDNOŚĆ TOKENÓW:** Zapobiega reinwencji koła i generowaniu zbędnego kodu, kierując Agentów na gotowe, sprawdzone narzędzia. |

### **2.3. Twarda Weryfikacja (ML/Optimization)**

**Lokalizacja:** Must be added to **TASK REGISTER DESIGN ARCHITECTURE** (Specyfikacja TODO).

| Zasada | Treść (Ang. Standard) |
| :---- | :---- |
| **Verifiability (ML/OPT)** | The \*Verification: payload for tasks tagged \[ML\] or \[OPT\] MUST contain two explicit references: 1\. **Metric:** Reference to a metric from eval/metrics.py (e.g., RMSE). 2\. **Threshold:** The required quality value (e.g., \< 0.05 or Cost reduction \> 10%), sourced from configs/quality/default.yaml. |
| **Wpływ** | **Mierzalna Definicja DONE:** Zabezpiecza przed zatwierdzeniem tasku, który działa, ale nie spełnia minimalnych progów jakości zdefiniowanych w plikach konfiguracyjnych. |

Niniejszy plik zawiera **surowy, inżynierski zestaw dyrektyw** do wdrożenia. Nie ma tu "lania wody", są tylko "rozkazy" poparte odniesieniami do Twojego kodu.