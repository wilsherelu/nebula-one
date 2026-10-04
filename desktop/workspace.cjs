// Two isolated renderers share one native window. Switching never reloads a draft.
const { WebContentsView, dialog } = require('electron');
const path = require('node:path');
const { ownedUrl } = require('./security.cjs');

class DesktopWorkspace {
  constructor(window, runtime, external) {
    this.window = window;
    this.runtime = runtime;
    this.dirty = false;
    this.editor = new WebContentsView({webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'), sandbox: true,
      contextIsolation: true, nodeIntegration: false,
      additionalArguments: [`--one-origin=${runtime.oneOrigin}`, `--editor-origin=${runtime.editorOrigin}`],
    }});
    const contents = this.editor.webContents;
    const route = (event, url) => {
      if (ownedUrl(url, [runtime.oneOrigin])) {
        event.preventDefault();
        // A verified handoff return is a new One route. Plain return restores the retained page.
        if (new URL(url).pathname === '/modeling/return') {
          this.showOne();
          void window.loadURL(url);
        } else this.showOne();
      } else if (!ownedUrl(url, [runtime.editorOrigin])) { event.preventDefault(); external(url); }
    };
    contents.on('will-navigate', route);
    contents.on('will-redirect', route);
    contents.setWindowOpenHandler(({url}) => {
      if (ownedUrl(url, [runtime.editorOrigin])) void this.open(url);
      else if (ownedUrl(url, [runtime.oneOrigin])) this.showOne();
      else external(url);
      return {action: 'deny'};
    });
    window.on('resize', () => this.resize());
    window.on('close', event => { if (!this.allowDiscard()) event.preventDefault(); });
    window.on('closed', () => { if (!contents.isDestroyed()) contents.close(); });
  }
  allowDiscard() {
    return !this.dirty || dialog.showMessageBoxSync(this.window, {
      type: 'question', title: 'Nebula LCA',
      message: '模型有未保存的修改 / Unsaved model changes',
      detail: '返回 One 会保留编辑。关闭或打开另一个模型会丢弃未保存修改。 / Switching to One keeps the draft. Closing or opening another model discards unsaved changes.',
      buttons: ['继续编辑 / Keep editing', '放弃修改 / Discard changes'], defaultId: 0, cancelId: 0,
    }) === 1;
  }
  resize() {
    const [width, height] = this.window.getContentSize();
    this.editor.setBounds({x: 0, y: 0, width, height});
  }
  showOne() {
    if (this.visible) this.window.contentView.removeChildView(this.editor);
    this.visible = false;
    this.window.webContents.focus();
  }
  showEditor() {
    if (!this.visible) this.window.contentView.addChildView(this.editor);
    this.visible = true;
    this.resize();
    this.editor.webContents.focus();
  }
  async open(url) {
    if (!ownedUrl(url, [this.runtime.editorOrigin])) throw new Error('Invalid editor origin');
    if (this.editor.webContents.getURL() !== url) {
      if (!this.allowDiscard()) return false;
      await this.editor.webContents.loadURL(url);
      this.dirty = false;
    }
    this.showEditor();
    return true;
  }
  async home(lang = 'zh') {
    if (this.editor.webContents.getURL()) { this.showEditor(); return true; }
    return this.open(`${this.runtime.editorOrigin}/?from_nebula_one=1&lang=${lang}`);
  }
}
module.exports = { DesktopWorkspace };
