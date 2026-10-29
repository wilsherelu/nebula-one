// Start only the exact packaged runtime, against caller-owned acceptance storage.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const {spawnSync}=require('node:child_process'),asar=require('@electron/asar');
async function main(){
  const installation=path.resolve(process.argv[2]),data=path.resolve(process.argv[3]),out=path.resolve(process.argv[4]);
  fs.mkdirSync(out,{recursive:true});const asarPath=path.join(installation,'resources/app.asar');
  const module=new Module(asarPath);module.filename=asarPath;module._compile(asar.extractFile(asarPath,'runtime.cjs').toString('utf8'),asarPath);
  const runtime=new module.exports.DesktopRuntime(path.join(installation,'resources/runtime'),data);
  try{const origin=await runtime.start();const evidence=JSON.parse(fs.readFileSync(path.join(data,'four-task-http.json')));
    const snapshots=evidence.filter(row=>row.method==='POST'&&row.route.endsWith('/solve'));
    const mfa=snapshots.find(row=>row.result.provider_receipt.analysis_task==='mfa');
    const cbam=snapshots.find(row=>row.result.provider_receipt.analysis_task==='cbam');
    if(!mfa||!cbam)throw Error('Exact persisted MFA and CBAM task receipts required');
    const fixture={base:origin.oneOrigin,app:mfa.result.application_id,mfa:mfa.result.id,cbam:cbam.result.id};
    const file=path.join(out,'fixture.json');fs.writeFileSync(file,JSON.stringify(fixture));
    const child=spawnSync(process.execPath,[path.resolve('../scripts/ui_result_stability_acceptance.mjs'),file,out],{stdio:'inherit'});
    if(child.status!==0)throw Error('Result browser acceptance failed');
  }finally{await runtime.stop();}
}
main().catch(error=>{console.error(error);process.exitCode=1});
