"""Choose direct execution or initialization in a separate Bash process."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil


@dataclass(frozen=True)
class MEGAlibRuntime:
    """MEGAlib runtime selection, independent of individual tool options.

    Use :meth:`direct` for an already initialized environment, or
    :meth:`from_setup_script` to source a trusted Bash script in a child process.
    The parent process's environment is never modified.
    """

    setup_script: Path | None = None
    bash: str = "bash"

    @classmethod
    def direct(cls):
        """Execute the tool directly using the current environment."""
        return cls()

    @classmethod
    def from_setup_script(cls, path, *, bash="bash"):
        """Source a trusted environment script, then exec the tool in that Bash."""
        return cls(Path(path).expanduser().resolve(), bash)

    def launch(self, command, executable_record):
        env = os.environ.copy()
        if self.setup_script is None:
            executable = shutil.which(command[0])
            if executable is None:
                raise FileNotFoundError(
                    f"Cannot find {command[0]!r}; initialize MEGAlib or configure "
                    "MEGAlibRuntime.from_setup_script(...)"
                )
            executable = str(Path(executable).resolve())
            executable_record.write_text(executable + "\n")
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
        # Fixed shell program: paths and tool arguments are positional parameters,
        # never interpolated into shell syntax. Script stdout stays in stdout.log.
        program = '''source "$1"
setup_status=$?
if [ "$setup_status" -ne 0 ]; then
    printf 'MEGAlib setup failed with status %s\\n' "$setup_status" >&2
    exit "$setup_status"
fi
shift
record="$1"
shift
command -v -- "$1" > "$record" || exit 127
exec "$@"
'''
        return [bash, "--noprofile", "--norc", "-c", program, "megalibpy",
                str(self.setup_script), str(executable_record), *command], env
