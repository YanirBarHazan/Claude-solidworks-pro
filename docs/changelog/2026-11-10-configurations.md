# What's new (2026-11-10): configurations, one-command updates, and the bugs a real change exposed

- **Suppression configurations on a 770-component assembly in 35 s each** (was > 25 min): one tree walk, one
  `EditSuppress2`. The timing table that found the cause: [assemblies](../../skill/solidworks-api/references/assemblies.md)
- **One command for any value change:** parameters text file + `update.bat` -> checks, update in place, assemblies
  regenerated only for layout values, one PASS/FAIL line. 3.5 min for a part value, 17 min for a layout change.
  [Update in place](../../skill/solidworks-api/references/update_in_place.md)
- **Three traps found by the first layout change** (negative global under `^`, equation edits not saved, crash
  mid-batch) - each caught by a check, not by eye. [Version notes 25-31](../../skill/solidworks-api/references/version_notes.md) |

[All updates](README.md) · [Back to the main page](../../README.md)
