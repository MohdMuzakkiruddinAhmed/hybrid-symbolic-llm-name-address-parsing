"""Use Python's standard Windows-version fallback before running a study script.

This local environment's WMI query blocks SDK user-agent initialization for about
120 seconds. The launcher changes only OS-version discovery, not study sources,
model arguments, prompts, references, routing or spending policy. The fallback
uses sys.getwindowsversion/registry as implemented by installed Python 3.13.
"""

from pathlib import Path
import platform
import runpy
import sys

if sys.platform == "win32":
    platform._wmi = None
target = Path(sys.argv[1]).resolve()
if target.parent != Path(__file__).resolve().parent:
    raise ValueError("launcher only accepts scripts in this research workspace")
sys.argv = [str(target), *sys.argv[2:]]
runpy.run_path(str(target), run_name="__main__")
