"""Choose direct execution or initialization in a separate Bash process."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import re


@dataclass(frozen=True)
class MEGAlibRuntime:
    """MEGAlib runtime selection, independent of individual tool options.

    Use :meth:`direct` for an already initialized environment, or
    :meth:`from_setup_script` to source a trusted Bash script in a child process.
    The parent process's environment is never modified.

    Parameters
    ----------
    setup_script : pathlib.Path or None, optional
        Absolute path to a trusted Bash initialization script. ``None`` selects
        direct execution. Prefer the factory methods to constructing this
        dataclass directly; :meth:`from_setup_script` expands ``~`` and resolves
        relative paths for you.
    bash : str, optional
        Bash command name or executable path, defaulting to ``"bash"``.
        Used only in setup-script mode.

    archive_inputs : bool, optional
        False (default) records native source/configuration bytes in the root
        manifest and removes temporary native input files after execution.
        True retains source/configuration snapshots in inputs/. Setup helpers
        and executable-path handoff files are temporary in both modes.

    Attributes
    ----------
    setup_script : pathlib.Path or None
        Script selected for initialization, or ``None`` in direct mode.
    bash : str
        Bash executable selected for setup-script mode.

    Notes
    -----
    Both modes launch external processes. Setup-script mode removes common
    inherited Python and native-library search paths, then sources the script
    and executes the tool in the same Bash child. The script must establish the
    complete runtime; this is not a container or fully hermetic environment.
    Scripts are executed from their original location so ``BASH_SOURCE``-based
    resource lookup continues to work. Only load scripts you trust.
    """

    setup_script: Path | None = None
    bash: str = "bash"
    archive_inputs: bool = False

    @classmethod
    def direct(cls, *, archive_inputs=False):
        """Select direct execution in the current process environment.

        Parameters
        ----------
        archive_inputs : bool, optional
            Default false stores configuration content in the manifest; true
            retains source/config files. Launch helpers are always temporary.

        Returns
        -------
        MEGAlibRuntime
            Runtime with no setup script. Tool availability is checked later,
            when an execution is prepared; this factory does not launch a tool.

        Examples
        --------
        >>> runtime = MEGAlibRuntime.direct()
        >>> runtime.setup_script is None
        True
        """
        return cls(archive_inputs=archive_inputs)

    @classmethod
    def from_setup_script(cls, path, *, bash="bash", archive_inputs=False):
        """Select environment initialization in a separate Bash child.

        Parameters
        ----------
        path : str or pathlib.Path
            Trusted Bash script to source before executing a tool. ``~`` is
            expanded and relative paths are resolved against the calling
            Python working directory. The script may activate a separate
            Conda environment and must establish MEGAlib's runtime paths.
        bash : str, optional
            Bash executable name or path, defaulting to ``"bash"``. Login and
            interactive startup files are not automatically loaded.
        archive_inputs : bool, optional
            False (default) stores source/configuration content in the manifest;
            true retains their files in inputs/. Helpers remain temporary.

        Returns
        -------
        MEGAlibRuntime
            Runtime containing the resolved script path. This method neither
            sources the script nor verifies its existence. Missing scripts or
            Bash executables are reported when an execution is prepared.

        Notes
        -----
        Environment changes occur only in the child process. The calling
        Python process remains in its original environment. The initialization
        script and tool arguments are passed as positional parameters rather
        than interpolated into shell syntax.

        Examples
        --------
        >>> runtime = MEGAlibRuntime.from_setup_script("~/initialize-megalib.sh")
        >>> runtime.setup_script.is_absolute()
        True
        """
        return cls(Path(path).expanduser().resolve(), bash, archive_inputs)

    def launch(self, command, executable_record, *, tool_environment=None):
        """Build subprocess arguments and a child environment for an executor.

        Parameters
        ----------
        command : sequence of str
            Nonempty argument sequence whose first item names the tool.
        executable_record : pathlib.Path
            Destination for the resolved executable path. Its parent directory
            must exist. Direct mode writes it immediately; setup-script mode
            writes it from the Bash child just before ``exec``. Setup mode also
            creates launch.sh beside this file in the executor's temporary
            directory, avoiding multiline shell argument lists. Both files are
            removed after the command; executable identity goes to the manifest.
        tool_environment : dict of str to str or None, optional
            Overrides applied only to the native tool, after setup completes.
            ``None`` leaves the initialized environment unchanged.

        Returns
        -------
        argv : list of str
            Arguments for ``subprocess.Popen`` with ``shell=False``.
        env : dict of str to str
            Child environment copied from the parent, with setup-mode search
            paths removed as described in the class notes.

        Raises
        ------
        FileNotFoundError
            The direct-mode tool, setup script, or Bash executable cannot be
            found. Setup-mode tool discovery occurs in the child instead.
        OSError
            The direct-mode executable record cannot be written.

        Notes
        -----
        This is a low-level executor interface. It does not launch a process;
        normal users select a runtime and pass it to ``Cosima`` instead.
        """
        env = os.environ.copy()
        overrides = dict(tool_environment or {})
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
               or not isinstance(value, str) or "\0" in value
               for key, value in overrides.items()):
            raise ValueError("Invalid tool environment variable")
        if self.setup_script is None:
            executable = shutil.which(command[0])
            if executable is None:
                raise FileNotFoundError(
                    f"Cannot find {command[0]!r}; initialize MEGAlib or configure "
                    "MEGAlibRuntime.from_setup_script(...)"
                )
            executable = str(Path(executable).resolve())
            executable_record.write_text(executable + "\n")
            env.update(overrides)
            return [executable, *command[1:]], env

        if not self.setup_script.is_file():
            raise FileNotFoundError(f"Missing setup script: {self.setup_script}")
        bash = shutil.which(self.bash)
        if bash is None:
            raise FileNotFoundError(f"Cannot find Bash: {self.bash}")
        # Remove Python/native-library search paths inherited from the analysis
        # environment. Keep Conda activation bookkeeping so its own hooks can run.
        for key in (
            "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
            "LIBRARY_PATH", "CPLUS_INCLUDE_PATH", "C_INCLUDE_PATH",
            "CMAKE_PREFIX_PATH", "PKG_CONFIG_PATH", "ROOTSYS", "ROOT_INCLUDE_PATH",
            "MEGALIB",
        ):
            env.pop(key, None)
        # Use a real script rather than a multiline `bash -c` argument. ROOT
        # 6.40.04 inspects /proc/$$/cmdline with line-oriented cut; newlines in
        # argv can make its shell detector consume our bootstrap commands.
        # Paths and tool arguments remain separate positional parameters.
        program = '''source "$1"
setup_status=$?
if [ "$setup_status" -ne 0 ]; then
    printf 'MEGAlib setup failed with status %s\\n' "$setup_status" >&2
    exit "$setup_status"
fi
shift
record="$1"
shift
count="$1"
shift
while [ "$count" -gt 0 ]; do
    export "$1" || exit 125
    shift
    count=$((count - 1))
done
command -v -- "$1" > "$record" || exit 127
exec "$@"
'''
        bootstrap = executable_record.parent / ("launch.sh" if executable_record.name == "executable.txt" else executable_record.stem + ".launch.sh")
        bootstrap.write_text(program, encoding="utf-8")
        return [bash, "--noprofile", "--norc", str(bootstrap),
                str(self.setup_script), str(executable_record), str(len(overrides)),
                *(f"{key}={value}" for key, value in overrides.items()), *command], env
