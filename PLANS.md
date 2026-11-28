# Plans

| | **Free** | **Pro** | **Company** |
|---|---|---|---|
| Who | everyone, including engineers at work | engineers who use it every day | teams and departments |
| Price | free | monthly subscription | quote |
| Parametric parts, assemblies, verification, update in place | ✅ | ✅ | ✅ |
| Drawings, BOM, PDF / DXF, engineering checks, 3D printing | ✅ | ✅ | ✅ |
| Claude tab inside SolidWorks, day log, Hebrew / English | ✅ | ✅ | ✅ |
| **Sheet metal**: flat pattern, bend table / K-factor, DXF for cutting | | ✅ | ✅ |
| **DXF → flat parts**: build sheet-metal parts from a DXF | | ✅ | ✅ |
| **Simulation**: static study, factor of safety, hand-calculation check | | ✅ | ✅ |
| **Manufacturing package**: STEP + PDF + DXF + BOM (Excel) ready for the supplier | | ✅ | ✅ |
| **Advanced drawings**: full assembly drawing set, revision table, auto title block | | ✅ | ✅ |
| **Whole-project update** across hundreds of files, resume after a crash | | ✅ | ✅ |
| **New project in one command**, weekly / monthly report from the day log | | ✅ | ✅ |
| Early access and priority support | | ✅ | ✅ |
| Your company's templates, materials, standards and title block built in | | | ✅ |
| Licenses for the whole team, central management | | | ✅ |
| Training and installation for the department, support agreement | | | ✅ |
| Server inside your own network | | | option |

Pro features run from the Pro server and are added continuously; subscribers get each one as soon as it ships.

**Pro:** subscription page coming soon. **Company:** message
**[Yanir Bar Hazan on LinkedIn](https://www.linkedin.com/in/yanir-hazan)** with your company name and roughly how many
engineers will use it.

## License in one line
The free version is under [PolyForm Shield 1.0.0](LICENSE): use it anywhere, including at work. Do not sell it or
build a competing product from it. Pro and company features are a separate commercial service.

## Activating Pro
After subscribing you get a key by email. On your PC:
```
python "%USERPROFILE%\.claude\skills\solidworks-api\scripts\pro_license.py" activate SWP-XXXX-XXXX-XXXX-XXXX
```
The key works on 2 PCs (`deactivate` frees one). Pro keeps working offline for up to 7 days, and for 7 days
after a missed payment, then the Pro tools lock until the subscription is renewed. The free version keeps working.
