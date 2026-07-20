'use strict';

const fs = require('fs');
const path = require('path');

const mainCssPath = path.resolve(__dirname, '../../static/css/main.css');

describe('unified dark dashboard theme', () => {
  test('defines the deep dashboard palette tokens', () => {
    const css = fs.readFileSync(mainCssPath, 'utf8');

    expect(css).toContain('--ui-surface-base: #0b1020');
    expect(css).toContain('--ui-accent: #7c6cff');
    expect(css).toContain('--ui-focus-ring: rgba(124, 108, 255, 0.42)');
  });

  test('styles shared components and visible keyboard focus states', () => {
    const css = fs.readFileSync(mainCssPath, 'utf8');

    [
      '.sidebar',
      '.topbar',
      '.card',
      '.data-table tbody tr:hover td',
      '.modal-content,',
      '.modal > .modal-box',
      '.btn:focus-visible',
      '.form-input:focus',
    ].forEach((selector) => expect(css).toContain(selector));
  });
});
