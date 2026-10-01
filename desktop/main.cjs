const { app, BrowserWindow, ipcMain, dialog, shell, session } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { DesktopRuntime } = require('./runtime.cjs');
const { ownedUrl, validateHandoff } = require('./security.cjs');

let runtime;
let mainWindow;
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
      const editor = createWindow();
      editor.loadURL(url).then(() => editor.show());
    }
  });
  window.webContents.on('will-redirect', (event, url) => {
    if (!ownedUrl(url, origins)) event.preventDefault();
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (ownedUrl(url, origins)) {
      const child = createWindow();
      child.loadURL(url).then(() => child.show());
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
    const owner = BrowserWindow.fromWebContents(contents);
    const choice = dialog.showSaveDialogSync(owner, { defaultPath: path.basename(item.getFilename()) });
    if (choice) item.setSavePath(choice); else item.cancel();
  });
  ipcMain.handle('desktop:open-editor', async (event, payload) => {
    if (!ownedUrl(event.senderFrame.url, [runtime.oneOrigin]) || !validateHandoff(payload, runtime.editorOrigin)) {
      throw new Error('Invalid modelling handoff');
    }
    if (event.sender !== mainWindow.webContents) return false;
    const editor = createWindow();
    try {
      await editor.loadURL(runtime.oneOrigin);
      const key = `nebula-one:modeling:${payload.handoff_id}`;
      const value = JSON.stringify({ state: payload.state, confirmation_token: payload.confirmation_token });
      await editor.webContents.executeJavaScript(`sessionStorage.setItem(${JSON.stringify(key)}, ${JSON.stringify(value)})`);
      await editor.loadURL(payload.url);
      editor.show();
      return true;
    } catch (error) { editor.destroy(); throw error; }
  });
  mainWindow = createWindow();
  await mainWindow.loadURL(runtime.oneOrigin);
  mainWindow.show();
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
