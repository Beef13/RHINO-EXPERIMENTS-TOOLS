# Growth Tools

## What It Does
Generates branching growth structures using biased random walks. Draws results as line segments in Rhino.

## Usage
Run `ui.py` in Rhino:
1. Pick a starting point
2. Set number of steps and step size
3. Branch structure appears on the `Growth` layer

## Parameters
- **steps** — number of growth iterations (more = longer branches)
- **step_size** — length of each growth segment
- **bias** — directional tendency (default upward)
- Branching probability is currently hardcoded at 10%

## Limitations
- No collision detection between branches
- No thickness variation
- Lines only — no pipe or mesh output

## Ideas
- [ ] Space colonisation algorithm (attract to nearby food points)
- [ ] DLA (diffusion-limited aggregation)
- [ ] Variable branching probability based on depth
- [ ] Pipe output with tapering radius
- [ ] Gravity/obstacle avoidance
