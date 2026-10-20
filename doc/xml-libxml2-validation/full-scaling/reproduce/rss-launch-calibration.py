"""Check Linux wait4 RSS accounting before/after parent allocation; no timed cells."""
from pathlib import Path
import subprocess,os,json,datetime
root=Path('/scratch/kohlbach/openms-libxml2-scaling-20261020-01a153cb');assert (root/'results/PIPELINE_EXIT_STATUS').read_text().strip()=='0';rows=[];allocation=None
for size in [0,128*1024*1024]:
 if size:allocation=bytearray(size)
 parent=int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
 p=subprocess.Popen([str(root/'benchmark-build/xml_benchmark_launcher'),'/bin/true'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);_,status,usage=os.wait4(p.pid,0);p.returncode=os.waitstatus_to_exitcode(status);assert p.returncode==0
 rows.append({'parent_allocation_bytes':size,'parent_resident_bytes':parent,'child_wait4_max_rss_bytes':usage.ru_maxrss*1024})
(root/'results/rss-launch-calibration.json').write_text(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'probe':'Same launcher and Popen/wait4 machinery, target /bin/true; checks whether parent address-space RSS can impose a pre-exec peak floor. No canonical timing records are changed.','results':rows},indent=2)+'\n');print(json.dumps(rows,indent=2))
