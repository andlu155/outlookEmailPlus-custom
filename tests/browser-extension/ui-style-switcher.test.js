'use strict';

const fs = require('fs');
const path = require('path');

const read = (relativePath) => fs.readFileSync(path.resolve(__dirname, '../..', relativePath), 'utf8');

describe('UI style switcher contract', () => {
  const html = read('templates/index.html');
  const js = read('static/js/main.js');
  const css = read('static/css/main.css');
  const compose = read('docker-compose.yml');

  test('provides the style selector before the theme toggle', () => {
    expect(html).toMatch(/<select[^>]*id="uiStyleSelect"[^>]*>[\s\S]*?<option value="classic">经典国风<\/option>[\s\S]*?<option value="dashboard">深色数据台<\/option>[\s\S]*?<\/select>/);
    expect(html.indexOf('id="uiStyleSelect"')).toBeLessThan(html.indexOf('id="themeToggleBtn"'));
  });

  test('persists and initializes the classic UI style independently', () => {
    const uiStyleStart = js.indexOf('function applyUiStyle(style)');
    const themeStart = js.indexOf('function applyTheme(theme)');
    const uiStyleFunction = js.slice(uiStyleStart, themeStart);

    expect(js).toMatch(/function applyUiStyle\(style\)/);
    expect(js).toMatch(/style === 'dashboard' \? 'dashboard' : 'classic'/);
    expect(js).toContain("document.documentElement.dataset.uiStyle = normalizedStyle;");
    expect(js).toContain("localStorage.setItem('ol_ui_style', normalizedStyle);");
    expect(js).toContain("applyUiStyle(localStorage.getItem('ol_ui_style') || 'classic');");
    expect(js).toMatch(/function applyTheme\(theme\)/);
    expect(js).toContain("localStorage.setItem('ol_theme', theme);");
    expect(themeStart).toBeGreaterThan(uiStyleStart);
    expect(uiStyleFunction).not.toContain('ol_theme');
  });

  test('scopes dashboard overrides and preserves the GHCR image source', () => {
    const dashboardTheme = css.slice(css.indexOf('/* ===== Unified Dark Dashboard Theme ===== */') + '/* ===== Unified Dark Dashboard Theme ===== */'.length).trimStart();
    const scopeStart = dashboardTheme.search(/@scope \(html\[data-ui-style="dashboard"\]\)\s*\{/);
    const openingBrace = dashboardTheme.indexOf('{', scopeStart);
    let depth = 0;
    let closingBrace = -1;

    expect(scopeStart).toBe(0);
    for (let index = openingBrace; index < dashboardTheme.length; index += 1) {
      if (dashboardTheme[index] === '{') depth += 1;
      if (dashboardTheme[index] === '}') depth -= 1;
      if (depth === 0) {
        closingBrace = index;
        break;
      }
    }
    expect(closingBrace).toBeGreaterThan(openingBrace);
    expect(dashboardTheme.slice(openingBrace, closingBrace + 1)).toContain(':scope {');
    expect(compose).toContain('image: ghcr.io/andlu155/outlookemailplus-custom:${IMAGE_TAG:-latest}');
  });
});
