const { contextBridge, ipcRenderer } = require('electron');
const read = key => process.argv.find(value => value.startsWith(`--${key}=`))?.slice(key.length + 3);
contextBridge.exposeInMainWorld('__NEBULA_DESKTOP__', {
  apiBase: `${read('editor-origin')}/api`,
  oneOrigin: read('one-origin'),
  integratedOne: true,
  setEditorDirty: dirty => ipcRenderer.send('desktop:editor-dirty', dirty),
  returnToOne: () => ipcRenderer.invoke('desktop:return-one')
});
contextBridge.exposeInMainWorld('__NEBULA_ONE_DESKTOP__', {
  openEditor: payload => ipcRenderer.invoke('desktop:open-editor', payload),
  openEditorHome: lang => ipcRenderer.invoke('desktop:editor-home', lang)
});
