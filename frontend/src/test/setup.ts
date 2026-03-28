import "@testing-library/jest-dom/vitest";
import { createElement, type ReactNode } from "react";
import { vi } from "vitest";

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");

  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) =>
      createElement("div", { style: { width: 1280, height: 720 } }, children),
  };
});

if (typeof window !== "undefined") {
  globalThis.AbortController = window.AbortController;
  globalThis.AbortSignal = window.AbortSignal;
  globalThis.Headers = window.Headers;
  globalThis.Request = window.Request;
  globalThis.Response = window.Response;
  window.matchMedia = window.matchMedia || ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

class ResizeObserverMock {
  observe() {
    return undefined;
  }

  unobserve() {
    return undefined;
  }

  disconnect() {
    return undefined;
  }
}

globalThis.ResizeObserver = globalThis.ResizeObserver || (ResizeObserverMock as unknown as typeof ResizeObserver);

class IntersectionObserverMock {
  readonly root = null;
  readonly rootMargin = "";
  readonly thresholds = [0];

  disconnect() {
    return undefined;
  }

  observe() {
    return undefined;
  }

  takeRecords() {
    return [];
  }

  unobserve() {
    return undefined;
  }
}

globalThis.IntersectionObserver =
  globalThis.IntersectionObserver || (IntersectionObserverMock as unknown as typeof IntersectionObserver);

HTMLCanvasElement.prototype.getContext =
  HTMLCanvasElement.prototype.getContext ||
  (() => {
    return {
      setTransform: () => undefined,
      clearRect: () => undefined,
      createRadialGradient: () => ({ addColorStop: () => undefined }),
      beginPath: () => undefined,
      arc: () => undefined,
      fill: () => undefined,
      moveTo: () => undefined,
      lineTo: () => undefined,
      createLinearGradient: () => ({ addColorStop: () => undefined }),
      stroke: () => undefined,
      fillRect: () => undefined,
    } as unknown as CanvasRenderingContext2D;
  });

Object.defineProperty(HTMLElement.prototype, "clientWidth", {
  configurable: true,
  get() {
    return 1280;
  },
});

Object.defineProperty(HTMLElement.prototype, "clientHeight", {
  configurable: true,
  get() {
    return 720;
  },
});

Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
  configurable: true,
  get() {
    return 1280;
  },
});

Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
  configurable: true,
  get() {
    return 720;
  },
});

HTMLElement.prototype.getBoundingClientRect =
  HTMLElement.prototype.getBoundingClientRect ||
  (() =>
    ({
      x: 0,
      y: 0,
      width: 1280,
      height: 720,
      top: 0,
      left: 0,
      right: 1280,
      bottom: 720,
      toJSON: () => undefined,
    }) as DOMRect);
