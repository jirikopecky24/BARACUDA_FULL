# AGENT BARAKUDA WORKFLOW NOTE

## 0. CURRENT PHASE OVERRIDE — AFM HYDROGEL POROSITY / ROI EXPLORER
- previous phase (AFM-A1v profile/mask intersection QA) is **completed**
  - implemented in commit `d684a35 afm-ui: add profile mask intersection QA`
  - file: `barakuda/devices/afm/ui/roi_explorer.py`
  - docs updated: `docs/agent_tasks/AFM_ROI_EXPLORER_DESIGN_NOTE.md`, `docs/agent_tasks/AFM_HYDROGEL_POROSITY_BIBLE.md`, `AGENT_BARAKUDA_WORKFLOW_NOTE.md`
- current phase (AFM-A1w candidate mask QA audit design) is **completed**
  - design document: `docs/agent_tasks/AFM_CANDIDATE_MASK_QA_AUDIT_DESIGN.md`
  - docs updated: `docs/agent_tasks/AFM_HYDROGEL_POROSITY_BIBLE.md`, `AGENT_BARAKUDA_WORKFLOW_NOTE.md`
  - no implementation, no UI buttons, no JSON outputs, no metrics
- current state: AFM ROI Explorer is visualization/QA only
  - loads validated `.npy` ROI arrays
  - shows 2D image with draggable horizontal/vertical profile cut line
  - displays exploratory in-memory depression mask overlay with opacity slider
  - shows visual profile/mask intersection bands in the profile plot
  - profile index ranges are derived from the active image shape; no hard-coded ROI dimensions
  - profiles plotted in physical µm/nm units
  - no segmentation, no porosity, no pore metrics, no roughness, no final channel selection, no final segmentation method
- no production code changes unless explicitly requested
- no AFM analysis, segmentation, porosity, pore metrics, or roughness computation
- masks are generated in memory only; no masks are saved
- no connected-component labeling or regionprops
- current next candidate work requires explicit user approval:
  1. AFM-A1x: implement QA audit JSON save for viewer state only, still no metrics, or
  2. QA snapshot/export design, still no scientific outputs, or
  3. raw `.jpk-qi-data` loading future work, or
  4. CP01 follow-up (timing audit / batch summary hardening / packaging)
- raw `.jpk-qi-data` loading remains future work
- one phase only (strict phase separation; do not do next-phase work early)
- stop after report and wait for explicit approval before continuing
- no proceeding without explicit approval
- quality and trustworthiness have priority over speed
- keep changes minimal, explicit, reviewable, and reversible

## 1. PROJECT MODE
- BARAKUDA is deterministic scientific software
- same input + same config + same version = same output
- no AI-computed physics
- protect reproducibility and auditability

## 2. BRANCH MODEL
- `main` must remain the stable branch
- `main` is now treated as frozen baseline (clean, stable, English user-facing)
- no new feature work should be committed directly on `main`
- `staging/barakuda-next` is the current integration/testing branch
- new feature/fix branches should branch from staging unless explicitly told otherwise
- merge to `main` only after human verification
- never merge automatically

## 3. EXECUTION RULES
- one step only
- one commit only
- allowed files only
- STOP after commit
- no broad refactors
- no "also changed"
- if another file is needed -> STOP and report it

## 3.0 AUDIT/HARDENING MODE
- During each hardening phase: prefer fail-loud for the specific risk class.
- Do not proceed to the next phase without explicit approval.
- Any edits must be minimal, isolated to the specific propagation mismatch for that phase, and accompanied by targeted verification.

## 3.1. AUTHORITATIVE RUNTIME ENVIRONMENT
- The canonical BARAKUDA Python environment is `C:/Users/jirik/anaconda3/envs/barakuda/python.exe`
- All pip installs, smoke tests, and application launches must target this interpreter
- Do not assume shell context matches app runtime; always verify against this env when diagnosing dependencies

## 4. CURRENT WORKFLOW DECISIONS
- RUN is the primary output mechanism
- for Optical Tweezers, new non-dataset runs are moving toward using a selected Output Root
- dataset-mode must continue writing into the existing dataset unless explicitly changed later
- the dataset/run folder is the canonical output package
- Export is no longer the intended primary output model
- OT Export UI/workflow is being phased out / removed
- Preview Gate report should ultimately live at batch root, not inside each individual run folder
- new OT layout direction is `preview/`, `pipeline/`, `summary/`, `qc/` instead of legacy clutter

## 5. CURRENT VERIFIED OT STATE
- Output Root selector exists in OT Run UI
- manifest supports `pipeline/` and legacy `ot_v2_shadow/`
- new OT writes should use `pipeline/`
- result summaries should go to `summary/`
- QC image should go to `qc/`
- preview report is resolvable from `preview/preview_report.json`
- old datasets should remain readable

## 6. HOW TO HANDLE NEW TASKS
- first decide whether the task is:
  - docs/spec
  - diagnostic
  - minimal runtime fix
  - integration verification
  - merge review
- if uncertain, do docs/spec or diagnostic first
- for risky changes, do compatibility/read path before writer/path migration
- do not combine unrelated fixes

## 7. PATCH CORRIDOR POLICY
- always declare allowed files
- everything else is forbidden
- if the requested corridor conflicts with actual code locations, STOP and report the correct file before editing

## 8. BARAKUDA STORAGE POLICY
- canonical outputs belong in the run/dataset folder
- do not create duplicate internal exports inside the same dataset unless explicitly required
- avoid redundant outputs and legacy duplicates
- prefer one canonical location per logical result
- preserve old dataset compatibility when changing new write locations

## 9. MERGE POLICY
- after a branch is functionally complete, do verification doc first
- then merge-review doc
- then human review/testing
- only then merge to `main`

## 10. AFM ROD BACTERIA - KNOWN ISSUES / BACKLOG

Následující problémy byly identifikovány a čekají na opravu:

### 10.1. Vzhled panelu
- AFM panel stále nevypadá úplně jako OT panel
- Problém: `_make_card()` funkce používala CSS selektor `QFrame {...}` který se propagoval na vnitřní widgety (SpinBox, ComboBox)
- Částečně opraveno (OT-style přístup bez fancy karet), ale vizuální konzistence s OT není 100%

### 10.2. Progress bar při analýze
- Progress bar se zasekává na 79% během AFM batch analýzy
- V terminálu se vypisuje průběh správně, ale UI progress bar se neaktualizuje
- Příčina: pravděpodobně chybí signál/slot propojení mezi worker a UI pro progress update během batch běhu
- Soubory k prověření:
  - `barakuda/shell/workers/afm_run_worker.py`
  - `barakuda/shell/main_window.py` (AFM batch progress handling)
  - `barakuda/devices/afm/device.py` (pb_preview widget)

### 10.3. Budoucí práce
- Až se vrátíme k AFM Rod Bacteria, opravit tyto issues před dalším rozšiřováním
- Reference pro OT-style UI: `barakuda/devices/optical_tweezers/ui/panel.py`

## 11. HOW FUTURE PROMPTS SHOULD REFERENCE THIS NOTE
- read `AGENT_BARAKUDA_WORKFLOW_NOTE.md` first
- follow it unless the current prompt explicitly overrides a point
