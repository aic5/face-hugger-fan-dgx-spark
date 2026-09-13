# Bill of materials

This bill covers the electronics and basic assembly described by the repository.
The printed cover and arms will be added under `hardware/stl/` separately.

## Required parts

| Qty. | Part | Specification / example | Notes |
| ---: | --- | --- | --- |
| 1 | NVIDIA DGX Spark | Target computer | The accessory does not modify the DGX internally. |
| 1 | Raspberry Pi Pico W | RP2040, 2.4 GHz Wi-Fi | A Pico WH is also plausible if its fitted headers suit the assembly, but this has not been verified. |
| 1 | 140 mm 4-wire PWM fan | **Noctua NF-A14 PWM, standard 12 V model** | Do not substitute the 5 V edition. See [fan specifications](fan-specifications.md). |
| 1 | 5 V-to-12 V DC boost converter | Regulated 12 V output; design for at least 0.5 A continuous output plus startup margin | The exact converter used in the prototype was not recorded in the source material. Verify its rating and set the output to 12 V before connecting anything else. |
| 1 | Regulated 5 V USB supply and cable | Enough capacity for the Pico, converter losses, and fan startup | The fan alone draws about 0.37 A from 5 V at 1.56 W and an illustrative 85% converter efficiency. Budget additional margin. |
| 1 | 4-pin PC fan mating header, breakout, or extension | Keyed, with accessible conductors | Do not cut the fan cable unless you accept the warranty and serviceability consequences. |
| 1 | 1 kΩ resistor | Tachometer pull-up | Connect from Pico 3V3(OUT) to the GP13/tach node. |
| 1 | 1 µF non-polarized capacitor | Tachometer filtering | Connect from the GP13/tach node to ground. |
| as needed | Insulated hookup wire | Suitable for signal and power currents | Keep motor wiring short and route its return directly to the supply. |
| as needed | Heat-shrink, terminals, strain relief, and fasteners | Appropriate to the assembly | No bare conductors should remain exposed. |
| 1 | Fan guard / printed cover | Sized for the 140 mm fan | Keep fingers, tools, cables, and the printed mount out of the blades. |

## Optional shared USB-C input variant

The illustrated wiring guide also documents a prototype arrangement using an
ANMBEST JRC-B008 USB-C receptacle breakout with pads marked `G`, `D+`, `D-`, and
`V`, plus an added Schottky diode on the Pico VSYS branch.

Treat that section as an advanced, unverified variant. The source material does
not establish that the board has the two independent 5.1 kΩ USB-C CC pull-downs
required of a basic power sink. Verify the actual board and 5 V output before
connecting it. Do not attach two USB hosts to the Pico USB socket and test pads.

## Tools

- Multimeter for polarity, continuity (with power off), 5 V input, and regulated
  12 V output checks
- Soldering equipment appropriate for the Pico/header assembly
- Small insulated hand tools
- A computer for installing CircuitPython and copying files
- A second device on the same trusted LAN for opening the dashboard

## Before buying substitutions

- The firmware assumes a standard 4-wire PC PWM interface at 25 kHz.
- The direct PWM signal is 3.3 V from GP15 and is not inverted.
- The tachometer is an open-collector, two-pulses-per-revolution signal.
- The configured lower limit is 20% PWM for a running fan; verify the actual
  minimum reliable duty with your fan and power supply.
- A converter's advertised input current or peak rating is not its continuous
  12 V output rating. Include cable losses and motor startup margin.

Manufacturer references:

- [Noctua NF-A14 PWM specifications](https://www.noctua.at/en/products/nf-a14-pwm/specifications)
- [Noctua PWM and RPM microcontroller guidance](https://www.noctua.at/en/support/faqs/microcontroller-guide-pwm-setup-and-rpm-monitoring)
- [Raspberry Pi Pico W documentation](https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html)
- [CircuitPython for Raspberry Pi Pico W](https://circuitpython.org/board/raspberry_pi_pico_w/)
