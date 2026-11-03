import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
"""Teste offline do salvamento atomico e backup do editor."""
import tempfile
from pathlib import Path
import pes2018_editor_xbox360_v0_8 as app


class DummyStatus:
    def set(self, value):
        self.value = value


def main():
    original = app.messagebox.showinfo
    try:
        app.messagebox.showinfo = lambda *args, **kwargs: None
        editor = app.Editor.__new__(app.Editor)
        editor.data = bytearray(b"data-bin-novo")
        editor.dirty = True
        editor.path = None
        editor.status = DummyStatus()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "data.bin"
            target.write_bytes(b"data-bin-anterior")
            editor._atomic_save(str(target))
            assert target.read_bytes() == b"data-bin-novo"
            assert Path(str(target) + ".bak").read_bytes() == b"data-bin-anterior"
            assert editor.dirty is False
            fresh = Path(folder) / "novo.bin"
            editor._atomic_save(str(fresh))
            assert fresh.read_bytes() == b"data-bin-novo"
            assert not Path(str(fresh) + ".bak").exists()
        print("PASS: gravação verificada, backup .bak e novo destino sem backup desnecessário.")
    finally:
        app.messagebox.showinfo = original


if __name__ == "__main__":
    main()
