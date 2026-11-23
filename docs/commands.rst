Standalone native commands
==========================

Use run_command() for small preparation scripts that need MEGAlib's initialized
environment but do not need an analysis workspace. It reuses MEGAlibRuntime's
child-process initialization, so the calling shell and Python environment do
not need to source MEGAlib first.

.. code-block:: python

   from megalibpy import MEGAlibRuntime, run_command

   runtime = MEGAlibRuntime.from_setup_script("initialize-megalib.sh")
   result = run_command(
       ["mimrec", "--help"],
       runtime=runtime,
       capture_output=True,
   )
   print(result.stdout)
   print(result.returncode)

The return value is subprocess.CompletedProcess, not ExecutionResult. There is
no root manifest, execution ID, analysis group, input snapshot, product discovery
or automatic output numbering. Caller-selected files are written according to
native command behavior. Temporary launch helpers are removed even on failure
or timeout. runtime.archive_inputs has no effect here.

One random background interval
-------------------------------

The following single-use example extracts a one-second interval from an input
TRA. It creates only the caller's output directory and the native output; no
megalibpy workspace is required. Supply the real valid time range in the TRA's
native time system. The illustrative range is assumed continuously valid.

.. code-block:: python

   import random
   from pathlib import Path
   from megalibpy import MEGAlibRuntime, run_command

   runtime = MEGAlibRuntime.from_setup_script("initialize-megalib.sh")
   config = Path("config/analysis.mimrec.cfg").resolve()
   geometry = Path("geometry/detector.geo.setup").resolve()
   background = Path("data/background-day.tra.gz").resolve()
   output = Path("bkg/background-1s.tra.gz").resolve()
   output.parent.mkdir(parents=True, exist_ok=True)

   day_start = 1000.0
   day_stop = day_start + 86400.0
   start = random.uniform(day_start, day_stop - 1.0)
   stop = start + 1.0
   print(f"Background interval: {start:.9f} to {stop:.9f}")

   result = run_command(
       ["mimrec", "-g", str(geometry), "-f", str(background),
        "-c", str(config), "-o", str(output),
        "-C", "EventSelections.TimeMode=1",
        "-C", f"EventSelections.Time.Min={start:.9f}",
        "-C", f"EventSelections.Time.Max={stop:.9f}",
        "-n", "-x"],
       runtime=runtime,
       cwd=config.parent,
   )

All other native cfg selections still apply. Native Mimrec's TimeMode=1 uses
inclusive minimum and maximum timestamps; this example does not introduce a
half-open partitioning rule, infer observation gaps or align event clocks.
Use the generated TRA path as external_components in your later named Mimrec
analysis. Keep background selection and its study-specific bookkeeping in your
own script.

Arguments, output and failures
-------------------------------

Pass an argv list, never a shell command string. Arguments are literal; shell
expansion, pipes and redirection operators are not interpreted. The optional
cwd controls the child's working directory; parent cwd/environment stay intact.

By default stdout/stderr are inherited, without collecting whole logs in memory.
With capture_output=True both streams, including initialization output, are
returned as UTF-8 strings with invalid bytes replaced. Capture is unbounded;
choose it only for appropriate output volumes.

check=True is the default and raises subprocess.CalledProcessError for a nonzero
exit, including setup failure. check=False returns the exit status instead.
timeout is in seconds, default None (unlimited); expiration raises
subprocess.TimeoutExpired following subprocess.run() termination behavior.
Neither exception has a workspace manifest. A zero exit status only reports the
native process result; the helper does not validate output contents.

See :func:`megalibpy.run_command` for the full API. Use Cosima/Revan/Mimrec when
managed execution records and data lineage are required.
