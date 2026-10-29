// Isolated acceptance through the installed app.asar and installed One/LCA backends.
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const {spawn} = require('node:child_process');
const asar = require('@electron/asar');
async function main() {
  const [installation,data,out]=process.argv.slice(2).map(p=>path.resolve(p));
  fs.mkdirSync(out,{recursive:true});
  const packed=path.join(installation,'resources/app.asar');
  const module=new Module(packed);module.filename=packed;
  module._compile(asar.extractFile(packed,'runtime.cjs').toString('utf8'),packed);
  const {DesktopRuntime,availablePort}=module.exports;
  const runtime=new DesktopRuntime(path.join(installation,'resources/runtime'),data);
  try {
    const origins=await runtime.start();
    for (const [script,folder] of [['ui_template_custom_acceptance.mjs','custom'],['visible_browser_acceptance.mjs','template']]) {
      const port=await availablePort(0);
      await new Promise((resolve,reject)=>{
        const child=spawn(process.execPath,[`scripts/${script}`,origins.oneOrigin,String(port),path.join(out,folder)],
          {stdio:'inherit',env:{...process.env,NEBULA_BROWSER_EVIDENCE_DIR:path.join(out,folder)}});
        child.on('error',reject);child.on('exit',code=>code===0?resolve():reject(new Error(`${script}: ${code}`)));
      });
    }
  } finally {await runtime.stop();}
}
main().catch(error=>{console.error(error);process.exitCode=1});
