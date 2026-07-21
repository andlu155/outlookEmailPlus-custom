'use strict';

const fs = require('fs');
const path = require('path');

const read = (relativePath) => fs.readFileSync(path.resolve(__dirname, '../..', relativePath), 'utf8');

describe('diagnostics center contract', () => {
  const html = read('templates/index.html');
  const js = read('static/js/main.js');

  test('provides an administrator diagnostics entry point', () => {
    expect(html).toContain('data-page="diagnostics"');
    expect(html).toContain('id="page-diagnostics"');
  });

  test('loads diagnostics by trace id and keeps audit history reachable', () => {
    expect(js).toContain("if (page === 'diagnostics') loadDiagnosticsPage();");
    expect(js).toContain("fetch('/api/system/diagnostics')");
    expect(js).toContain("fetch(`/api/audit-logs?${params.toString()}`)");
  });
});
