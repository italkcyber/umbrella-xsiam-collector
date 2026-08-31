#!/usr/bin/env python3
"""Regenerate the uploadable integration YAML from the .py + the template.

    python3 build/build.py

Never upload build/integration.template.yml - it contains the @@SCRIPT@@
placeholder and XSIAM will reject it with "SyntaxError: invalid syntax".
"""
import os
import re
import sys

# demisto-sdk's unifier strips these three lines before writing a unified YAML:
# the platform prepends the real demisto / CommonServerPython bindings around the
# script, and `demistomock` does not exist inside the container. Leaving them in
# fails at line 1 with ModuleNotFoundError: No module named 'demistomock'.
DEV_ONLY_IMPORTS = [
    r"import demistomock as demisto[ \t]*(#.*)?",
    r"from CommonServerPython import \*[ \t]*(#.*)?",
    r"from CommonServerUserPython import \*[ \t]*(#.*)?",
]

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
code = open(os.path.join(root, "CiscoUmbrellaS3EventCollector.py")).read().rstrip("\n")
tpl = open(os.path.join(root, "build", "integration.template.yml")).read()
for pattern in DEV_ONLY_IMPORTS:
    code = re.sub(pattern, "", code)
code = code.lstrip("\n")
if "demistomock" in code:
    sys.exit("build failed: demistomock import survived the strip")
indented = "\n".join(("    " + line) if line.strip() else "" for line in code.split("\n"))
out = tpl.replace("  script: '@@SCRIPT@@'", "  script: |-\n" + indented)
if "@@SCRIPT@@" in out:
    sys.exit("build failed: placeholder not replaced")
target = os.path.join(root, "CiscoUmbrellaS3EventCollector.yml")
open(target, "w").write(out)
print(f"wrote {target} ({len(out)} bytes) - this is the file you upload to XSIAM")
