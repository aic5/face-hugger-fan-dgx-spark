# DGX Spark thermal comparison

Test date: **13 September 2026**

The supplied comparison contains separate temperature traces for a baseline run
without the external fan and an updated run with the fan. It reports GPU and CPU
summary statistics and a point-by-point delta chart over roughly 80 minutes.

[Open the original one-page PDF report](results/dgx-fan-temperature-2026-09-13.pdf).

## Published measurements

| Statistic | GPU, no fan | GPU, with fan | With fan minus baseline | CPU, no fan | CPU, with fan | With fan minus baseline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Median | 63.5 °C | 64.0 °C | +0.5 °C | 73.6 °C | 72.2 °C | -1.4 °C |
| Average | 60.8 °C | 62.1 °C | +1.3 °C | 68.0 °C | 69.8 °C | +1.8 °C |
| Maximum | 78.0 °C | 68.0 °C | **-10.0 °C** | 91.6 °C | 76.7 °C | **-14.9 °C** |
| Minimum | 42.0 °C | 39.0 °C | -3.0 °C | 44.0 °C | 40.7 °C | -3.3 °C |
| Standard deviation | 11.2 °C | 7.3 °C | **-3.9 °C** | 14.8 °C | 9.3 °C | **-5.5 °C** |

Negative deltas are cooler or less variable. Positive deltas are warmer.

## Interpretation

The external fan substantially reduced the highest recorded temperatures:
10.0 °C lower for the GPU and 14.9 °C lower for the CPU. The standard deviations
also fell by 3.9 °C and 5.5 °C, consistent with a more stable temperature trace.

The same data does **not** show a lower average temperature. Average GPU and CPU
temperatures were 1.3 °C and 1.8 °C higher with the fan, and the GPU median was
0.5 °C higher. The strongest supported conclusion from this run is therefore
reduced peaks and variability - not universally lower temperature.

## Limits of the comparison

The report does not record enough experimental detail for a controlled benchmark.
In particular, it does not state:

- the exact workload or whether both runs used an identical timed script;
- ambient temperature and room airflow;
- the fan position, PWM duty, or control curve used during the fan run;
- the DGX Spark software/power mode and internal fan behavior;
- sampling cadence, raw timestamps, or a formal warm-up period; or
- whether the two traces contain perfectly paired samples.

Those omissions can affect averages and point-by-point deltas. Treat this as a
useful build result, not a general performance guarantee.

## Suggested reproduction protocol

1. Record ambient temperature and place the DGX in the same location for both runs.
2. Use a scripted workload with fixed duration, power mode, model/data, and idle
   warm-up/cool-down periods.
3. Log GPU, CPU, fan PWM, tach RPM, power, and timestamps at a fixed cadence.
4. Run baseline and fan conditions in alternating order, with at least three runs
   per condition.
5. Publish raw CSV data and the exact analysis script alongside the summary.
6. Compare peak, median, average, standard deviation, time above thresholds, and
   workload performance so cooling is not confused with a workload difference.
