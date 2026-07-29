/**
 * Smoke tests — public JSON API (E-26)
 *
 * Hits the static JSON API endpoints and asserts the canonical envelope shape.
 * All endpoints are always present (static files, not generated from protocol data).
 */

import { test, expect } from '@playwright/test';
import { RUBRIC_VERSION as RUBRIC } from '../../src/lib/rubric';

const API = `/api/${RUBRIC}`;

type Envelope = {
  rubric_version: string;
  data_as_of: string;
  generated_at: string;
  data: Record<string, unknown>;
};

function assertEnvelope(body: unknown): asserts body is Envelope {
  const b = body as Record<string, unknown>;
  expect(typeof b.rubric_version).toBe('string');
  expect(typeof b.data_as_of).toBe('string');
  expect(typeof b.generated_at).toBe('string');
  expect(typeof b.data).toBe('object');
  expect(b.data).not.toBeNull();
}

test.describe('API — always-present static JSON', () => {
  test(`GET /api/${RUBRIC}/index.json — valid envelope, non-empty data`, async ({ request }) => {
    const res = await request.get(`${API}/index.json`);
    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toContain('application/json');
    const body = await res.json() as unknown;
    assertEnvelope(body);
  });

  test(`GET /api/${RUBRIC}/factors.json — valid envelope with factors array`, async ({ request }) => {
    const res = await request.get(`${API}/factors.json`);
    expect(res.status()).toBe(200);
    const body = await res.json() as Envelope;
    assertEnvelope(body);
    expect(Array.isArray((body.data as Record<string, unknown>).factors)).toBe(true);
    const factors = (body.data as { factors: unknown[] }).factors;
    expect(factors.length).toBeGreaterThan(0);
  });

  test(`GET /api/${RUBRIC}/hacks.json — valid envelope with hacks array`, async ({ request }) => {
    const res = await request.get(`${API}/hacks.json`);
    expect(res.status()).toBe(200);
    const body = await res.json() as Envelope;
    assertEnvelope(body);
    expect(Array.isArray((body.data as Record<string, unknown>).hacks)).toBe(true);
  });

  test(`GET /api/${RUBRIC}/incidents.json — valid envelope`, async ({ request }) => {
    const res = await request.get(`${API}/incidents.json`);
    expect(res.status()).toBe(200);
    const body = await res.json() as Envelope;
    assertEnvelope(body);
  });

  test(`GET /api/${RUBRIC}/rubric.json — valid envelope`, async ({ request }) => {
    const res = await request.get(`${API}/rubric.json`);
    expect(res.status()).toBe(200);
    const body = await res.json() as Envelope;
    assertEnvelope(body);
  });

  test(`GET /api/${RUBRIC}/schema/envelope.json — is a JSON Schema object`, async ({ request }) => {
    const res = await request.get(`${API}/schema/envelope.json`);
    expect(res.status()).toBe(200);
    const body = await res.json() as Record<string, unknown>;
    expect(body['$schema']).toBeTruthy();
    expect(body['type']).toBe('object');
  });

  test(`GET /api/${RUBRIC}/schemas/envelope.json — is a JSON Schema object (canonical path)`, async ({ request }) => {
    const res = await request.get(`${API}/schemas/envelope.json`);
    expect(res.status()).toBe(200);
    const body = await res.json() as Record<string, unknown>;
    expect(body['$schema']).toBeTruthy();
    expect(body['type']).toBe('object');
  });

  test(`GET /api/${RUBRIC}/openapi.json — OpenAPI 3.1 spec`, async ({ request }) => {
    const res = await request.get(`${API}/openapi.json`);
    expect(res.status()).toBe(200);
    const body = await res.json() as Record<string, unknown>;
    expect(body.openapi).toBe('3.1.0');
    expect(typeof body.paths).toBe('object');
  });

  test(`GET /api/${RUBRIC}/openapi.yaml — is YAML-parseable text`, async ({ request }) => {
    const res = await request.get(`${API}/openapi.yaml`);
    expect(res.status()).toBe(200);
    const text = await res.text();
    // Basic YAML structure check: must start with openapi: or contain openapi:
    expect(text).toMatch(/openapi:\s*['"']?3\.\d/);
    expect(text.length).toBeGreaterThan(100);
  });
});

test.describe('API — per-protocol JSON (skip when M3a not imported)', () => {
  const SLUG = 'aave-v3';

  test(`GET /api/${RUBRIC}/protocols/${SLUG}.json — valid envelope if present`, async ({ request }) => {
    const res = await request.get(`${API}/protocols/${SLUG}.json`);
    if (res.status() === 404) {
      test.skip(true, `${SLUG} not yet generated — M3a data pending`);
      return;
    }
    expect(res.status()).toBe(200);
    const body = await res.json() as Envelope;
    assertEnvelope(body);
    const pd = (body.data as { protocol_data?: Record<string, unknown> }).protocol_data;
    expect(pd).toBeTruthy();
  });

  test(`GET /api/${RUBRIC}/protocols/${SLUG}.json — M1 v4 envelope fields (rubric_version, risk_score, category_severities, cap_applied, cap_reason)`, async ({ request }) => {
    const res = await request.get(`${API}/protocols/${SLUG}.json`);
    if (res.status() === 404) {
      test.skip(true, `${SLUG} not yet generated — M3a data pending`);
      return;
    }
    expect(res.status()).toBe(200);
    const body = await res.json() as Envelope & Record<string, unknown>;

    // rubric_version must match the single source of truth in site/src/lib/rubric.ts
    expect(body.rubric_version).toBe(RUBRIC);

    // M1 v4 fields are canonical at envelope top-level. The inner copy under
    // data.protocol_data.protocol.* is retained for compatibility and asserted
    // separately below.
    //
    // ── Envelope-level (canonical) ──────────────────────────────────────────
    expect(typeof body.risk_score).toBe('number');
    expect(body.risk_score as number).toBeGreaterThanOrEqual(0);
    expect(body.risk_score as number).toBeLessThanOrEqual(100);

    expect(typeof body.category_severities).toBe('object');
    expect(body.category_severities).not.toBeNull();
    const cs = body.category_severities as Record<string, unknown>;
    for (const [key, val] of Object.entries(cs)) {
      expect(key).toMatch(/^([1-9]|1[0-3])$/);
      expect(typeof val).toBe('number');
      expect(val as number).toBeGreaterThanOrEqual(0);
      expect(val as number).toBeLessThanOrEqual(100);
    }

    expect(['none', 'D', 'F']).toContain(body.cap_applied);
    // cap_reason: always present on protocol envelopes, paired with cap_applied;
    // null when cap_applied='none', string otherwise.
    expect(body.cap_reason === null || typeof body.cap_reason === 'string').toBe(true);

    // ── Inner protocol object (back-compat copy) ────────────────────────────
    const pd = (body.data as { protocol_data?: Record<string, unknown> }).protocol_data;
    expect(pd).toBeTruthy();
    const proto = (pd as { protocol?: Record<string, unknown> }).protocol;
    expect(proto).toBeTruthy();
    const p = proto as Record<string, unknown>;
    expect(typeof p.risk_score).toBe('number');
    expect(typeof p.category_severities).toBe('object');
    expect(['none', 'D', 'F']).toContain(p.cap_applied);
    expect(p.cap_reason === null || typeof p.cap_reason === 'string').toBe(true);

    // Envelope-level and inner copy must agree exactly on ALL four M1 v4
    // fields. Per docs/api.md, envelope-level is canonical; the inner copy
    // under data.protocol_data.protocol.* is a back-compat mirror, and a
    // mirror that differs on ANY M1 field is a contract violation.
    // (round-2 patched risk_score skew on 4 protocols; round-4 patched the
    // same 4 protocols' category_severities skew.)
    expect(body.risk_score).toBe(p.risk_score);
    expect(body.category_severities).toEqual(p.category_severities);
    expect(body.cap_applied).toBe(p.cap_applied);
    expect(body.cap_reason).toBe(p.cap_reason);
  });
});

test.describe('API — per-factor JSON', () => {
  const FACTOR = 'RD-F-001';

  test(`GET /api/${RUBRIC}/factors/${FACTOR}.json — valid envelope if present`, async ({ request }) => {
    const res = await request.get(`${API}/factors/${FACTOR}.json`);
    if (res.status() === 404) {
      test.skip(true, `Factor ${FACTOR} detail JSON not yet generated`);
      return;
    }
    expect(res.status()).toBe(200);
    const body = await res.json() as Envelope;
    assertEnvelope(body);
  });
});

test.describe('API — private review routes are absent', () => {
  const BOGUS = 'test-protocol-deadbeef';
  const URL = `${API}/unpublished/${BOGUS}/index.json`;

  test(`GET ${URL} cannot return private review data`, async ({ request }) => {
    const res = await request.get(URL);
    expect(res.status()).toBe(404);
  });
});
