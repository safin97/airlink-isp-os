"""Launch the same local first-owner/network wizard used by the boot console."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from console.console import firstboot

if __name__=='__main__':
    if os.geteuid()!=0:
        raise SystemExit('Run first-boot setup from the local root-controlled console')
    firstboot()
