from pathlib import Path
import json,subprocess,shlex,shutil,hashlib,os
root=Path(__file__).resolve().parents[3];out=root/'results/full-scaling/macos';source=root/'OpenMS-libxml2/src/openms/source/FORMAT/HANDLERS/MzMLHandler.cpp';target=out/'MzMLHandler-discard-first.cpp';text=source.read_text()
old='''      if (std::any_of(chars, chars + length,
          [](unsigned char value) { return value >= 0x80; })) { return false; }
      if (skip_spectrum_ || skip_chromatogram_ || !options_.getFillData() || open_tags_.empty()) { return true; }'''
new='''      // Only ignored binary payloads bypass the ASCII scan. Other callbacks
      // preserve the established non-ASCII fallback, including derived handlers.
      if (!open_tags_.empty() && open_tags_.back() == "binary" &&
          (skip_spectrum_ || skip_chromatogram_ || !options_.getFillData())) { return true; }
      if (std::any_of(chars, chars + length,
          [](unsigned char value) { return value >= 0x80; })) { return false; }
      if (skip_spectrum_ || skip_chromatogram_ || !options_.getFillData() || open_tags_.empty()) { return true; }'''
assert text.count(old)==1;target.write_text(text.replace(old,new));diff=subprocess.run(['diff','-u',source,target],capture_output=True,text=True);(out/'handler-discard-first.patch').write_text(diff.stdout)
build=root/'OpenMS-replacement-build';compile_row=next(x for x in json.loads((build/'compile_commands.json').read_text()) if x['file']==str(source));cmd=shlex.split(compile_row['command']);obj=out/'MzMLHandler-discard-first.cpp.o';original_obj=cmd[cmd.index('-o')+1];cmd[cmd.index('-o')+1]=str(obj);cmd[cmd.index('-c')+1]=str(target)
with (out/'handler-compile.log').open('w') as log:subprocess.run(cmd,cwd=build,stdout=log,stderr=subprocess.STDOUT,check=True)
commands=subprocess.check_output(['ninja','-C',build,'-t','commands','OpenMS'],text=True).splitlines();line=next(x for x in commands if ' -dynamiclib ' in x and ' -o lib/libOpenMS.dylib ' in x)
line=line.removeprefix(': && ').removesuffix(' && :');cmd=shlex.split(line);install=out/'handler-discard-first/lib';install.mkdir(parents=True,exist_ok=True);library=install/'libOpenMS.dylib';cmd=[str(obj) if x==original_obj else x for x in cmd];cmd[cmd.index('-o')+1]=str(library)
with (out/'handler-link.log').open('w') as log:subprocess.run(cmd,cwd=build,stdout=log,stderr=subprocess.STDOUT,check=True)
shutil.copy2(build/'lib/libOpenSwathAlgo.dylib',install/'libOpenSwathAlgo.dylib')
(out/'handler-experiment.json').write_text(json.dumps({'source_commit':'8f66b3d921c9512e1e5968f494c77715ff71c696','production_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'experimental_source_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'library_sha256':hashlib.sha256(library.read_bytes()).hexdigest(),'method':'one translation unit rebuilt with original compile command; original library link command with only that object and output path replaced; production library/source untouched'},indent=2)+'\n')
print('Built private discard-before-ASCII-scan variant')
