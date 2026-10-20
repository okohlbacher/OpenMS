#!/bin/bash
set -euo pipefail
root=/scratch/kohlbach/openms-libxml2-replacement-20261020-01a153cb
cd "$root"
while ! test -f results/VALIDATION_EXIT_STATUS; do sleep 2; done
test "$(cat results/VALIDATION_EXIT_STATUS)" = 0
test "$(cat results/CLASS_TEST_EXIT_STATUS)" = 0
test -f results/SUPPLEMENTAL_COMPLETE
cp results/source-identity.txt results/build-source-identity.txt
cp results/no-xerces-check.log results/no-xerces-check-fcdc.log
cp results/ci-python-tests.log results/ci-python-tests-fcdc.log
cd source
git fetch "$root/staging/replacement-ci-guard.bundle" '+refs/heads/*:refs/heads/*' > "$root/logs/ci-bundle-fetch.log" 2>&1
git checkout -q --detach 8cf5579a163146a6d7d543b9ec19613909f876ad
git rev-parse HEAD HEAD^{tree} > "$root/results/source-identity.txt"
python3 tools/ci/check_no_xerces.py --build-dir "$root/build" > "$root/results/no-xerces-check.log" 2>&1
python3 -m unittest discover -s tools/ci/tests -p test_check_no_xerces.py > "$root/results/ci-python-tests.log" 2>&1
python3 - <<'PY'
import hashlib,json,subprocess
from pathlib import Path
root=Path('/scratch/kohlbach/openms-libxml2-replacement-20261020-01a153cb');source=root/'source'
before='fcdc7458543e8936a0f8915828860669c7044514';after='8cf5579a163146a6d7d543b9ec19613909f876ad'
def git(*args):return subprocess.check_output(['git','-C',str(source),*args],text=True)
def cpp(ref):
 lines=[l for l in git('ls-tree','-r',ref).splitlines() if Path(l.split('\t',1)[1]).suffix in ('.cpp','.h','.hpp','.ipp','.inc')]
 return hashlib.sha256(('\n'.join(lines)+'\n').encode()).hexdigest()
assert cpp(before)==cpp(after)
assert not git('status','--porcelain','--untracked-files=no')
report={'cpp_build_commit':before,'final_source_guard_commit':after,'cpp_source_tree_sha256':cpp(after),'cpp_source_unchanged':True,'changed_files':git('diff','--name-only',before,after).splitlines(),'linked_library_sha256':hashlib.sha256((root/'build/lib/libOpenMS.so').read_bytes()).hexdigest(),'guard_unit_tests':5}
(root/'results/ci-only-provenance.json').write_text(json.dumps(report,indent=2)+'\n')
PY
touch "$root/results/FINAL_CI_COMPLETE"
