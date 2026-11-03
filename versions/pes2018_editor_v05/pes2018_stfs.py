"""STFS package detector. This build deliberately does not modify or resign STFS packages."""
def detect_package(path):
    with open(path,'rb') as f: magic=f.read(4)
    return magic in (b'CON ',b'LIVE',b'PIRS')
