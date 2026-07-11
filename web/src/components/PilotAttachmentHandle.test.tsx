// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import PilotAttachmentHandle from './PilotAttachmentHandle';

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | undefined;
let root: Root | undefined;

function render(ui: React.ReactNode) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root?.render(ui));
  return container;
}

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

describe('PilotAttachmentHandle', () => {
  it('serializes its reference-only attachment for native drag and offers an accessible click action', () => {
    const onAttach = vi.fn();
    const attachment = { kind: 'application' as const, id: '7', label: 'ByteDance · Backend' };
    const view = render(<PilotAttachmentHandle attachment={attachment} onAttach={onAttach} />);
    const button = view.querySelector<HTMLButtonElement>('button')!;
    const setData = vi.fn();
    const dragStart = new Event('dragstart', { bubbles: true });
    Object.defineProperty(dragStart, 'dataTransfer', { value: { setData } });

    expect(button.draggable).toBe(true);
    expect(button.getAttribute('aria-label')).toBe('添加 ByteDance · Backend 到 Pilot 上下文');

    act(() => button.dispatchEvent(dragStart));
    act(() => button.click());

    expect(setData).toHaveBeenCalledWith(
      'application/x-offerpilot-context-attachment',
      JSON.stringify(attachment),
    );
    expect(onAttach).toHaveBeenCalledWith(attachment);
  });
});
