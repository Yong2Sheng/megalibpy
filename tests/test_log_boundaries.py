"""Summary boundaries are semantic markers, never byte retention limits."""

from megalibpy.execution.logs import StreamLog


class Chunks:
    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def read1(self, size):
        return next(self.chunks, b'')

    def close(self):
        pass


def test_summary_over_70_kib_is_preserved_including_important_prefix(tmp_path):
    prefix = b'IMPORTANT FIRST SIX KIB\n' * 350
    summary = b'Summary for run Burst\n' + prefix + b'physics statistics\n' * 7000 + b'Graphics systems deleted.\n'
    assert len(summary) > 70 * 1024
    path = tmp_path/'summary.log'
    stream = Chunks([b'event record\n' * 100000, b'\nSum', b'mary for ', b'run Burst\n',
                     prefix, b'physics statistics\n' * 7000, b'Graphics systems deleted.\n'])
    capture = StreamLog(stream, path, 'summary')
    capture.run()
    assert capture.error is None
    assert path.read_bytes() == summary
    assert capture.metadata()['bytes_retained'] == len(summary)
    assert capture.metadata()['summary_found']
    assert 'limit_bytes' not in capture.metadata()


def test_last_summary_marker_replaces_previous_block(tmp_path):
    path = tmp_path/'summary.log'
    capture = StreamLog(Chunks([b'Summary for run Old\nold data\n', b'long footer\n',
                                b'Summary for', b' run New\nnew data\n']), path, 'summary')
    capture.run()
    assert capture.error is None
    assert path.read_bytes() == b'Summary for run New\nnew data\n'


def test_non_boundary_words_do_not_start_a_summary(tmp_path):
    path = tmp_path/'summary.log'
    capture = StreamLog(Chunks([b'event text says Summary for run Wrong\n']), path, 'summary')
    capture.run()
    assert not path.exists()
    assert capture.metadata()['summary_missing']
    assert capture.metadata()['bytes_retained'] == 0
