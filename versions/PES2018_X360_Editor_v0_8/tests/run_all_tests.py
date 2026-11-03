"""Testes offline da edição local e do importador PlayersDB."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/"tests"))
import test_atomic_save, test_playersdb_local, test_playersdb_apply

def main():
    test_playersdb_local.main()
    test_atomic_save.main()
    test_playersdb_apply.main()
    print("TODOS OS TESTES OFFLINE PASSARAM.")
if __name__=="__main__": main()
