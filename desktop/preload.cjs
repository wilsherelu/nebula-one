const { contextBridge, ipcRenderer } = require('electron');
const read = key => process.argv.find(value => value.startsWith(`--${key}=`))?.slice(key.length + 3);
contextBridge.exposeInMainWorld('__NEBULA_DESKTOP__', {
  apiBase: `${read('editor-origin')}/api`,
  oneOrigin: read('one-origin')
});
contextBridge.exposeInMainWorld('__NEBULA_ONE_DESKTOP__', {
  openEditor: payload => ipcRenderer.invoke('desktop:open-editor', payload)
});
