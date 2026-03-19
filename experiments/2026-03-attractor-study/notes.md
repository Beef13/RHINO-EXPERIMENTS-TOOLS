# Attractor Study

## Goal
Compare different attractor falloff functions and visualise their effects on a random point field.

## How to Run
1. Open Rhino
2. `RunPythonScript` → select `script.py`
3. Pick an attractor point
4. Choose a falloff type: `linear`, `inverse`, or `gaussian`
5. Points appear on a named layer, displaced in Z by the falloff

## Falloff Types
- **Linear** — strength decreases linearly with distance, reaches zero at influence radius
- **Inverse** — 1/(1 + distance), soft falloff with long tail
- **Gaussian** — bell curve, concentrated near attractor, drops off smoothly

## Ideas to Try
- [ ] Overlay multiple falloff types on separate layers for comparison
- [ ] Add colour gradient based on Z height
- [ ] Animate by sweeping the attractor point
- [ ] Try 3D point fields instead of flat

## Observations
_Add notes here as you experiment._
