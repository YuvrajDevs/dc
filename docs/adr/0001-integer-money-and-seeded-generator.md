# 0001: Integer money and a seeded, pure generator

**Status:** accepted

Money is stored and computed as integer minor units. Floats are never used for an amount, so rounding is explicit, testable and identical everywhere. Percentage fees and FX conversion use integer arithmetic with round-half-up.

The synthetic world is a pure function of its config, using an independent seeded random stream per stage. The same seed always gives byte-identical files, which makes every test and benchmark reproducible and lets CI compare hashes.
