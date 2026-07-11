// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Composer from './Composer';

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

function changeValue(input: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

describe('Composer quick questions', () => {
  it('fills the composer without sending when a quick question is selected', () => {
    const onSend = vi.fn();
    const view = render(
      <Composer
        capabilities={[]}
        suggestions={['Compare this offer with my application']}
        onSend={onSend}
      />,
    );

    const question = view.querySelector<HTMLButtonElement>('[data-testid="quick-question-0"]');
    expect(question?.textContent).toContain('Compare this offer');

    act(() => question?.click());

    expect(view.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe(
      'Compare this offer with my application',
    );
    expect(onSend).not.toHaveBeenCalled();
  });

  it('hides quick questions after typing and while disabled', () => {
    const view = render(
      <Composer capabilities={[]} suggestions={['Question one']} onSend={vi.fn()} />,
    );
    const input = view.querySelector<HTMLTextAreaElement>('textarea');

    expect(view.querySelector('[data-testid="quick-question-0"]')).not.toBeNull();
    act(() => changeValue(input!, 'A draft question'));
    expect(view.querySelector('[data-testid="quick-question-0"]')).toBeNull();

    act(() => root?.render(<Composer capabilities={[]} suggestions={['Question one']} disabled onSend={vi.fn()} />));
    expect(view.querySelector('[data-testid="quick-question-0"]')).toBeNull();
  });
});
