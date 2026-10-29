/** Minimal CDP driver over Node's built-in WebSocket: no third-party dependency, no stub browser. */
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';

function isFile(path) {
  try { return statSync(path).isFile(); } catch { return false; }
}

export async function launchChrome({ port, headless = true, windowSize = '1400,950' }) {
  const candidates = [
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  ];
  const binary = candidates.find(isFile);
  if (!binary) throw new Error(`no chrome/edge binary found among ${candidates.join(', ')}`);
  const userDataDir = mkdtempSync(join(tmpdir(), 'nebula-browser-'));
  const args = [
    headless ? '--headless=new' : '--headless=off',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${userDataDir}`,
    `--window-size=${windowSize}`,
    '--no-first-run', '--no-default-browser-check', '--disable-extensions',
    '--force-device-scale-factor=1', '--lang=zh-CN', 'about:blank',
  ];
  const child = spawn(binary, args, { stdio: ['ignore', 'pipe', 'pipe'] });
  let stderrTail = '';
  child.stderr.on('data', chunk => { stderrTail = (stderrTail + chunk.toString()).slice(-4000); });
  child.stdout.on('data', () => {});
  let wsUrl = null;
  for (let attempt = 0; attempt < 60 && !wsUrl; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`);
      wsUrl = (await response.json()).webSocketDebuggerUrl;
    } catch { await sleep(500); }
  }
  if (!wsUrl) { child.kill(); throw new Error(`chrome did not open a debugging port (stderr: ${stderrTail.trim() || 'empty'})`); }
  return { child, wsUrl, binary, userDataDir, stderrTail: () => stderrTail };
}

export function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

export class Cdp {
  constructor(wsUrl, { sendTimeoutMs = 90000 } = {}) {
    this.ws = new WebSocket(wsUrl);
    this.id = 0;
    this.pending = new Map();
    this.events = [];
    this.droppedEvents = 0;
    this.anomalies = [];
    this.dialogs = [];
    this.sendTimeoutMs = sendTimeoutMs;
    this.ready = new Promise((resolve, reject) => {
      this.ws.addEventListener('open', () => resolve());
      this.ws.addEventListener('error', event => reject(event.error ?? new Error('ws error')));
    });
    this.ws.addEventListener('message', event => {
      let message;
      try { message = JSON.parse(event.data); } catch { return; }
      if (message.id !== undefined && this.pending.has(message.id)) {
        const { resolve, reject, timer } = this.pending.get(message.id);
        clearTimeout(timer);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(`${message.error.message} (${JSON.stringify(message.error.data ?? {})})`));
        else resolve(message.result);
        return;
      }
      // A dirty draft's beforeunload prompt is modal: until it is answered the renderer answers
      // nothing, so Page.navigate and every later Runtime.evaluate on that session look hung. Leaving
      // the page is what the caller asked for, so accept it the way a user clicking 离开 would.
      if (message.method === 'Page.javascriptDialogOpening') {
        const info = message.params ?? {};
        this.dialogs.push({ type: info.type ?? null, text: info.message ?? '', url: info.url ?? null });
        this.send('Page.handleJavaScriptDialog', { accept: true }, message.sessionId ?? this.sessionId)
          .catch(error => this.anomalies.push({ kind: 'dialog_not_handled', error: String(error?.message ?? error) }));
      }
      // A crashed or detached renderer explains a session that stops answering: without recording it, a
      // page that kills its own tab is indistinguishable from a harness timeout.
      if (message.method === 'Inspector.targetCrashed' || message.method === 'Target.targetCrashed'
        || message.method === 'Target.detachedFromTarget') {
        this.anomalies.push({ kind: message.method, sessionId: message.sessionId ?? null, params: message.params ?? null });
      }
      // Only keep the two event kinds consoleErrors() reads. An unbounded buffer turns a chatty page
      // (a graph canvas logging per frame) into message-parse work that starves the awaited replies,
      // which reads as a hung harness rather than as the page it was meant to observe.
      if (message.method === 'Runtime.exceptionThrown'
        || (message.method === 'Log.entryAdded' && message.params?.entry?.level === 'error')) {
        if (this.events.length < 500) this.events.push(message);
        else this.droppedEvents += 1;
      }
    });
    // A dropped socket must fail every in-flight call: without this a lost reply leaves the harness
    // awaiting forever and the run looks hung instead of reporting what it could not observe.
    for (const type of ['close', 'error']) {
      this.ws.addEventListener(type, () => this._failPending(new Error(`cdp websocket ${type}`)));
    }
  }

  _failPending(error) {
    for (const [, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(error);
    }
    this.pending.clear();
  }

  send(method, params = {}, sessionId, timeoutMs = this.sendTimeoutMs) {
    this.id += 1;
    const id = this.id;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        if (!this.pending.has(id)) return;
        this.pending.delete(id);
        reject(new Error(`cdp ${method} did not answer within ${timeoutMs}ms`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.ws.send(JSON.stringify(payload));
    });
  }

  async newTab() {
    const { targetId } = await this.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await this.send('Target.attachToTarget', { targetId, flatten: true });
    this.sessionId = sessionId;
    this.targetId = targetId;
    await this.send('Page.enable', {}, sessionId);
    await this.send('Runtime.enable', {}, sessionId);
    await this.send('Log.enable', {}, sessionId);
    // Crash notification for this target; a failure here must not abort the session.
    await this.send('Inspector.enable', {}, sessionId).catch(() => {});
    return sessionId;
  }

  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression, returnByValue: true, awaitPromise: true, userGesture: true,
    }, this.sessionId);
    if (result.exceptionDetails) {
      throw new Error(`evaluate failed: ${result.exceptionDetails.text} ${JSON.stringify(result.exceptionDetails.exception?.description ?? '')}`);
    }
    return result.result.value;
  }

  async setViewport({ width, height, deviceScaleFactor = 1 }) {
    await this.send('Emulation.setDeviceMetricsOverride', {
      width, height, deviceScaleFactor, mobile: false,
    }, this.sessionId);
  }

  async pressKey(key, { code = key, windowsVirtualKeyCode = 0 } = {}) {
    for (const type of ['keyDown', 'keyUp']) {
      await this.send('Input.dispatchKeyEvent', { type, key, code, windowsVirtualKeyCode }, this.sessionId);
    }
  }

  async navigate(url, { timeoutMs = 30000, settleMs = 700, commandTimeoutMs = 20000 } = {}) {
    this.events.length = 0;
    try {
      await this.send('Page.navigate', { url }, this.sessionId, commandTimeoutMs);
    } catch (error) {
      // Observed: the browser commits the navigation (the target list shows the new URL and the page
      // renders) while the Page.navigate reply never comes back. Record it as an anomaly and drive the
      // navigation from the page itself, so the harness keeps collecting evidence instead of stalling;
      // the anomaly is asserted by the caller, never silently absorbed.
      this.anomalies.push({ kind: 'page_navigate_no_reply', url, error: String(error?.message ?? error) });
      try {
        await this.evaluate(`location.assign(${JSON.stringify(url)})`);
      } catch (inner) {
        this.anomalies.push({ kind: 'session_unresponsive', url, error: String(inner?.message ?? inner) });
        await this.newTab();
        await this.send('Page.navigate', { url }, this.sessionId, commandTimeoutMs).catch(retry => {
          this.anomalies.push({ kind: 'page_navigate_no_reply_on_fresh_tab', url, error: String(retry?.message ?? retry) });
        });
      }
    }
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const state = await this.evaluate(`(() => ({
        ready: document.readyState,
        rootChildren: document.getElementById('root')?.childElementCount ?? -1,
        url: location.href,
      }))()`).catch(() => null);
      if (state && state.ready === 'complete' && state.rootChildren > 0) break;
      await sleep(200);
    }
    await sleep(settleMs);
    return this.evaluate('location.href');
  }

  async screenshot(file) {
    const { data } = await this.send('Page.captureScreenshot', {
      format: 'png', captureBeyondViewport: false, fromSurface: true,
    }, this.sessionId);
    const buffer = Buffer.from(data, 'base64');
    writeFileSync(file, buffer);
    // Read the dimensions straight out of the PNG IHDR: a capture that does not match the
    // requested viewport is not evidence of that viewport.
    const width = buffer.readUInt32BE(16);
    const height = buffer.readUInt32BE(20);
    return { file, bytes: buffer.length, width, height, sha256: createHash('sha256').update(buffer).digest('hex') };
  }

  consoleErrors() {
    return this.events
      .filter(event => (event.method === 'Runtime.exceptionThrown'
        || (event.method === 'Log.entryAdded' && event.params?.entry?.level === 'error')))
      .map(event => event.method === 'Runtime.exceptionThrown'
        ? String(event.params?.exceptionDetails?.text ?? 'exception')
        : String(event.params?.entry?.text ?? 'log error'));
  }

  close() { try { this.ws.close(); } catch { /* already closed */ } }
}
