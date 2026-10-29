import '@testing-library/jest-dom/vitest';
import { createElement, type ComponentType, type ReactNode } from 'react';
import { vi } from 'vitest';
import { I18nProvider } from '../i18n';
import { webcrypto } from 'node:crypto';

// Exercise the real digest implementation; jsdom does not supply SubtleCrypto.
Object.defineProperty(globalThis.crypto, 'subtle', { configurable: true, value: webcrypto.subtle });

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(window, 'ResizeObserver', { writable: true, value: ResizeObserverStub });
Object.defineProperty(globalThis, 'ResizeObserver', { writable: true, value: ResizeObserverStub });
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});

// The running app mounts one language provider at its root, and every screen reads its wording from
// it. The harness supplies the same provider for every test rather than asking each file to remember
// it, so a missing provider fails in production wiring instead of passing as a bare render.
const underProvider = (Wrapper?: ComponentType<{ children: ReactNode }>) =>
  function LanguageWrapper({ children }: { children: ReactNode }) {
    return createElement(I18nProvider, null,
      Wrapper ? createElement(Wrapper, null, children) : children);
  };

vi.mock('@testing-library/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@testing-library/react')>();
  return {
    ...actual,
    render: (ui: ReactNode, options?: Parameters<typeof actual.render>[1]) =>
      actual.render(ui as never, { ...options, wrapper: underProvider(options?.wrapper) }),
    renderHook: (callback: never, options?: Parameters<typeof actual.renderHook>[1]) =>
      actual.renderHook(callback, { ...options, wrapper: underProvider(options?.wrapper) }),
  };
});
