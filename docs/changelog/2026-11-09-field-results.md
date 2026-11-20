# What's new (2026-11-09): field results from a 738-component model in SolidWorks 2019

- **Update in place, never rebuild to change a value.** A run with no change over 70 parts: **1 s** (fingerprints,
  nothing opened) instead of ~19 min; a value change touching half the parts: **0 rebuilds**, ~15 min instead of 62
  rebuilds and ~27 min, with edge ids, mates and drawings kept. [How it works](../../skill/solidworks-api/references/update_in_place.md)
- **Big assemblies on 2019:** 738 components placed in 60 s; mates inside sub-assemblies on named planes, checked
  against the computed transform; interference by sub-assembly + cut-out + Python clearances. [Assemblies](../../skill/solidworks-api/references/assemblies.md)
- **20 SolidWorks 2019 traps** with cause and workaround (window limit crash, licence/VPN drops, configuration API
  crashes, 6-digit globals...). [Version notes](../../skill/solidworks-api/references/version_notes.md)
- **The whole day, measured:** timeline, method versions 1.0-1.4, time and tokens per task, what worked and what
  didn't. [Roadmap](../../skill/solidworks-api/ROADMAP.md)

[All updates](README.md) · [Back to the main page](../../README.md)
