"""Drain native pipes concurrently, with bounded-memory tail/summary capture."""

from threading import Thread


class StreamLog(Thread):
    def __init__(self, stream, path, mode, limit):
        super().__init__(daemon=True)
        self.stream, self.path, self.mode, self.limit = stream, path, mode, limit
        self.seen = 0
        self.buffer = bytearray()
        self.error = None
        self.summary_found = False
        self.retained = 0

    def run(self):
        output = None
        try:
            if self.mode == "full":
                try:
                    output = self.path.open("wb")
                except OSError as exc:
                    self.error = exc
            while chunk := self.stream.read1(65536):
                self.seen += len(chunk)
                if self.mode == "full":
                    if output is not None:
                        try:
                            output.write(chunk)
                            self.retained += len(chunk)
                        except OSError as exc:
                            self.error = exc
                            try:
                                output.close()
                            except OSError:
                                pass
                            output = None
                else:
                    self.buffer.extend(chunk)
                    if len(self.buffer) > self.limit:
                        del self.buffer[:-self.limit]
            if self.mode != "full" and self.buffer:
                if self.mode == "summary":
                    marker = b"Summary for run "
                    offset = self.buffer.rfind(b"\n" + marker)
                    if offset >= 0:
                        del self.buffer[:offset + 1]
                        self.summary_found = True
                    elif self.buffer.startswith(marker):
                        self.summary_found = True
                self.path.write_bytes(self.buffer)
                self.retained = len(self.buffer)
        except (OSError, ValueError) as exc:
            self.error = exc
        finally:
            if output is not None:
                try:
                    output.close()
                except OSError as exc:
                    self.error = exc
            self.stream.close()
            self.buffer.clear()

    def metadata(self):
        return {"mode": self.mode, "limit_bytes": self.limit if self.mode != "full" else None, "bytes_seen": self.seen, "bytes_retained": self.retained,
                "truncated": self.retained < self.seen,
                "summary_found": self.summary_found if self.mode == "summary" else None,
                "summary_fallback": "bounded_tail" if self.mode == "summary" and not self.summary_found else None}
