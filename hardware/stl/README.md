# Printable body and arms

This directory contains the two supplied binary STL exports for the Face Hugger
Fan assembly:

- [face-hugger-fan-dgx-spark-body.stl](face-hugger-fan-dgx-spark-body.stl) - fan
  body / cover
- [face-hugger-fan-dgx-spark-arms.stl](face-hugger-fan-dgx-spark-arms.stl) -
  the arm set

## File checks

| File | Binary STL triangles | File size | Geometry extents (X × Y × Z) |
| --- | ---: | ---: | ---: |
| Body | 12,554 | 627,784 bytes | 117.39 × 157.70 × 103.55 model units |
| Arms | 1,732 | 86,684 bytes | 165.10 × 161.52 × 5.66 model units |

Both files have internally consistent binary STL sizes. STL stores unitless
coordinates; the geometry appears intended for millimetres, but verify scale and
fit in the slicer before printing.

SHA-256 checksums:

```text
9c1f025c2a4f044e721fbc4a8768e0ce10d8e4b5323c02de7012720d822ea69a  face-hugger-fan-dgx-spark-body.stl
e7a46a85c022b9e21589a93c3937379717238a1be09f6edae005b530b0292813  face-hugger-fan-dgx-spark-arms.stl
```

## Printing and assembly status

The source material does not yet include a validated slicer profile, source CAD,
material choice, support strategy, fastener list, or step-by-step mechanical
assembly guide. Until those are documented:

- inspect the imported scale against the 140 mm fan and the dimensions above;
- choose material with appropriate heat resistance and creep performance;
- orient and support the parts based on load paths and your printer's behavior;
- keep printed parts and fasteners clear of the blades and DGX vents;
- protect the Pico antenna from nearby metal and dense wiring; and
- treat the assembly as a prototype that requires inspection before each use.

The models are distributed under the repository's MIT License. Editable CAD and
tested print settings are welcome as future contributions.
