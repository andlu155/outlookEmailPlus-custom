'use strict';

const fs = require('fs');
const path = require('path');

const workflow = fs.readFileSync(
  path.resolve(__dirname, '../../.github/workflows/docker-build-push.yml'),
  'utf8',
);

describe('custom registry publish workflow', () => {
  test('publishes the image used by docker compose for every branch push', () => {
    expect(workflow).toMatch(/branches:\r?\n\s+- "\*\*"/);
    expect(workflow).toContain('ghcr.io/${GITHUB_REPOSITORY_OWNER,,}/outlookemailplus-custom');
    expect(workflow).toContain('type=raw,value=latest');
  });
});
