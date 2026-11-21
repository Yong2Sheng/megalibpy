"""Stream native output, optionally retaining everything from the last summary marker."""

from threading import Thread


class StreamLog(Thread):
    def __init__(self, stream, path, mode):
        super().__init__(daemon=True)
        self.stream, self.path, self.mode = stream, path, mode
        self.seen = 0
        self.error = None
        self.summary_found = False
        self.retained = 0

    def run(self):
        output = None
        # Keep only enough undecided bytes to recognize a marker split across
        # reads. This is a parser overlap, never a limit on retained log content.
        marker = b"\nSummary for run "
        overlap = len(marker) - 1
        pending = b"\n"
        try:
            if self.mode == "full":
                output = self.path.open("wb")
            while chunk := self.stream.read1(65536):
                self.seen += len(chunk)
                if self.mode == "full":
                    output.write(chunk)
                    self.retained += len(chunk)
                    continue
                data = pending + chunk
                boundary = data.rfind(marker)
                if boundary >= 0:
                    if output is not None:
                        output.close()
                    output = self.path.open("wb")
                    self.retained = 0
                    self.summary_found = True
                    data = data[boundary + 1:]
                decided = max(0, len(data) - overlap)
                if self.summary_found and decided:
                    output.write(data[:decided])
                    self.retained += decided
                pending = data[decided:]
            if self.mode == "summary" and self.summary_found:
                output.write(pending)
                self.retained += len(pending)
        except (OSError, ValueError) as exc:
            self.error = exc
            # Continue draining so a child cannot block forever on a full pipe
            # when the filesystem rejects a log write.
            try:
                while self.stream.read1(65536):
                    pass
            except (OSError, ValueError):
                pass
        finally:
            if output is not None:
                try:
                    output.close()
                except OSError as exc:
                    self.error = exc
            self.stream.close()

    def metadata(self):
        return {"mode": self.mode, "bytes_seen": self.seen, "bytes_retained": self.retained,
                "selection": "last_summary_marker_to_eof" if self.mode == "summary" else "all",
                "summary_found": self.summary_found if self.mode == "summary" else None,
                "summary_missing": self.mode == "summary" and not self.summary_found}
