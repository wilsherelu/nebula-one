const { app, BrowserWindow, ipcMain, dialog, shell, session, Menu } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { DesktopRuntime } = require('./runtime.cjs');
const { ownedUrl, validateHandoff } = require('./security.cjs');
const { DesktopWorkspace } = require('./workspace.cjs');

let runtime;
let mainWindow;
let workspace;
let quitting = false;
const windows = new Set();
if (process.env.NEBULA_ONE_DESKTOP_TEST_DATA) app.setPath('userData', path.resolve(process.env.NEBULA_ONE_DESKTOP_TEST_DATA));
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (mainWindow) { mainWindow.restore(); mainWindow.focus(); } });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', event => {
    if (!runtime || quitting) return;
    event.preventDefault();
    // Let both renderer draft guards cancel closing before shutting down their services.
    if (mainWindow && !mainWindow.isDestroyed()) { mainWindow.close(); return; }
    quitting = true;
    runtime.stop().finally(() => app.quit());
  });
  app.whenReady().then(start).catch(async error => {
    if (runtime) await runtime.stop();
    dialog.showErrorBox('Nebula One', `${error.message}\nLogs: ${path.join(app.getPath('userData'), 'logs')}`);
    app.exit(1);
  });
}

function createWindow() {
  const window = new BrowserWindow({ width: 1440, height: 960, minWidth: 390, minHeight: 600,
    show: false, autoHideMenuBar: true, title: 'Nebula One',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true,
      nodeIntegration: false, sandbox: true,
      additionalArguments: [`--one-origin=${runtime.oneOrigin}`, `--editor-origin=${runtime.editorOrigin}`] }
  });
  windows.add(window);
  window.on('closed', () => windows.delete(window));
  const origins = [runtime.oneOrigin, runtime.editorOrigin];
  window.webContents.on('will-navigate', (event, url) => {
    if (!ownedUrl(url, origins)) { event.preventDefault(); openExternal(url); }
    else if (window === mainWindow && ownedUrl(url, [runtime.editorOrigin])) {
      event.preventDefault();
      void workspace.open(url);
    }
  });
  window.webContents.on('will-redirect', (event, url) => {
    if (!ownedUrl(url, origins)) event.preventDefault();
  });
  window.webContents.on('will-prevent-unload', event => {
    if (dialog.showMessageBoxSync(window, {type:'question', title:'Nebula One',
      message:'页面有未保存的修改 / Unsaved page changes',
      buttons:['继续编辑 / Keep editing', '离开页面 / Leave page'], defaultId:0, cancelId:0}) === 1) event.preventDefault();
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (ownedUrl(url, origins)) {
      if (ownedUrl(url, [runtime.editorOrigin])) void workspace.open(url);
      else void mainWindow.loadURL(url);
    } else openExternal(url);
    return { action: 'deny' };
  });
  return window;
}

function openExternal(value) {
  try { if (new URL(value).protocol === 'https:') shell.openExternal(value); } catch { /* Invalid navigation is rejected. */ }
}

async function start() {
  const resources = app.isPackaged ? path.join(process.resourcesPath, 'runtime') : path.join(__dirname, 'resources');
  runtime = new DesktopRuntime(resources, app.getPath('userData'));
  await runtime.start();
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  session.defaultSession.on('will-download', async (event, item, contents) => {
    if (!contents || !ownedUrl(contents.getURL(), [runtime.oneOrigin, runtime.editorOrigin])) {
      event.preventDefault(); return;
    }
    const owner = mainWindow;
    const choice = dialog.showSaveDialogSync(owner, { defaultPath: path.basename(item.getFilename()) });
    if (choice) item.setSavePath(choice); else item.cancel();
  });
  ipcMain.handle('desktop:open-editor', async (event, payload) => {
    if (!ownedUrl(event.senderFrame.url, [runtime.oneOrigin]) || !validateHandoff(payload, runtime.editorOrigin)) {
      throw new Error('Invalid modelling handoff');
    }
    if (event.sender !== mainWindow.webContents) return false;
    // Credentials remain in the original One renderer's sessionStorage.
    return workspace.open(payload.url);
  });
  ipcMain.handle('desktop:editor-home', (event, lang) => {
    if (event.sender !== mainWindow.webContents || !ownedUrl(event.senderFrame.url, [runtime.oneOrigin]) || !['zh', 'en'].includes(lang)) throw new Error('Invalid editor request');
    return workspace.home(lang);
  });
  ipcMain.handle('desktop:return-one', event => {
    if (event.sender !== workspace.editor.webContents || !ownedUrl(event.senderFrame.url, [runtime.editorOrigin])) throw new Error('Invalid return request');
    workspace.showOne();
    return true;
  });
  ipcMain.on('desktop:editor-dirty', (event, dirty) => {
    if (event.sender === workspace.editor.webContents && ownedUrl(event.senderFrame.url, [runtime.editorOrigin]) && typeof dirty === 'boolean') workspace.dirty = dirty;
  });
  mainWindow = createWindow();
  workspace = new DesktopWorkspace(mainWindow, runtime, openExternal);
  Menu.setApplicationMenu(Menu.buildFromTemplate([{label:'工作区 / Workspace', submenu:[
    {label:'Nebula One', accelerator:'CmdOrCtrl+1', click:() => workspace.showOne()},
    {label:'Nebula LCA', accelerator:'CmdOrCtrl+2', click:() => void workspace.home()},
  ]}]));
  mainWindow.setAutoHideMenuBar(false);
  await mainWindow.loadURL(runtime.oneOrigin);
  mainWindow.show();
  if (process.argv.includes('--window-smoke')) {
    if (!process.env.NEBULA_ONE_DESKTOP_TEST_DATA || !process.env.NEBULA_ONE_DESKTOP_WINDOW_REPORT) throw new Error('Isolated acceptance paths required');
    await require('./window-acceptance.cjs').accept({app, mainWindow, workspace, runtime});
  }
  // An explicit package acceptance entry reports owned process identities, not credentials.
  if (process.argv.includes('--runtime-smoke')) {
    const file = process.env.NEBULA_ONE_DESKTOP_SMOKE_REPORT;
    if (!file) throw new Error('Smoke report path is required');
    fs.writeFileSync(file, JSON.stringify({ resources, data: app.getPath('userData'),
      ...{ oneOrigin: runtime.oneOrigin, editorOrigin: runtime.editorOrigin, lcaOrigin: runtime.lcaOrigin },
      children: runtime.children.map(child => child.pid), electron: process.versions.electron,
      packaged: app.isPackaged, window: {url:mainWindow.webContents.getURL(),
        preferences:mainWindow.webContents.getLastWebPreferences()} }, null, 2));
    const duration = Number(process.env.NEBULA_ONE_DESKTOP_SMOKE_EXIT_MS);
    if (Number.isSafeInteger(duration) && duration >= 5000 && duration <= 300000) setTimeout(() => app.quit(), duration);
  }
}
