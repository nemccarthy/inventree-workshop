# Changelog

All notable changes to this plugin are recorded here.
Versions follow [semantic versioning](https://semver.org).

## 0.1.0 - 2026-11-20

First release. Built and tested against InvenTree 1.7.3.

- A list of workshop machines (laser, CNC, other) with notes
- Link a part to its machine and to one or more files, kept as attachments of
  the part, in order and with labels; good parts and machine time of one run;
  setup notes
- Read xTool project files (.xcs) for display: machine, area, what is cut,
  scored and engraved with which settings, the preview picture
- Read G-code programs for display: tools, spindle speed, feed, travel and
  depth; tool names, material and running time from the header of Makera's
  CAM software
- Raise a job from the part page: a build order for whole runs
- Download the files of a part or a job (a zip when there are several), and
  book the good parts into stock as build outputs when the job has been run
- Take the material the runs used from stock, against the bill of materials
  lines of the build order
- Keep a job open for the rest, close it short, or cancel it
- Say when more of a part is due: below its minimum stock, or needed by build
  orders in production
- Workshop page with every linked part and open job, by machine, and the
  machine time still to do
- API for scripts

No machine is controlled.
