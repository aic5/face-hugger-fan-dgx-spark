# Fan specifications

The reference build uses the **Noctua NF-A14 PWM standard 12 V model**. Similar
product names exist for different voltage and connector variants, so check the
label before wiring.

## Manufacturer specifications

| Property | Published value |
| --- | --- |
| Form factor | 140 × 140 × 25 mm without anti-vibration pads |
| Size with anti-vibration pads | 141 × 141 × 27 mm |
| Mounting-hole spacing | 124.5 × 124.5 mm |
| Connector | 4-pin PWM |
| Rated voltage | 12 V |
| Maximum operating voltage | 13.2 V |
| Starting voltage | 7 V |
| Speed range | 0-1,500 RPM |
| Speed at 20% PWM | 300 RPM |
| Maximum airflow | 140.2 m³/h / 82.52 CFM |
| Maximum static pressure | 2.08 mm H₂O |
| Maximum acoustical noise | 24.6 dB(A) |
| Typical / maximum input power | 1.19 W / 1.56 W |
| Typical / maximum input current | 0.10 A / 0.13 A |
| Tachometer | Open-collector, 2 pulses per revolution |
| Fan operating temperature | -10 °C to +70 °C |

Values are from the linked manufacturer pages as accessed in September 2026.
The project has not independently certified every specification.

## Pinout used by this project

| Fan pin | Standard wire colour | Function | Project connection |
| ---: | --- | --- | --- |
| 1 | Black | Ground | Boost `OUT-` and Pico ground |
| 2 | Yellow | Motor voltage | Regulated boost `OUT+` at 12 V |
| 3 | Green | RPM / tachometer | Pico GP13, physical pin 17, with 1 kΩ pull-up and 1 µF filter |
| 4 | Blue | PWM command | Pico GP15, physical pin 20 |

Wire colour is only a cross-check. Use the keyed connector and manufacturer
pin numbering; the apparent left-to-right order reverses between mating-face and
wire-side views.

## How the firmware uses it

- PWM output: direct, non-inverted 3.3 V logic at 25 kHz
- Accepted command: off (`0%`) or `20-100%`
- Startup: 100% for two seconds when starting from off
- Default remote fail-safe: 100% until valid commands arrive and after timeout
- RPM estimate: tach falling edges divided by two pulses per revolution

PWM duty is a command, not closed-loop RPM regulation. The dashboard also shows
a simple linear RPM estimate for charting, while the API keeps the physical tach
reading separate.

## References

- [NF-A14 PWM specifications](https://www.noctua.at/en/products/nf-a14-pwm/specifications)
- [Noctua microcontroller PWM/RPM guide](https://www.noctua.at/en/support/faqs/microcontroller-guide-pwm-setup-and-rpm-monitoring)
- [Noctua 4-wire PWM specification](https://cdn.noctua.at/media/Noctua_PWM_specifications_white_paper.pdf)
