# BARAKUDA AFM Hydrogel Porosity Bible

**Repository target path:** `docs/agent\_tasks/AFM\_HYDROGEL\_POROSITY\_BIBLE.md`  
**Status:** canonical planning/specification document for the BARAKUDA AFM hydrogel direction  
**Created:** 2026-05-27  
**Scope:** AFM analysis, hydrogel porosity, JPK/QI data, height-map based morphology, future force-curve mechanics  
**Out of current scope:** bacteria workflow, optical tweezers workflow, acquisition hardware changes

\---

## 0\. Purpose of this document

This document is the project reference for the new BARAKUDA AFM hydrogel analysis direction.

It exists so that future agents and developers do **not** improvise, duplicate existing tools, silently change scientific assumptions, or invent unsupported metrics. Every implementation step must be traceable back to this document or to a later dated update appended here.

The strategic goal is:

```text
AFM data -> validated height/mechanics extraction -> hydrogel pore analysis -> audit trail -> tables -> figures -> report -> batch summary
```

BARAKUDA's value is not to rewrite every scientific library from scratch. BARAKUDA's value is to integrate existing validated scientific tools into a controlled, reproducible, auditable workflow that produces usable outputs for real AFM hydrogel experiments.

\---

## 1\. Non-negotiable scientific rules

### 1.1 No invented science

Agents must not invent formulas, thresholds, material parameters, calibration values, or physical interpretations.

A metric may be implemented only if one of the following is true:

1. It follows directly from geometry, image measurement, statistics, or linear algebra and the equation is written in this document.
2. It is provided by a validated external scientific library and the library/function is recorded in the audit output.
3. It is a named physical model from literature/software documentation and all assumptions are explicitly recorded.

### 1.2 Raw data first

The workflow must always start from the loaded raw AFM data and metadata. Derived outputs must be produced step-by-step by recorded deterministic processing operations.

No workflow may start from a screenshot, manually adjusted exported image, or unknown preprocessed view unless the output is clearly marked as non-canonical / exploratory.

### 1.3 Every number must be traceable

Every reported number must be traceable to:

* source file path/hash,
* loader used,
* selected channel,
* raw shape,
* physical pixel scale,
* preprocessing parameters,
* segmentation method,
* filtering rules,
* equation/function used,
* software/library versions,
* CPU/GPU backend.

### 1.4 Units are mandatory

Every physical measurement must carry units.

Examples:

* pixel count: `px`
* pixel area: `px^2`
* physical length: `um`
* physical area: `um^2`
* height: preferably `nm` or `um`, but unit must come from metadata or user-confirmed calibration
* roughness: same unit as height

If height units are unknown, height-derived physical metrics must be marked as `unit\_unknown` and excluded from final scientific report unless user explicitly approves exploratory output.

### 1.5 Calibration must not be guessed

The lateral pixel size must come from data metadata, acquisition manifest, or explicit user input.

If lateral scale is missing:

* BARAKUDA may compute pixel-only metrics,
* BARAKUDA must not report physical pore sizes in µm,
* the report must fail or clearly mark the result as not physically calibrated.

### 1.6 Height topography cannot produce viscosity

From a static AFM height map alone BARAKUDA must not report:

* viscosity,
* storage modulus,
* loss modulus,
* bulk permeability,
* bulk diffusivity,
* true 3D hydrogel porosity,
* hydrogel mesh size.

These require additional measurements, models, or assumptions. They are not valid outputs of a 2D topography-only workflow.

### 1.7 AFM surface pores are not automatically bulk pores

AFM height maps describe a surface-accessible topography. Pores detected from a 2D AFM topography are **surface-visible pore-like depressions/regions**, not automatically the full 3D hydrogel pore network.

Reports must use careful language:

```text
surface-visible pore descriptors
surface pore fraction
2D pore size distribution from AFM topography
```

Do not call this automatically:

```text
bulk porosity
mesh size
permeability
diffusion coefficient
```

unless a separate validated model and data source exist.

\---

## 2\. BARAKUDA development rules for this AFM direction

These rules follow the existing BARAKUDA agent principles.

### 2.1 Narrow tasks only

One task = one narrow goal.

Do not combine:

* JPK loader implementation,
* hydrogel segmentation,
* GPU backend,
* UI redesign,
* PDF report,
* mechanics models,
* refactor of batch controller,

into a single task.

### 2.2 Five-file stop rule

If a change requires editing more than five files, the agent must stop and request explicit approval.

### 2.3 Prefer diagnostics before risky implementation

Before implementing a parser or scientific metric, write a diagnostic/check script or test that demonstrates what the raw data contains and what metadata are available.

### 2.4 Do not rewrite existing working systems

The current optical tweezers modules, drag/Brownian analysis, timing truth, report consistency logic, and acquisition hardware layers are not part of this task.

### 2.5 Do not make AFM bacteria the focus

The bacteria workflow is not the current priority. It may remain in the UI/codebase, but current development focus is:

```text
AFM -> hydrogels -> porosity/morphology -> audit/report/export
```

### 2.6 Add dated updates here

Do not create a new planning document for every small AFM decision. Append dated updates to this file unless a separate document is explicitly needed.

Recommended format:

```markdown
## Update YYYY-MM-DD — short title

- Decision:
- Reason:
- Files affected:
- Validation:
```

\---

## 3\. Existing libraries/tools to use before writing custom code

BARAKUDA should integrate proven libraries instead of reimplementing them unless there is a measured reason not to.

### 3.1 AFM/JPK data loading candidates

|Tool|Use in BARAKUDA|Notes|License status to audit|
|-|-|-|-|
|`afmformats`|Preferred first candidate for `.jpk-qi-data`, JPK force maps, QI data, and force-distance oriented data|It is a base module for loading AFM data and has documented JPK/QI support.|MIT according to GitHub|
|`AFMReader`|Candidate for AFM image/topography formats, including `.spm`, `.gwy`, `.jpk`, `.jpk-qi-image`|Useful especially if `.jpk-qi-data` contains `data-image.jpk-qi-image`.|PyPI reports LGPLv3; GitHub/plugin pages mention GPL/LGPL family. Must audit before bundling.|
|`TopoStats`|Reference/inspiration for AFM preprocessing and flattening workflows|Do not copy code casually because GPL/LGPL licensing must be reviewed.|GPL/LGPL according to GitHub|
|Custom BARAKUDA loader|Allowed only as a thin adapter or fallback|Must not silently invent binary layout; must be validated against metadata and test data.|BARAKUDA internal|

Implementation principle:

```text
External reader -> BARAKUDA canonical AFM data object -> method pipeline -> export/audit/report
```

The external reader should not leak uncontrolled data structures into the rest of BARAKUDA.

### 3.2 Image analysis and pore-analysis candidates

|Tool|Use in BARAKUDA|
|-|-|
|`numpy`|Canonical numerical array operations|
|`scipy.ndimage`|Filters, morphology, exact Euclidean distance transform|
|`scikit-image`|Thresholding, labeling, watershed, regionprops, measurements|
|`PoreSpy`|Pore-specific metrics, local thickness, pore size distribution, porous-media analysis|
|`pandas`|Tables, CSV/XLSX-ready data frames|
|`matplotlib`|Figures, histograms, 3D surface visualizations for reports|

### 3.3 GPU and memory candidates

|Tool|Use in BARAKUDA|
|-|-|
|`CuPy`|CUDA/ROCm-compatible NumPy/SciPy-like GPU array backend where available|
|`cuCIM`|GPU-accelerated n-dimensional image processing, useful for scikit-image-like operations|
|`pyclesperanto`|Optional OpenCL/CUDA/Metal image-processing backend after evaluation|
|`Dask Array`|Chunked computation for arrays larger than memory|
|`Zarr`|Chunked/compressed internal cache for height maps, masks, mechanics maps, force-derived data|
|`numpy.memmap`|Simple RAM-safe storage for large intermediate arrays|

### 3.4 Dependency policy

Dependencies must be categorized:

```text
required: needed for AFM module to run at all
optional: used if installed, with fallback
experimental: not used in production output unless enabled explicitly
reference-only: may guide design, but do not import/copy code
```

Initial recommended categorization:

```text
required: numpy, scipy, scikit-image, pandas, matplotlib
optional: afmformats, AFMReader, porespy, openpyxl/report tooling already used by BARAKUDA
experimental: cupy, cucim, pyclesperanto, dask, zarr
reference-only: TopoStats internals unless license is approved
```

\---

## 4\. Canonical AFM data object

All loaders should return a common object or equivalent dictionary with these fields.

```python
AfmLoadedData = {
    "height": np.ndarray,             # 2D height/topography image
    "height\_unit": str | None,        # e.g. "nm", "um", "m"; None if unknown
    "um\_per\_px\_x": float | None,
    "um\_per\_px\_y": float | None,
    "selected\_channel": str,
    "available\_channels": list\[str],
    "source\_path": str,
    "source\_format": str,
    "loader": str,
    "loader\_version": str | None,
    "metadata\_raw": dict,
    "metadata\_normalized": dict,
    "warnings": list\[str],
}
```

Rules:

* `height` must be 2D.
* If input is multi-channel, selected channel must be recorded.
* If pixel size differs in X and Y, both must be preserved.
* If code needs a scalar scale, use only when `um\_per\_px\_x == um\_per\_px\_y` within tolerance; otherwise use anisotropic formulas.
* Do not transpose/flip/rotate data without recording the operation.

\---

## 5\. JPK/QI input strategy

### 5.1 Current target formats

The AFM module should ultimately accept:

```text
.spm
.jpk-qi-data
.jpk-qi-image
.jpk
.gwy
.tif/.tiff
.png/.jpg/.bmp for calibrated exploratory or exported images
```

Priority now:

```text
1. .jpk-qi-data
2. .jpk-qi-image
3. existing .spm behavior must remain working
```

### 5.2 JPK/QI loading order

For `.jpk-qi-data`, attempt in this order:

1. `afmformats` direct load, if it can produce height/topography and metadata reliably.
2. Extract/find internal `data-image.jpk-qi-image` and load with `AFMReader`, if available and license/dependency status is accepted.
3. BARAKUDA custom fallback only after diagnostic validation of metadata and binary layout.

### 5.3 Large archive rule

Never blindly list/process millions of ZIP entries unless necessary.

The loader should read only:

```text
header.properties
shared metadata needed for calibration
image/topography data object
selected force curves only when mechanics mode is explicitly requested
```

A `.jpk-qi-data` file may contain a force-distance curve for each pixel. The topography-only porosity pipeline must not load all force curves into RAM.

### 5.4 Required JPK diagnostics before production support

For every new JPK reader path, add a diagnostic function that reports:

* archive/file structure summary,
* top-level metadata keys,
* detected scan size,
* detected pixel dimensions,
* available channels,
* selected channel,
* raw dtype,
* height unit,
* lateral units,
* missing metadata warnings,
* estimated memory use,
* time to load height map.

No production JPK support should be merged until this diagnostic produces a saved JSON audit artifact.

\---

## 6\. Canonical height-map preprocessing

Input:

```text
Z\_raw\[j, i]
```

where `i` indexes X columns and `j` indexes Y rows.

### 6.1 NaN/invalid handling

Let valid pixel mask be:

```text
M\_valid\[j, i] = isfinite(Z\_raw\[j, i])
```

Invalid pixels must be counted and recorded.

Allowed handling:

* preserve NaNs and ignore in statistics,
* interpolate only for visualization/segmentation if explicitly recorded,
* fail if invalid fraction exceeds configured limit.

### 6.2 Unit conversion

If height metadata is in meters:

```text
Z\_nm = Z\_m \* 1e9
Z\_um = Z\_m \* 1e6
```

If height unit is unknown, do not report physical height roughness.

### 6.3 Lateral coordinates

For isotropic pixels:

```text
s = scan\_size\_um / n\_pixels
x\_i = i \* s
y\_j = j \* s
A\_px = s^2
```

For anisotropic pixels:

```text
x\_i = i \* s\_x
y\_j = j \* s\_y
A\_px = s\_x \* s\_y
```

### 6.4 Plane leveling

Plane leveling removes scanner/sample tilt from the height map by fitting a plane to valid pixels.

Model:

```text
z\_hat(x, y) = a\*x + b\*y + c
```

Least-squares objective:

```text
min\_{a,b,c} sum\_{(i,j) in valid/background} \[Z\_raw\[j,i] - (a\*x\_i + b\*y\_j + c)]^2
```

Leveled image:

```text
Z\_level\[j,i] = Z\_raw\[j,i] - z\_hat(x\_i, y\_j)
```

Audit must record:

* whether leveling was applied,
* whether all pixels or background mask were used,
* coefficients `a`, `b`, `c`,
* residual statistics.

### 6.5 Row/line flattening

Line flattening may be used to reduce line artifacts, but it can distort real structures. It must be optional and audited.

For each scan line `j`, fit polynomial:

```text
p\_j(x) = sum\_{k=0}^{d} beta\_{j,k} x^k
```

Then:

```text
Z\_flat\[j,i] = Z\_level\[j,i] - p\_j(x\_i)
```

Audit must record:

* polynomial degree `d`,
* whether object/pore masks were excluded from fitting,
* number of lines processed,
* whether any lines failed.

### 6.6 Filtering/smoothing

Any smoothing must be recorded as a preprocessing operation.

Allowed examples:

* Gaussian filter with sigma in pixels/µm,
* median filter with footprint size,
* morphological opening/closing with structuring element.

No smoothing is allowed without storing parameters in audit.

\---

## 7\. Definition of a pore for Phase 1

For Phase 1, BARAKUDA defines a pore operationally as a connected surface-visible region in the AFM height map that satisfies a recorded segmentation rule and passes recorded size/shape filters.

A pore is not claimed to be the true 3D hydrogel mesh or bulk pore unless validated by additional data.

Canonical language:

```text
Detected pore-like depressions in AFM topography
```

or

```text
surface-visible pore regions
```

\---

## 8\. Segmentation strategy for hydrogel porosity

The segmentation must be reproducible. The selected method and all parameters must be saved.

### 8.1 Pore polarity

For topography, pores are usually height depressions. If using a threshold on height:

```text
pore\_candidate\[j,i] = Z\_pre\[j,i] <= T
```

If the image convention is inverted, the polarity must be explicitly set and saved:

```text
pore\_candidate\[j,i] = Z\_pre\[j,i] >= T
```

The code must not silently guess pore polarity for final output.

### 8.2 Otsu threshold option

Otsu thresholding may be offered as a reproducible automatic threshold option.

It selects a threshold that maximizes between-class variance or equivalently minimizes within-class variance.

Given histogram class probabilities `w0(t)`, `w1(t)` and class means `mu0(t)`, `mu1(t)`:

```text
sigma\_b^2(t) = w0(t) \* w1(t) \* \[mu0(t) - mu1(t)]^2
T\_otsu = argmax\_t sigma\_b^2(t)
```

For pore depressions:

```text
mask = Z\_pre <= T\_otsu
```

Audit must record:

* method = `otsu`,
* threshold value,
* histogram bin count,
* polarity,
* preprocessing before thresholding.

### 8.3 Manual or fixed threshold option

Manual threshold is allowed only if:

* value is explicitly provided,
* unit is recorded,
* reason/source is recorded,
* output is marked as user-thresholded.

### 8.4 Percentile threshold option

Percentile thresholding is allowed only as exploratory or user-defined mode unless validated for a dataset.

Example:

```text
T\_p = percentile(Z\_pre, p)
mask = Z\_pre <= T\_p
```

Audit must state that `p` was user-selected or protocol-selected.

### 8.5 Distance-transform separation

If adjacent pores merge, use a distance-transform based watershed.

For binary pore mask `B`, the exact Euclidean distance transform is:

```text
D\[j,i] = min distance from pixel (j,i) to background pixel
```

where distance must include pixel spacing if anisotropic.

Watershed separation can use:

```text
markers = local maxima of D
labels = watershed(-D, markers, mask=B)
```

Audit must record:

* distance transform backend,
* marker detection parameters,
* watershed connectivity,
* number of objects before and after split.

### 8.6 Connected-component labeling

After segmentation:

```text
L = label(mask, connectivity)
```

Each nonzero integer in `L` is one detected pore candidate.

Audit must record connectivity:

* 2D 4-connectivity,
* or 2D 8-connectivity.

### 8.7 Filtering rules

Objects may be filtered by:

* minimum area in px² or µm²,
* maximum area,
* border touching,
* circularity range,
* aspect ratio range,
* depth contrast threshold,
* invalid/NaN overlap.

Every rejected object must be countable by rejection reason.

\---

## 9\. Pore geometry equations

For each labeled pore region `R\_k` with pixel set `P\_k`.

### 9.1 Pixel count

```text
N\_k = number of pixels in P\_k
```

### 9.2 Physical area

Isotropic pixels:

```text
A\_k = N\_k \* s^2
```

Anisotropic pixels:

```text
A\_k = N\_k \* s\_x \* s\_y
```

Units: `um^2`.

### 9.3 Equivalent circular diameter

Equivalent diameter is the diameter of a circle with the same area:

```text
d\_eq,k = sqrt(4 \* A\_k / pi)
```

Units: `um`.

### 9.4 Perimeter

Perimeter should come from a consistent image measurement method, for example `skimage.measure.regionprops` / `perimeter` or Crofton perimeter if chosen.

Audit must record which perimeter estimator was used.

### 9.5 Circularity

```text
C\_k = 4\*pi\*A\_k / P\_k^2
```

where `P\_k` is perimeter in the same physical length unit as area.

Notes:

* ideal circle approaches 1,
* irregular or elongated shapes are lower,
* noisy boundaries can strongly affect this metric.

### 9.6 Major/minor axis lengths

Use a documented region property method. In `skimage.measure.regionprops`, major/minor axes are obtained from the ellipse with the same normalized second central moments as the region.

Record:

```text
major\_axis\_length\_um
minor\_axis\_length\_um
```

### 9.7 Aspect ratio

```text
AR\_k = major\_axis\_length\_k / minor\_axis\_length\_k
```

If minor axis is zero or invalid, mark `AR\_k = NaN` and record warning.

### 9.8 Centroid

Pixel centroid:

```text
x\_c,px = mean(i for pixels in P\_k)
y\_c,px = mean(j for pixels in P\_k)
```

Physical centroid:

```text
x\_c,um = x\_c,px \* s\_x
y\_c,um = y\_c,px \* s\_y
```

### 9.9 Feret diameter

Feret diameter may be included if provided by the measurement library or implemented from convex hull geometry.

Do not implement a custom Feret metric without tests against known shapes.

### 9.10 Depth metrics

For a pore region `R\_k`, depth-like metrics may be computed from preprocessed height values.

Let local reference height be defined explicitly, for example:

```text
z\_ref,k = median height in a dilation ring around R\_k
```

Then:

```text
mean\_depth\_k = z\_ref,k - mean(Z\_pre\[pixels in R\_k])
max\_depth\_k  = z\_ref,k - min(Z\_pre\[pixels in R\_k])
```

These metrics are valid only if height unit is known and polarity is correct.

Audit must record:

* reference ring width,
* height unit,
* polarity,
* whether depth is measured relative to global or local reference.

\---

## 10\. Pore population metrics

Let:

```text
N = number of accepted pores
A\_ROI = physical area of analyzed ROI
A\_pores = sum\_k A\_k
```

### 10.1 Pore count

```text
N\_pores = N
```

### 10.2 Pore number density

```text
rho\_pores = N / A\_ROI
```

Units: `pores / um^2`.

### 10.3 Surface pore area fraction

```text
phi\_area = A\_pores / A\_ROI
```

Often reported as percent:

```text
phi\_area\_percent = 100 \* phi\_area
```

Important: call this `surface pore area fraction`, not bulk porosity.

### 10.4 Pore size distribution from equivalent diameters

Use `d\_eq,k` values and report:

* mean,
* median,
* standard deviation,
* min/max,
* percentiles P10/P25/P75/P90,
* histogram bin edges and counts.

### 10.5 Size-class fractions

If size classes are defined, store them explicitly.

Example:

```text
small:  d\_eq < 0.1 um
medium: 0.1 <= d\_eq < 0.5 um
large:  d\_eq >= 0.5 um
```

These boundaries must be user/protocol-defined and audited. Do not hard-code them as universal hydrogel truth.

For each class:

```text
count\_fraction\_class = N\_class / N\_total
area\_fraction\_class  = sum(A\_k in class) / A\_pores
roi\_area\_fraction\_class = sum(A\_k in class) / A\_ROI
```

### 10.6 Nearest-neighbor distance

For pore centroids:

```text
nnd\_k = min\_{m != k} sqrt((x\_k - x\_m)^2 + (y\_k - y\_m)^2)
```

Report distribution only when `N >= 2`.

\---

## 11\. Roughness/topography metrics

Roughness metrics are calculated on a selected surface `Z`, usually preprocessed/leveled height map over ROI or background.

The report must state which surface was used:

```text
raw
leveled
flattened
masked background
full ROI
```

Let `z\_i` be valid height values after chosen preprocessing and let:

```text
z\_mean = mean(z\_i)
q\_i = z\_i - z\_mean
n = number of valid pixels
```

### 11.1 Arithmetic mean height / average roughness

For areal surface, use `Sa` terminology where appropriate:

```text
Sa = (1/n) \* sum\_i |q\_i|
```

For a line profile, analogous parameter is `Ra`.

### 11.2 Root mean square height

For areal surface:

```text
Sq = sqrt((1/n) \* sum\_i q\_i^2)
```

For a line profile, analogous parameter is `Rq`.

### 11.3 Skewness

```text
Ssk = (1 / (n \* Sq^3)) \* sum\_i q\_i^3
```

### 11.4 Kurtosis

```text
Sku = (1 / (n \* Sq^4)) \* sum\_i q\_i^4
```

If `Sq == 0`, skewness and kurtosis must be NaN with warning.

### 11.5 Maximum peak/pit/range

```text
Sp = max(q\_i)
Sv = abs(min(q\_i))
Sz = Sp + Sv
```

### 11.6 Roughness caution

Leveling, filtering, masking, and line correction can change roughness values. Reports must not compare roughness across samples unless preprocessing protocol is identical.

\---

## 12\. PoreSpy/local thickness option

PoreSpy can be used for local-thickness based pore-size distribution.

Conceptually, local thickness assigns to pore-space pixels the radius/diameter of the largest circle in 2D, or sphere in 3D, that fits within the pore space and overlaps that pixel.

For BARAKUDA Phase 1 on 2D AFM masks:

```text
input = binary pore mask
output = local thickness image over pore pixels
summary = pore size distribution from local thickness
```

Important:

* This is a 2D pore-space descriptor unless the input is truly 3D.
* Record whether output is radius or diameter according to the PoreSpy function used.
* Do not mix object-equivalent diameter distribution and local-thickness distribution without labeling them separately.

Recommended report naming:

```text
PSD\_object\_equivalent\_diameter
PSD\_local\_thickness\_2D
```

\---

## 13\. 3D surface map

A 3D surface map is a visualization/audit artifact, not a new physical analysis.

Coordinates:

```text
X\[j,i] = i \* s\_x
Y\[j,i] = j \* s\_y
Z\[j,i] = height\[j,i]
```

Allowed outputs:

* `surface\_3d.png`
* `surface\_3d\_with\_pores.png`
* optional interactive HTML only if dependency is approved

Audit must record:

* source height map used,
* z unit,
* whether z scaling was exaggerated,
* colormap,
* view angle,
* whether pore overlay was displayed.

Do not infer volume, viscosity, or bulk network structure from this plot.

\---

## 14\. Future QI mechanics module — not Phase 1

JPK QI data may contain force-distance curves at many pixels. These can potentially support mechanical property maps, but this must be a separate module with its own validation.

Potential future module name:

```text
hydrogel\_qi\_mechanics
```

### 14.1 Mechanics prerequisites

Do not compute Young's modulus/stiffness unless the following are known or explicitly provided:

* force curve data,
* deflection sensitivity,
* spring constant,
* tip geometry,
* tip radius or cone half-angle,
* Poisson ratio assumption,
* contact point method,
* indentation calculation,
* model selection,
* fitting interval,
* sample/substrate assumptions.

### 14.2 Force conversion

If deflection `d` and cantilever spring constant `k` are known:

```text
F = k \* d
```

Units must be consistent.

### 14.3 Indentation

A typical indentation calculation requires piezo/sample displacement and cantilever deflection. Exact sign convention depends on source metadata and must be validated per loader.

Generic form:

```text
indentation = z\_displacement - deflection - contact\_offset
```

Do not implement without confirming sign conventions from the reader/source.

### 14.4 Hertz spherical indenter model

For a spherical indenter under ideal elastic half-space assumptions:

```text
F = (4/3) \* E\_eff \* sqrt(R) \* delta^(3/2)
```

where:

```text
E\_eff = E / (1 - nu^2)
```

So:

```text
F = (4/3) \* \[E / (1 - nu^2)] \* sqrt(R) \* delta^(3/2)
```

Do not use if assumptions are violated without warning.

### 14.5 Sneddon conical indenter model

For a conical indenter under ideal assumptions:

```text
F = \[2 \* E \* tan(alpha) / (pi \* (1 - nu^2))] \* delta^2
```

where:

* `alpha` = cone half-angle,
* `nu` = Poisson ratio,
* `delta` = indentation.

### 14.6 Mechanics output naming

Do not call outputs `viscosity` unless a time-dependent viscoelastic model is implemented and validated.

Preferred future names:

```text
apparent\_stiffness\_map
apparent\_young\_modulus\_map
adhesion\_map
dissipation\_proxy\_map
```

Every map must include model and assumptions in metadata.

\---

## 15\. GPU/RAM architecture

### 15.1 Compute profiles

AFM hydrogel pipeline should eventually support:

```text
auto
cpu
gpu\_cuda
experimental\_opencl
```

Behavior:

* `cpu`: NumPy/SciPy/scikit-image path only.
* `gpu\_cuda`: CuPy/cuCIM where functions are available; fall back only with warning.
* `auto`: use GPU only if runtime is available and validated.
* `experimental\_opencl`: disabled by default.

### 15.2 Reproducibility across CPU/GPU

GPU and CPU outputs may differ slightly because of numerical precision and algorithm implementation. Tests must define tolerances.

For segmentation, compare:

* mask IoU,
* pore count tolerance,
* summary metric tolerance,
* exact equality only where deterministic integer operations are expected.

### 15.3 Memory policy

Do not load full JPK force-curve maps into memory for height-only porosity analysis.

Large data strategy:

* height map: normal NumPy array is acceptable for 512x512/1024x1024 images,
* large stacks/maps: Zarr or memmap,
* larger-than-RAM computations: Dask Array,
* cache heavy derived data in `analysis/cache/` with provenance.

### 15.4 GPU audit fields

Record:

```json
{
  "compute\_profile\_requested": "auto",
  "compute\_profile\_resolved": "cpu|gpu\_cuda",
  "gpu\_available": true,
  "gpu\_name": "...",
  "cupy\_version": "...",
  "cucim\_version": "...",
  "fallback\_applied": false,
  "fallback\_reason": ""
}
```

\---

## 16\. Hydrogel Porosity v1 pipeline

### 16.1 Pipeline overview

```text
input file(s)
  -> resolve AFM input
  -> load canonical height map + metadata
  -> validate units/calibration
  -> choose ROI
  -> preprocess height map
  -> segment pore candidates
  -> label pores
  -> filter pore objects
  -> compute pore metrics
  -> compute roughness/topography metrics
  -> generate figures
  -> write per-item outputs
  -> write audit JSON
  -> write batch summary/report
```

### 16.2 Required per-item outputs

```text
analysis/
  afm\_loaded\_metadata.json
  afm\_audit.json
  height\_raw.npy or height\_raw.zarr
  height\_preprocessed.npy or height\_preprocessed.zarr
  pore\_mask.png
  pore\_labels.tif
  pore\_overlay.png
  pore\_size\_histogram.png
  pore\_size\_classes.png optional
  surface\_3d.png
  pore\_table.csv
  pore\_summary.json
  report.pdf optional in first task; required eventually
```

### 16.3 Required batch outputs

```text
batch\_summary.csv
batch\_summary.xlsx
batch\_audit.json
batch\_report.pdf optional in first task; required eventually
```

### 16.4 Pore table columns

Minimum required columns:

```text
source\_file
item\_id
pore\_id
area\_px2
area\_um2
equivalent\_diameter\_um
perimeter\_um
circularity
major\_axis\_length\_um
minor\_axis\_length\_um
aspect\_ratio
centroid\_x\_px
centroid\_y\_px
centroid\_x\_um
centroid\_y\_um
bbox\_min\_row
bbox\_min\_col
bbox\_max\_row
bbox\_max\_col
mean\_height
min\_height
max\_height
mean\_depth
max\_depth
size\_class
filter\_status
filter\_reason
```

Columns requiring known height unit should be blank/NaN if height unit is unknown.

### 16.5 Summary JSON fields

```json
{
  "schema\_version": 1,
  "module": "afm",
  "method\_id": "hydrogel\_porosity",
  "source\_file": "...",
  "selected\_channel": "...",
  "roi": \[0, 0, 512, 512],
  "shape": \[512, 512],
  "um\_per\_px\_x": 0.01953125,
  "um\_per\_px\_y": 0.01953125,
  "height\_unit": "nm",
  "n\_pores\_raw": 0,
  "n\_pores\_accepted": 0,
  "surface\_pore\_area\_fraction": 0.0,
  "pore\_density\_per\_um2": 0.0,
  "equivalent\_diameter\_um": {
    "mean": null,
    "median": null,
    "std": null,
    "p10": null,
    "p25": null,
    "p75": null,
    "p90": null
  },
  "roughness": {
    "surface\_used": "leveled\_full\_roi",
    "Sa": null,
    "Sq": null,
    "Ssk": null,
    "Sku": null,
    "Sp": null,
    "Sv": null,
    "Sz": null
  },
  "warnings": \[]
}
```

\---

## 17\. Audit JSON requirements

Every run must write an audit JSON.

Minimum structure:

```json
{
  "schema\_version": 1,
  "created\_at": "ISO-8601",
  "barakuda\_version": "...",
  "method\_id": "hydrogel\_porosity",
  "source": {
    "path": "...",
    "sha256": "...",
    "format": "jpk-qi-data",
    "file\_size\_bytes": 0
  },
  "loader": {
    "name": "afmformats|afmreader|barakuda\_custom",
    "version": "...",
    "selected\_channel": "...",
    "available\_channels": \[],
    "metadata\_keys\_detected": \[],
    "warnings": \[]
  },
  "calibration": {
    "um\_per\_px\_x": null,
    "um\_per\_px\_y": null,
    "height\_unit": null,
    "source": "metadata|manifest|user|unknown",
    "warnings": \[]
  },
  "preprocessing": \[
    {
      "operation": "plane\_level",
      "enabled": true,
      "parameters": {},
      "coefficients": {},
      "warnings": \[]
    }
  ],
  "segmentation": {
    "method": "otsu|manual|percentile|adaptive|...",
    "polarity": "depression|peak",
    "threshold": null,
    "connectivity": 2,
    "watershed": {
      "enabled": false,
      "parameters": {}
    }
  },
  "filtering": {
    "rules": {},
    "rejection\_counts": {}
  },
  "metrics": {
    "equations\_version": "AFM\_HYDROGEL\_POROSITY\_BIBLE\_2026-05-27",
    "library\_functions": \[]
  },
  "compute": {
    "backend\_requested": "auto",
    "backend\_resolved": "cpu",
    "gpu": {},
    "fallbacks": \[]
  },
  "outputs": {
    "pore\_table\_csv": "...",
    "summary\_json": "...",
    "figures": \[]
  },
  "warnings": \[]
}
```

\---

## 18\. BARAKUDA integration points

Expected repo structure based on current BARAKUDA layout:

```text
barakuda/devices/afm/
  io/
  methods/
  core/
  export/
  device.py
  manifest.py
barakuda/shell/
  batch\_controller.py
  workers/
barakuda/core/
  afm\_report.py
```

Preferred implementation locations:

```text
barakuda/devices/afm/io/jpk\_qi\_loader.py
barakuda/devices/afm/io/canonical\_loader.py
barakuda/devices/afm/methods/hydrogel\_porosity.py
barakuda/devices/afm/core/hydrogel\_porosity.py
barakuda/devices/afm/export/hydrogel\_porosity\_export.py
```

Rules:

* Loader code goes in `afm/io/`.
* Scientific image analysis goes in `afm/core/` or method implementation, not shell UI.
* Method wrapper goes in `afm/methods/hydrogel\_porosity.py`.
* Export/report code goes in `afm/export/` or existing report layer.
* Shell/batch controller should only orchestrate, not implement equations.

\---

## 19\. Minimal implementation phases

### Phase A — Audit and diagnostics only

Goal:

* confirm loader options,
* inspect JPK/QI structure,
* write diagnostic JSON,
* no production scientific output yet.

Allowed file changes:

* one diagnostic script or test,
* this document update if needed.

### Phase B — Canonical AFM loader

Goal:

* produce canonical `height + metadata` from `.jpk-qi-data` and existing `.spm`, without changing analysis logic.

Required validation:

* known image shape,
* known scale,
* channel selection recorded,
* invalid metadata warning behavior.

### Phase C — Hydrogel Porosity v1 CPU

Goal:

* implement pore segmentation and metric outputs on CPU.

Required outputs:

* pore table CSV,
* summary JSON,
* mask/overlay figures,
* audit JSON.

### Phase D — Report and batch export

Goal:

* integrate with BARAKUDA's existing output style.

Required outputs:

* batch CSV/XLSX,
* item report PDF,
* batch report PDF eventually.

### Phase E — GPU acceleration

Goal:

* accelerate selected operations without changing scientific results.

Rules:

* CPU path remains canonical fallback.
* GPU path must pass numeric equivalence tests.
* GPU fallback must be audited.

### Phase F — QI mechanics research module

Goal:

* only after force-curve loading and calibration are validated.

Not allowed in Phase C:

* reporting viscosity,
* reporting Young's modulus from topography,
* fitting Hertz/Sneddon without full force-curve calibration.

\---

## 20\. Tests and validation

### 20.1 Synthetic image tests

Create synthetic masks/images with known geometry:

* one circle with known radius,
* two circles touching for watershed test,
* ellipse with known axis lengths,
* empty image,
* all-pore image,
* noisy background with shallow depressions.

Validate:

* area,
* equivalent diameter,
* centroid,
* pore count,
* area fraction,
* rejection filters.

### 20.2 Calibration tests

Validate conversion:

```text
512 px over 10 um -> 0.01953125 um/px
area per pixel = 0.01953125^2 um^2
```

### 20.3 Regression tests

For a fixed sample input, compare:

* summary JSON values within tolerance,
* pore count,
* output file existence,
* audit completeness.

### 20.4 CPU/GPU equivalence tests

If GPU backend is enabled, compare CPU and GPU outputs:

* same shape,
* same threshold or threshold within tolerance,
* mask IoU above defined threshold,
* metric differences within tolerance.

### 20.5 Failure tests

Must test:

* missing scale,
* unknown height unit,
* unreadable file,
* missing selected channel,
* invalid ROI,
* empty segmentation,
* no accepted pores after filtering.

\---

## 21\. Stop conditions for agents

Stop and ask for approval if:

1. More than five files must be changed.
2. A required dependency has GPL/LGPL implications not already accepted by the project.
3. JPK metadata do not contain enough information to determine lateral scale.
4. Height units are unclear but report would include height/roughness metrics.
5. Any output would imply viscosity, modulus, or bulk porosity from height-only data.
6. Segmentation requires subjective/manual tuning not recorded in audit.
7. GPU path changes numerical/scientific output beyond tolerance.
8. Existing OT, drag, Brownian, acquisition, or timing code would need changes.

\---

## 22\. Report language rules

Allowed phrasing:

```text
surface-visible pore-like depressions detected from AFM topography
2D pore area fraction within analyzed ROI
pore equivalent diameter distribution from segmented AFM regions
roughness of leveled AFM height map
```

Forbidden unless separately validated:

```text
bulk hydrogel porosity
true mesh size
viscosity from topography
permeability from AFM image
diffusion coefficient from AFM image
Young's modulus from height map
```

\---

## 23\. Bibliography / source links checked

This section records external sources that justify tool selection, available APIs, or scientific cautions. Agents may add sources, but must not remove existing ones without reason.

### AFM/JPK loading

1. `afmformats` documentation — base module for loading experimental AFM data:  
https://afmformats.readthedocs.io/en/stable/sec\_getting\_started.html
2. `afmformats` documentation PDF/search result indicating support for `.jpk-qi-data`:  
https://afmformats.readthedocs.io/\_/downloads/en/stable/pdf/
3. `afmformats` GitHub — MIT license:  
https://github.com/AFM-analysis/afmformats
4. `AFMReader` GitHub — supported formats include `.jpk-qi-image`, `.jpk`, `.spm`, `.gwy`, etc.:  
https://github.com/AFM-SPM/AFMReader
5. `AFMReader` PyPI — license metadata:  
https://pypi.org/project/AFMReader/
6. Bruker/JPK QI mode description — QI files may contain up to \~260,000 force-distance curves and can provide height/slope/adhesion impressions:  
https://www.bruker.com/en/products-and-solutions/microscopes/bioafm/resource-library/qi-mode-quantitative-imaging-with-the-nanowizard-3-afm.html

### Pore/image analysis

7. PoreSpy GitHub — porous material image analysis tools:  
https://github.com/PMEAL/porespy
8. PoreSpy local thickness documentation:  
https://porespy.org/examples/filters/tutorials/local\_thickness.html
9. PoreSpy pore size distribution documentation:  
https://porespy.org/examples/metrics/reference/pore\_size\_distribution.html
10. scikit-image regionprops example/documentation:  
https://scikit-image.org/docs/0.25.x/auto\_examples/segmentation/plot\_regionprops.html
11. scikit-image measure API:  
https://scikit-image.org/docs/stable/api/skimage.measure.html
12. scikit-image thresholding guide / Otsu method description:  
https://scikit-image.org/docs/0.25.x/auto\_examples/applications/plot\_thresholding\_guide.html
13. SciPy exact Euclidean distance transform documentation:  
https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.distance\_transform\_edt.html
14. scikit-image marker watershed documentation:  
https://scikit-image.org/docs/0.25.x/auto\_examples/segmentation/plot\_marked\_watershed.html

### Roughness/topography

15. Digital Surf guide — areal field parameters according to ISO 25178-2:  
https://guide.digitalsurf.com/en/guide-areal-field-parameters.html
16. Keyence roughness guide — ISO 25178 surface texture parameters including Sa, Sq, Ssk, Sku, Sp, Sv:  
https://www.keyence.eu/ss/products/microscope/roughness/surface/parameters.jsp
17. Gwyddion user guide — plane subtraction/ordinary least squares plane concept for image data:  
https://gwyddion.net/download/user-guide/gwyddion-user-guide-en.pdf
18. Nečas et al. 2020 — leveling and scan-line corrections can affect roughness results:  
https://pmc.ncbi.nlm.nih.gov/articles/PMC7499267/

### Hydrogels and pore-analysis caution

19. Rossberg et al. 2025, Automated analysis of pore structures in biomaterials — highlights need for standardization, validation, and consistent reporting in pore analysis:  
https://pubs.rsc.org/en/content/articlehtml/2025/tb/d5tb00848d
20. Jamshidi et al. 2021 — image analysis method for hydrogel heterogeneity and porosity characterization:  
https://pmc.ncbi.nlm.nih.gov/articles/PMC8256190/

### GPU/RAM

21. CuPy documentation/site — GPU-accelerated NumPy/SciPy-compatible array library:  
https://cupy.dev/
22. cuCIM documentation — GPU accelerated n-dimensional image processing:  
https://docs.rapids.ai/api/cucim/stable/
23. NVIDIA cuCIM blog — accelerating scikit-image-like image processing on GPUs:  
https://developer.nvidia.com/blog/cucim-rapid-n-dimensional-image-processing-and-i-o-on-gpus/
24. Dask Array documentation — blocked algorithms and arrays larger than memory:  
https://docs.dask.org/en/latest/array.html
25. Zarr documentation — chunked/compressed N-dimensional arrays:  
https://zarr.readthedocs.io/

### Future AFM mechanics

26. Bruker mechanical property mapping documentation — Hertz/Sneddon model context and variables:  
https://www.nanophys.kth.se/nanolab/afm/icon/bruker-help/Content/ForceVolume/Mechanical%20Property%20Mapping.htm
27. Kontomaris 2022 review — restrictions of Hertz model in AFM nanoindentation:  
https://www.sciencedirect.com/science/article/abs/pii/S0968432822000245
28. Springer entry on hydrogel elastic modulus measurement — AFM indentation and model fitting context:  
https://link.springer.com/rwe/10.1007/978-3-319-77830-3\_60

\---

## 24\. First instruction to future implementation agent

Before writing production code, do this:

```text
1. Read AGENTS.md.
2. Read docs/agent\_tasks/AFM\_HYDROGEL\_POROSITY\_BIBLE.md.
3. Confirm current AFM method/loader/export paths.
4. Do not touch optical tweezers, drag, Brownian, acquisition, or timing truth code.
5. Start with one narrow diagnostic task.
6. Use existing libraries where possible.
7. Save audit JSON for every diagnostic and every analysis run.
8. Stop if more than five files need editing.
```

\---

## 25\. Current immediate next task recommendation

Recommended next task:

```text
Task AFM-A1 — JPK/QI loader diagnostic audit
```

Goal:

* inspect one `.jpk-qi-data` file,
* try `afmformats`,
* try internal `.jpk-qi-image` via AFMReader if appropriate,
* produce `jpk\_qi\_diagnostic.json`,
* report detected channels, scale, shape, units, and loading time,
* do not implement hydrogel segmentation yet.

Expected changed files:

```text
0-2 files maximum
```

Suggested files:

```text
scripts/diagnose\_jpk\_qi.py
or
barakuda/devices/afm/io/jpk\_qi\_diagnostic.py
```

Do not proceed to production implementation until diagnostics are reviewed.


---

## Update 2026-06-02 — AFM-A1 JPK/QI loading validation freeze

- Decision:
  - AFM-A1 diagnostics are paused in a validated pre-segmentation state.
  - Current work stops before segmentation feasibility.
  - No final production channel has been selected.

- Repository state:
  - Branch: feature/afm-hydrogel-porosity
  - Last relevant pushed commits:
    - d15e4a6 docs: add AFM hydrogel porosity bible
    - 14da5ce chore: ignore local AFM diagnostic artifacts
  - diagnostics/ is local ignored output and must not be committed.
  - One-off diagnostic scripts are local ignored scripts and must not be committed.

- Validated JPK source:
  - Source file: C:\Work\1-prct-AG-10x10-512x512.jpk-qi-data
  - Internal image: data-image.jpk-qi-image
  - Internal image SHA256: 73467f56e4e738066ee38cce12e1a9063e72c1f9cd4858cdf84b24ef8e4e23f8
  - Grid: 512 x 512 px
  - Scan size: 10 x 10 µm
  - Pixel size: 0.01953125 µm/px
  - Page 0: 64 x 64 preview
  - Pages 1–5: 512 x 512 int32 full-resolution channels

- Verified channel mapping:
  - Page 1 = vDeflection, role auxiliary_contrast_qc, default slot force, unit N
  - Page 2 = adhesion, role auxiliary_contrast_qc, default slot force, unit N
  - Page 3 = slope, role auxiliary_contrast_qc, default slot volts, unit V
  - Page 4 = measuredHeight, role provisional_topography_candidate, default slot nominal, unit m
  - Page 5 = height, role provisional_topography_candidate, default slot calibrated, unit m

- Calibration values:
  - Page 1 vDeflection:
    multiplier = 1.1372479554597193e-18
    offset = -9.179100973056714e-10
    unit = N
  - Page 2 adhesion:
    multiplier = 8.195939290254133e-19
    offset = 7.386039963348108e-10
    unit = N
  - Page 3 slope:
    multiplier = 2.459201689976086e-12
    offset = 0.005676285999597853
    unit = V
  - Page 4 measuredHeight:
    multiplier = 1.6007394836112993e-15
    offset = 1.3295399523850161e-05
    unit = m
  - Page 5 height:
    multiplier = -1.1024078717794967e-15
    offset = 9.628506312840996e-06
    unit = m
  - Conversion formula:
    physical = raw_int32 * multiplier + offset
  - Sentinels:
    -2147483648 and 2147483647 are masked as NaN

- ROI decision:
  - Central ROI: y=40:340, x=20:492
  - Shape: 300 x 472 px
  - Physical size: approximately 9.2188 x 5.8594 µm
  - Reason: excludes lower horizontal artifact band and lateral edge margins
  - Page 4/Page 5 central ROI has zero NaNs

- Current interpretation:
  - Primary provisional topography candidate: Page 5 height calibrated
  - Control topography candidate: Page 4 measuredHeight nominal
  - Auxiliary channels retained:
    - Page 1 vDeflection for QC
    - Page 2 adhesion for possible pore-boundary contrast
    - Page 3 slope for possible edge/sidewall contrast
  - Page 1–3 must not be treated as height/topography.

- Loading validation:
  - TIFF page validation passed.
  - Page 4 measuredHeight tag validation passed.
  - Page 5 height/calibrated tag validation passed.
  - All saved NPY ROI arrays matched recomputation from raw JPK.
  - index/ sampled entries indicate per-pixel QI force-curve storage, not ready 2D image.
  - shared-data is not present as a direct ZIP entry in the loading validation; record this as a non-blocking warning.

- Local diagnostic evidence files:
  - diagnostics/afm_jpk_qi/1-prct-AG-10x10-512x512/AFM_A1_CHANNEL_AUDIT_MANIFEST.md
  - diagnostics/afm_jpk_qi/1-prct-AG-10x10-512x512/loading_validation_audit/loading_validation_audit.md
  - diagnostics/afm_jpk_qi/1-prct-AG-10x10-512x512/aligned_roi_all_channels/aligned_roi_all_channels_summary.md
  - These files are intentionally local/ignored and should not be committed.

- Stop state:
  - Do not continue with production implementation yet.
  - Do not run final porosity.
  - Do not compute pore metrics.
  - Do not compute roughness.
  - Do not claim bulk porosity.
  - Do not claim viscosity, modulus, permeability, mesh size, or diffusion coefficient from the static AFM height map.

- Resume task after pause:
  - First verify:
    git status --short --branch
  - Confirm local diagnostics still exist.
  - Then run AFM-A1r segmentation feasibility only on copies of the aligned central ROI.
  - Use Page 5 height calibrated as primary provisional input.
  - Use Page 4 measuredHeight nominal as control.
  - Optionally compare Page 2 adhesion and Page 3 slope as auxiliary overlays.
  - AFM-A1r must remain diagnostic-only and must not produce final scientific claims.

Resume state verified before AFM-A1r; AFM-A1r still requires explicit user approval.
