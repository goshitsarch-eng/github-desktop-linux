"""Desktop create-repository helpers: name sanitization, README, gitignore, license, attributes."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

NO_GITIGNORE = "None"
NO_LICENSE = "None"

# Desktop `sanitizedRepositoryName`: drop emoji, then keep JS `\w` plus `.` and `-`.
_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f900-\U0001f9ff"
    "\U00002600-\U000026ff"
    "]+",
    flags=re.UNICODE,
)


def sanitized_repository_name(name: str) -> str:
    r"""Desktop `sanitizedRepositoryName`: emoji -> '-', then JS `[^\w.-]` -> '-'."""
    cleaned = _EMOJI_RE.sub("-", name)
    return re.sub(r"[^A-Za-z0-9_.-]", "-", cleaned)


def write_default_readme(path: str, name: str, description: str | None = None) -> None:
    """Desktop `writeDefaultReadme`."""
    body = f"# {name}\n{description}\n" if description is not None else f"# {name}\n"
    Path(path, "README.md").write_text(body, encoding="utf-8")


def classify_create_path(full_path: str) -> tuple[bool, bool]:
    """Return `(is_repository, is_subfolder_of_repository)` for the create-repo dialog."""
    from .git.ops import get_repository_type

    info = get_repository_type(full_path)
    kind = info.get("kind")
    if kind == "unsafe":
        return os.path.isdir(os.path.join(full_path, ".git")), False
    if kind == "bare":
        return True, False
    if kind != "regular":
        return False, False
    top = info.get("topLevelWorkingDirectory") or ""
    is_repo = os.path.abspath(top) == os.path.abspath(full_path)
    return is_repo, not is_repo


def write_git_attributes(path: str) -> None:
    """Desktop `writeGitAttributes`."""
    target = Path(path, ".gitattributes")
    if target.exists():
        return
    target.write_text("# Auto detect text files and perform LF normalization\n* text=auto\n", encoding="utf-8")


GITIGNORE_TEMPLATES: dict[str, str] = {
    "Python": """\
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
.venv/
venv/
ENV/
.env
.mypy_cache/
.pytest_cache/
.ruff_cache/
""",
    "Node": """\
logs
*.log
npm-debug.log*
yarn-debug.log*
yarn-error.log*
node_modules/
.npm
.eslintcache
.yarn-integrity
.env
.cache
dist/
coverage/
""",
    "Go": """\
*.exe
*.exe~
*.dll
*.so
*.dylib
*.test
*.out
vendor/
go.work
""",
    "Rust": """\
/target/
**/*.rs.bk
Cargo.lock
""",
    "Java": """\
*.class
*.jar
*.war
*.ear
hs_err_pid*
.idea/
*.iml
target/
.gradle/
build/
""",
    "C++": """\
*.o
*.obj
*.exe
*.dll
*.so
*.dylib
*.a
*.lib
*.out
*.app
CMakeFiles/
CMakeCache.txt
cmake-build-*/
""",
    "C": """\
*.o
*.ko
*.obj
*.elf
*.lib
*.a
*.la
*.lo
*.dll
*.so
*.so.*
*.dylib
*.exe
*.out
*.app
""",
    "Swift": """\
.build/
Packages/
*.xcodeproj
xcuserdata/
DerivedData/
.swiftpm/
""",
    "Kotlin": """\
.gradle/
build/
*.iml
.idea/
local.properties
""",
    "Ruby": """\
*.gem
*.rbc
.bundle/
vendor/bundle/
.log/
tmp/
.sass-cache/
coverage/
""",
    "PHP": """\
/vendor/
composer.phar
.env
.phpunit.result.cache
""",
    "Unity": """\
[Ll]ibrary/
[Tt]emp/
[Oo]bj/
[Bb]uild/
[Bb]uilds/
[Ll]ogs/
[Uu]ser[Ss]ettings/
*.csproj
*.unityproj
*.sln
*.pidb
*.booproj
*.svd
*.pdb
*.mdb
""",
    "Android": """\
*.iml
.gradle/
/local.properties
/.idea/
.DS_Store
/build/
/captures/
*.apk
*.ap_
""",
    "macOS": """\
.DS_Store
.AppleDouble
.LSOverride
._*
.Spotlight-V100
.Trashes
""",
    "Linux": """\
*~
.fuse_hidden*
.directory
.Trash-*
.nfs*
""",
    "Windows": """\
Thumbs.db
ehthumbs.db
Desktop.ini
$RECYCLE.BIN/
*.cab
*.msi
*.msix
*.msm
*.msp
""",
    "VisualStudio": """\
[Dd]ebug/
[Rr]elease/
x64/
x86/
[Bb]in/
[Oo]bj/
.vs/
*.user
*.suo
*.userosscache
*.sln.docstates
[Pp]ackages/
""",
    "JupyterNotebooks": """\
.ipynb_checkpoints
*/.ipynb_checkpoints/*
profile_default/
ipython_config.py
""",
    "Terraform": """\
**/.terraform/*
*.tfstate
*.tfstate.*
crash.log
*.tfvars
override.tf
override.tf.json
.terraformrc
terraform.rc
""",
    "Docker": """\
**/.dockerignore
**/docker-compose.override.yml
""",
}


GITIGNORE_DATA_DIR = Path(__file__).resolve().parent / "data" / "gitignore"


def _gitignore_from_disk(name: str) -> str | None:
    path = GITIGNORE_DATA_DIR / f"{name}.gitignore"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return None


def gitignore_names() -> list[str]:
    """Desktop `getGitIgnoreNames` from vendored github/gitignore templates."""
    names = []
    if GITIGNORE_DATA_DIR.is_dir():
        names = [path.stem for path in GITIGNORE_DATA_DIR.glob("*.gitignore")]
    if not names:
        names = list(GITIGNORE_TEMPLATES)
    return sorted(names)


def write_named_gitignore(path: str, name: str) -> None:
    """Desktop `writeGitIgnore`."""
    text = _gitignore_from_disk(name) or GITIGNORE_TEMPLATES.get(name)
    if not text:
        raise ValueError(f"Unknown gitignore: {name}. Only names returned from gitignore_names() can be used.")
    Path(path, ".gitignore").write_text(text, encoding="utf-8")


@dataclass(frozen=True)
class LicenseTemplate:
    name: str
    featured: bool
    body: str
    hidden: bool = False


LICENSE_DATA_DIR = Path(__file__).resolve().parent / "data" / "licenses"


def _parse_license_file(path: Path) -> LicenseTemplate | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    rest = text[3:]
    end = rest.find("\n---")
    if end < 0:
        return None
    header, body = rest[:end], rest[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in header.splitlines():
        if not line or line[0] in " \t-" or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    name = meta.get("title") or path.stem
    featured = meta.get("featured", "false").lower() == "true"
    hidden = meta.get("hidden", "false").lower() == "true"
    return LicenseTemplate(name=name, featured=featured, body=body, hidden=hidden)


def _licenses_from_disk() -> list[LicenseTemplate]:
    """Load choosealicense.com `_licenses` files vendored under data/licenses."""
    if not LICENSE_DATA_DIR.is_dir():
        return []
    licenses = []
    for path in sorted(LICENSE_DATA_DIR.glob("*.txt")):
        parsed = _parse_license_file(path)
        if parsed is not None:
            licenses.append(parsed)
    return licenses


LICENSE_TEMPLATES: tuple[LicenseTemplate, ...] = (
    LicenseTemplate(
        name="MIT License",
        featured=True,
        body="""\
MIT License

Copyright (c) {year} {fullname}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
""",
    ),
    LicenseTemplate(
        name="Apache License 2.0",
        featured=True,
        body="""\
Apache License
Version 2.0, January 2004
http://www.apache.org/licenses/

Copyright {year} {fullname}

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
""",
    ),
    LicenseTemplate(
        name="GNU General Public License v3.0",
        featured=True,
        body="""\
GNU GENERAL PUBLIC LICENSE
Version 3, 29 June 2007

Copyright (C) {year} {fullname}

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
""",
    ),
    LicenseTemplate(
        name="BSD 3-Clause \"New\" or \"Revised\" License",
        featured=False,
        body="""\
BSD 3-Clause License

Copyright (c) {year}, {fullname}

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
""",
    ),
    LicenseTemplate(
        name="The Unlicense",
        featured=False,
        body="""\
This is free and unencumbered software released into the public domain.

Anyone is free to copy, modify, publish, use, compile, sell, or
distribute this software, either in source code form or as a compiled
binary, for any purpose, commercial or non-commercial, and by any
means.

In jurisdictions that recognize copyright laws, the author or authors
of this software dedicate any and all copyright interest in the
software to the public domain. We make this dedication for the benefit
of the public at large and to the detriment of our heirs and
successors. We intend this dedication to be an overt act of
relinquishment in perpetuity of all present and future rights to this
software under copyright law.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.

For more information, please refer to <https://unlicense.org>
""",
    ),
)


def license_templates() -> list[LicenseTemplate]:
    """Desktop `getLicenses`: featured first, then remaining by name."""
    licenses = _licenses_from_disk() or list(LICENSE_TEMPLATES)
    featured = [item for item in licenses if item.featured]
    rest = sorted((item for item in licenses if not item.featured), key=lambda item: item.name)
    return featured + rest


def write_license(path: str, license: LicenseTemplate, *, fullname: str, email: str, project: str, description: str = "") -> None:
    """Desktop `writeLicense`: replace {token} and [token] placeholders."""
    body = license.body
    fields = {
        "fullname": fullname or "Copyright Owner",
        "email": email or "",
        "project": project,
        "description": description,
        "year": str(date.today().year),
    }
    for token, value in fields.items():
        body = body.replace(f"[{token}]", f"{{{token}}}")
        body = body.replace(f"{{{token}}}", value)
    Path(path, "LICENSE").write_text(body, encoding="utf-8")
