from pathlib import Path
import subprocess,datetime,time,json,hashlib
root=Path(__file__).resolve().parent
prompt=(root/'review-input.txt').read_text()
command=['claude','--print','--safe-mode','--model','claude-opus-5-5','--effort','high','--permission-mode','plan','--permission-prompts','none','--tools','','--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--no-session-persistence','--output-format','json']
start=time.time()
meta={'requested_model':'claude-opus-5-5','version':subprocess.check_output(['claude','--version'],text=True).strip(),'candidate':json.loads((root/'input-manifest.json').read_text())['candidate'],'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'input_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'mode':'tool-free self-contained complete-diff review; no model fallback configured'}
with (root/'claude-review-output.json').open('w') as out,(root/'claude-review-stderr.txt').open('w') as err:
    try:
        result=subprocess.run(command,input=prompt,text=True,stdout=out,stderr=err,cwd=root,timeout=1800)
        meta['returncode']=result.returncode
    except subprocess.TimeoutExpired:
        meta['error']='review timeout after1800seconds'
meta['elapsed_seconds']=time.time()-start
try:
    output=json.loads((root/'claude-review-output.json').read_text())
    meta['reported_models']=list(output.get('modelUsage',{}))
    meta['is_error']=output.get('is_error')
    (root/'claude-findings.md').write_text(output.get('result','')+'\n')
except (ValueError,TypeError):
    meta['output_parse_error']=True
(root/'claude-review-run.json').write_text(json.dumps(meta,indent=2)+'\n')
print(json.dumps(meta))
