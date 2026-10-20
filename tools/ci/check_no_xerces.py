#!/usr/bin/env python3
"""Reject a reintroduced Xerces dependency in product sources and linked OpenMS."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--build-dir', type=Path)
    args = parser.parse_args()
    source = args.source_dir
    forbidden = re.compile(r'#\s*include\s*[<"]xercesc/|\bxercesc\s*::|\bXERCES_CPP_NAMESPACE')
    failures = []
    for path in (source / 'src').rglob('*'):
        if path.suffix not in ('.h', '.hpp', '.cpp') or {'extern', 'thirdparty', 'data'} & set(path.relative_to(source).parts):
            continue
        if forbidden.search(path.read_text(encoding='utf-8')):
            failures.append(str(path.relative_to(source)))
    manifest = json.loads((source / 'vcpkg.json').read_text())
    names = [item if isinstance(item, str) else item['name'] for item in manifest['dependencies']]
    if 'xerces-c' in names:
        failures.append('vcpkg.json: xerces-c dependency')
    for path in [source / 'src/openms/CMakeLists.txt', source / 'cmake/cmake_findExternalLibs.cmake']:
        if re.search(r'XercesC::|find_package\(XercesC', path.read_text()):
            failures.append(str(path.relative_to(source)))
    if args.build_dir:
        libraries = set()
        for pattern in ('**/libOpenMS*.dylib', '**/libOpenMS.so*', '**/OpenMS.dll'):
            libraries.update(path.resolve() for path in args.build_dir.glob(pattern) if path.is_file())
        if not libraries:
            failures.append('No built OpenMS library found')
        for library in sorted(libraries):
            if sys.platform == 'darwin':
                command = ['otool', '-L', str(library)]
            elif sys.platform == 'win32':
                command = ['dumpbin', '/DEPENDENTS', str(library)]
            else:
                command = ['ldd', str(library)]
            try:
                links = subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)
            except (OSError, subprocess.CalledProcessError) as error:
                failures.append(f'{library}: could not inspect dependencies with {command[0]}: {error}')
                continue
            if re.search(r'\b(?:lib)?xerces[-_A-Za-z0-9.]*\.(?:dylib|so(?:\.\d+)*|dll)\b', links, re.IGNORECASE):
                failures.append(str(library) + ': linked Xerces dependency')
    if failures:
        parser.exit(1, 'Xerces removal check failed:\n' + '\n'.join(failures) + '\n')
    print('No Xerces dependency in product sources, manifest or checked OpenMS libraries.')


if __name__ == '__main__':
    main()
