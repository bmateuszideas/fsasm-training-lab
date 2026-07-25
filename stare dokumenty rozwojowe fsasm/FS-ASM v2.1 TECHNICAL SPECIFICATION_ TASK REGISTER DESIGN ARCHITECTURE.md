# **FS-ASM v2.1 TECHNICAL SPECIFICATION: TASK REGISTER DESIGN ARCHITECTURE**

Status: CONTROL PLANE STANDARD  
Target Audience: Planning Agent (System Designer) & Human Supervisor  
Purpose: To define the syntax, semantic structure, and logic required to construct a valid todo.md executable specification for the Coding Agent.

## **0\. PREAMBLE: THE DESIGN CONTRACT**

This specification is **NOT** read by the Coding Agent directly.

It is read by the chat-based **Planning Agent** together with the Human Supervisor, to DESIGN the todo.md files that the Coding Agent will later execute.

Every rule in this document must therefore be interpreted as:

* A **design rule** for how the Planning Agent must write tasks.  
* A **safety rule** that guarantees the Coding Agent can execute each task mechanically, without guessing.

## **1\. FUNDAMENTAL CONCEPT: TODO AS CODE**

In the FS-ASM v2.1 architecture, todo.md is **NOT** a passive wish list, a backlog of feature requests, or a reminder list for a human operator. It is a strictly defined **Control Script** (or "Instruction Tape") designed to be interpreted by a stateless inference engine (the Coding Agent).

In this paradigm, the Coding Agent functions as a stochastic runtime environment that requires precise constraints to operate deterministically. Unlike a human developer who builds up implicit mental context over time, the Coding Agent resets its "state of mind" with every new context window reload. Therefore, the todo.md file must serve as the persistent external program counter and memory, dictating exactly *what* must happen next without reliance on ephemeral chat history.

The Planning Agent must always write todo.md as if it were programming a blind, stateless Coding Agent that only sees these files and cannot "fill the gaps" with human common sense.

As the Planning Agent, your job is **"Programming in Prose"**. You are effectively acting as a compiler, translating high-level business requirements (from README.md, client docs, and architectural decisions) into a low-level, sequential Instruction Set Architecture (ISA) for the Coding Agent. You are not asking the Agent to "think"; you are programming it to "execute".

This compilation process must produce instructions that adhere to three immutable properties:

1. Deterministic (Hallucination-Proof):  
   The instruction must eliminate the need for the Coding Agent to "guess" or "infer" missing information. Ambiguity is the primary driver of hallucinations. If a task says "Improve error handling," the Agent might invent arbitrary error codes. If a task says "Wrap api.py calls in try/except blocks catching ConnectionError," the execution path is fixed. You must define the solution space so tightly that the Agent's probability distribution collapses onto the correct code.  
2. Verifiable (Self-Correcting):  
   Every instruction must possess an objective "Exit Condition" or "Definition of Done" that can be machine-verified. Subjective goals like "Clean up code" are invalid because an LLM cannot objectively measure them. Valid instructions include binary success criteria: a specific test passing (Green bar), a linter returning code 0, or a specific log entry appearing. This allows the Coding Agent's OODA loop to function: it can self-correct because it has a clear signal of failure.  
3. Atomic (Transactional):  
   Adhere to the principle: 1 Task \= 1 State Change \= 1 Commit. Tasks must be irreducible units of work. If a task is "Refactor Authentication," it is too large; if the Coding Agent fails halfway, the codebase is left in a broken, non-deterministic state. By breaking it down into "Create Interface", "Implement Mock", "Swap Implementation", you ensure transactional integrity. If a task fails, the system can rollback to the previous clean state without complex git surgery.

**The Golden Design Rule:**

*"The Coding Agent is blind to everything outside its current context. It does not know what was discussed in the chat, what was done in the previous session, or what is 'obvious' to a human. Your job in todo.md is to inject the necessary context directly into the task definition, creating a self-contained unit of execution that requires no external knowledge to complete."*

## **2\. THE TARGET RUNTIME (CODING AGENT MODEL)**

To design effective instructions, you must understand the consumer. The Coding Agent (CLI) is not a creative partner; it is a **Single-Threaded Loop Machine**. It processes your todo.md using the following strictly serial protocol:

1. FETCH: It reads todo.md and locates the CURRENT (Active Context) section.  
   If the CURRENT section exists, it locks onto the first unchecked \- \[ \] task within that section.  
   If no CURRENT section exists, it locks onto the first unchecked \- \[ \] task anywhere in the file.  
2. **PLAN:** Before coding, it writes a plan into the CURRENT PLAN section (Write-Ahead Log) or .ai/scratchpad.md.  
3. **EXECUTE:** It implements code changes strictly for the active task.  
4. **VERIFY (The Gate):** It runs the verification command defined in your task.  
   * *If Fail:* It loops back to Execute (Max 3 retries).  
   * *If Pass:* It proceeds to Commit.  
5. **COMMIT:** It marks the task as \- \[x\] and returns to FETCH.

**Implication for Planning Agent:** If your task description is vague, the Coding Agent will fail at step 4 or loop infinitely. You must provide the "Exit Condition".

## **3\. REGISTER FILE ANATOMY (MASTER TEMPLATE)**

When designing todo.md, you must strictly adhere to the following memory structure. The Coding Agent relies on these headers as "memory addresses".

\# TASK REGISTER: \[PHASE NAME / MODULE NAME\]

\> \*\*SYNC:\*\* ROADMAP.md Phase \[X\] | \*\*VERSION:\*\* v2.1  
\> \*\*CONTEXT LOCK:\*\* Only tasks defined here are valid execution targets.

\#\# 0\. SESSION CONTEXT (Global Scope)  
\> Define environment variables for the entire session here.  
\* \*\*Goal:\*\* \[Single business goal of this list, e.g., "Build CLI for order handling"\]  
\* \*\*Boundaries:\*\* Work ONLY in \`src/cli/\`. Do NOT touch \`src/core/\`.  
\* \*\*Testing Strategy:\*\* All tests must use \`pytest\` and mock external APIs.

\#\# CURRENT (Active Context)  
\> This is the Coding Agent's processor. ONLY one active task goes here.

\#\#\# ACTIVE TASK  
\- \[ \] \*\*\[ID-001\]\*\* \[Verb\] \+ \[Object\] \+ \[Context\]  
    \* \*Input:\* ...  
    \* \*Constraint:\* ...  
    \* \*Verification:\* ...

\#\#\# CURRENT PLAN (Write-Ahead Log)  
\> Buffer for the Coding Agent (Required by Patch 01).  
\<\!-- AGENT MUST FILL THIS BEFORE CODING \--\>

\#\# 2\. PENDING QUEUE (Instruction Buffer)  
\> Instruction sequence arranged topologically (dependencies first).

\- \[ \] \*\*\[ID-002\]\*\* ...  
\- \[ \] \*\*\[ID-003\]\*\* ...

\#\# 3\. DONE HISTORY (Audit Log)  
\> Execution trace.

\- \[x\] \*\*\[INIT-000\]\*\* Project scaffolded.

## **4\. INSTRUCTION ENGINEERING (TASK SYNTAX DESIGN)**

As a Planning Agent, you cannot write "Do authorization". You must design the task like a function call with parameters.

### **4.1. The Golden Rules of Task Design**

1. **One X \= One Commit:** Never create a task like "Build Backend". Break it down. One task \= one specific feature or fix.  
2. **Zero Guesswork:** Don't write "Make it look nice". Write "Use Click library and green color for success messages".  
3. **Test First:** Every task must specify HOW to verify it. If the Coding Agent doesn't know how to test it, it can't finish it.

### **4.2. Header (Function Signature)**

Format: \- \[ \] \*\*\[ID\]\*\* {ACTION\_VERB} {TARGET\_OBJECT} inside {CONTEXT\_LOCATION}

* **ACTION\_VERB:** Use precise engineering verbs: *Implement, Refactor, Write Test, Define Interface, Migrate*. Avoid: *Think about, Check, Work on*.  
* **TARGET\_OBJECT:** Specific class, function, file.  
* **CONTEXT\_LOCATION:** File path or module path.

### **4.3. Payload (Call Parameters)**

Every critical task **MUST** contain an indented list of parameters (Nested List) that controls the Coding Agent's attention:

* **\* Input:** Where is the input data? (e.g., "See docs/api\_schema.json field user\_id").  
* **\* Constraint:** Negative constraints (Safety Guardrails). (e.g., "DO NOT use external lib requests, use urllib only").  
* **\* Dependency:** What must be done first? (e.g., "Requires \[ID-002\] completed").  
* **\* Verification:** Success condition. (e.g., "Create & Pass test tests/cli/test\_args.py").

### **4.4. Design Example (Bad vs. Good)**

❌ Bad (Non-deterministic):  
\- \[ \] Create a CLI for login.  
(Risk: Coding Agent uses argparse instead of click, skips tests, puts code in main.py instead of module).  
✅ **Good (FS-ASM v2.1 Compliant):**

\- \[ \] \*\*\[CLI-01\]\*\* Implement \`login\_command\` function in \`src/cli/auth.py\`.  
    \* \*Input:\* User credentials (username/password) passed as flags.  
    \* \*Architecture:\* Use \`Click\` library as defined in \`pyproject.toml\`.  
    \* \*Logic:\* Call \`CoreAuthService.authenticate()\` (mocked).  
    \* \*Verification:\* Run \`pytest tests/cli/test\_auth\_command.py\`.

## **5\. SEQUENCING LOGIC (WORKFLOW DESIGN)**

When designing the full todo.md list, you must arrange tasks in a logical causal chain (DAG \- Directed Acyclic Graph).

### **5.1. Sequence Patterns**

1. **Foundations First:** Data models, DB connections, configs.  
2. **Logic Core:** Processing functions, business rules.  
3. **Interface Layer:** API endpoints, CLI commands (using the logic).  
4. **Final Product (Release):** Integration tests and documentation.

### **5.2. The Release Task**

According to requirements, the last task must constitute the "Final Product". It must be an integration or verification task for the whole set.

* Example:  
  \- \[ \] \*\*\[REL-1.0\]\*\* Perform Integration Test of full CLI workflow & Update Documentation.  
  * *Action:* Run full suite pytest.  
  * *Action:* Verify CLI binary build via pyinstaller.  
  * *Action:* Update README.md with usage instructions.

## **6\. LONG-TERM MEMORY INTEGRATION RULES**

The Planning Agent must foresee moments when the Coding Agent must update .ai/MEMORY.md.

* **Trigger Rule:** If you design a task that changes DB Schema, API, or adds a library – you **MUST** add a memory update instruction to the task payload.  
* **Example:**  
  \- \[ \] \*\*\[DB-02\]\*\* Alter \`Users\` table schema to add \`mfa\_token\`.  
      \* \*Action:\* Create Alembic migration.  
      \* \*Post-Condition:\* Append ADR entry to \`.ai/MEMORY.md\` documenting the schema change.

## **7\. TODO LIST VALIDATION (PLANNING AGENT'S CHECKLIST)**

Before approving todo.md for the Coding Agent, verify:

1. \[ \] **Consistency:** Do all files mentioned in tasks exist or are scheduled for creation?  
2. \[ \] **Atomicity:** Is any task too big ("do entire backend")? If yes \-\> **BREAK IT DOWN**.  
3. \[ \] **Verifiability:** Does every task have a success condition (test/log)?  
4. \[ \] **Safety:** Do tasks suggest violating .ai/STANDARDS.md (e.g., deleting tests)?  
5. \[ \] **Closure:** Does completing the last task mean the business goal from Section 0 is achieved?

## **8\. TROUBLESHOOTING (INTERVENTION PROTOCOL)**

As the Planning Agent or Human Supervisor overseeing the Coding Agent:

1. **Symptom:** Coding Agent loops on the same task (Fail \-\> Fix \-\> Fail \-\> Fix) more than 3 times.  
2. **Intervention:**  
   * **STOP** the Coding Agent.  
   * **EDIT** todo.md:  
     * Split the stuck task into two smaller tasks.  
     * Add a specific hint to the \* Constraint field (e.g., "Hint: The error is caused by circular import in module X").  
   * **RESTART** the Coding Agent.