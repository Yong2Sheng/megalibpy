"""Lightweight native commands with runtime initialization and no workspace."""

import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from .runtime import MEGAlibRuntime


def run_command(command, *, runtime=None, cwd=None, timeout=None, check=True, capture_output=False):
    """Run one native command in a MEGAlib runtime without a workspace.

    Parameters
    ----------
    command : sequence of str or os.PathLike
        Nonempty argv sequence, beginning with the executable name or path.
        Each argument is passed literally with shell=False. Shell command
        strings, pipelines, redirections and variable expansion are not parsed.
        Format numeric native values as strings before passing them.
    runtime : MEGAlibRuntime or None, optional
        Runtime to initialize in the child, default None (direct mode).
        from_setup_script() sources its trusted script before executing the
        command, even if the parent shell has no MEGAlib environment. The
        parent's environment and working directory remain unchanged.
    cwd : str or pathlib.Path or None, optional
        Child working directory. None (default) inherits the caller's directory.
        No directory is created; relative resource/output paths use this base.
    timeout : float or None, optional
        Positive timeout in seconds, including initialization. None (default)
        waits indefinitely. Process termination follows subprocess.run().
    check : bool, optional
        True (default) raises subprocess.CalledProcessError on nonzero exit.
        False returns the process status, including setup or tool-discovery
        failures that occur inside the child.
    capture_output : bool, optional
        False (default) inherits stdout/stderr without capturing them in memory.
        True captures both, including setup output, as UTF-8 strings with invalid
        bytes replaced. Capture is unbounded; use only for suitable log volumes.

    Returns
    -------
    subprocess.CompletedProcess
        Original native args and returncode; stdout/stderr are strings when
        captured, otherwise None. This is not an ExecutionResult and has no
        manifest, execution ID, discovered products or provenance registration.

    Raises
    ------
    TypeError
        command is a shell string, an argument is not text/path-like, or runtime
        is not a MEGAlibRuntime.
    ValueError
        Empty argv/executable, invalid boolean options or nonpositive timeout.
    FileNotFoundError
        Direct-mode executable, setup script, Bash or cwd cannot be found.
    subprocess.CalledProcessError
        Initialization or command exits nonzero and check=True. cmd identifies
        the original native argv, not a removed temporary launch script.
    subprocess.TimeoutExpired
        Timeout expires. cmd identifies the original argv.
    OSError
        Temporary helper creation or process launch fails.

    Notes
    -----
    Uses the same runtime bootstrap as managed execution, including environment
    separation and the ROOT-compatible script launcher. Temporary helpers are
    removed on success, failure and timeout. No workspace/manifest, cfg archive,
    automatic -n/-x flags, output validation or file protection is added. Native
    commands may create or overwrite outputs according to their own rules.
    runtime.archive_inputs does not apply to this unmanaged command.

    Examples
    --------
    >>> runtime = MEGAlibRuntime.from_setup_script("initialize-megalib.sh")
    >>> result = run_command(  # doctest: +SKIP
    ...     ["mimrec", "-g", "detector.geo.setup", "-f", "background.tra.gz",
    ...      "-c", "analysis.mimrec.cfg", "-o", "background-1s.tra.gz",
    ...      "-C", "EventSelections.TimeMode=1",
    ...      "-C", "EventSelections.Time.Min=100",
    ...      "-C", "EventSelections.Time.Max=101", "-n", "-x"],
    ...     runtime=runtime)
    """
    if isinstance(command, (str, bytes, os.PathLike)):
        raise TypeError("command must be an argv sequence, not a shell command string")
    argv = [os.fspath(value) for value in command]
    if any(not isinstance(value, str) for value in argv):
        raise TypeError("command arguments must be text or text paths")
    if not argv or not argv[0]:
        raise ValueError("command requires a nonempty executable")
    if timeout is not None and timeout <= 0:
        raise ValueError("timeout must be positive")
    if not isinstance(check, bool) or not isinstance(capture_output, bool):
        raise ValueError("check and capture_output must be bool")
    runtime = MEGAlibRuntime.direct() if runtime is None else runtime
    if not isinstance(runtime, MEGAlibRuntime):
        raise TypeError("runtime must be a MEGAlibRuntime")
    directory = None if cwd is None else Path(cwd).expanduser().resolve()
    with TemporaryDirectory(prefix="megalibpy-command-") as temporary:
        launch_argv = argv
        if runtime.setup_script is None and directory is not None and os.path.dirname(argv[0]) and not Path(argv[0]).is_absolute():
            launch_argv = [str(directory / argv[0]), *argv[1:]]
        launch, env = runtime.launch(launch_argv, Path(temporary) / "executable.txt")
        try:
            process = subprocess.run(launch, env=env, cwd=directory, timeout=timeout,
                                     capture_output=capture_output, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired as error:
            error.cmd = argv
            raise
        result = subprocess.CompletedProcess(argv, process.returncode, process.stdout, process.stderr)
        if check:
            result.check_returncode()
        return result
