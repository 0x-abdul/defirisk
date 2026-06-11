/** ESLint config for Astro + TS site.
 *
 * Conservative starter rules: catch real correctness issues, do not enforce
 * taste. Run via `npm run lint`. Auto-fix safe findings via
 * `npm run lint -- --fix`.
 */
module.exports = {
  root: true,
  env: {
    browser: true,
    node: true,
    es2022: true,
  },
  extends: ['eslint:recommended'],
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
  },
  rules: {
    // Empty catch blocks are common in defensive parsing; allow them.
    'no-empty': ['error', { allowEmptyCatch: true }],
  },
  ignorePatterns: [
    'dist/',
    '.astro/',
    'node_modules/',
    'public/',
    'tests/visual/__snapshots__/',
    'scripts/build-og-images.mjs', // satori runtime; minified-style output OK
    // Pages with HTML-style `<!--` inside JSX expressions; astro-eslint-parser
    // misreads these as JSX. Files are design-blocked anyway — rewritten with
    // D3 page implementation.
    'src/pages/protocols/**',
  ],
  overrides: [
    // TypeScript files
    {
      files: ['**/*.ts', '**/*.tsx'],
      parser: '@typescript-eslint/parser',
      plugins: ['@typescript-eslint'],
      extends: ['plugin:@typescript-eslint/recommended'],
      rules: {
        '@typescript-eslint/no-unused-vars': [
          'warn',
          { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
        ],
        '@typescript-eslint/no-explicit-any': 'off',
        // env.d.ts uses Astro's standard triple-slash reference convention.
        '@typescript-eslint/triple-slash-reference': 'off',
      },
    },
    // Astro components
    {
      files: ['**/*.astro'],
      parser: 'astro-eslint-parser',
      parserOptions: {
        parser: '@typescript-eslint/parser',
        extraFileExtensions: ['.astro'],
      },
      plugins: ['astro'],
      extends: ['plugin:astro/recommended'],
      rules: {
        // Astro components have implicit imports; these are noise.
        'no-undef': 'off',
        'no-unused-vars': 'off',
      },
    },
    // Test files
    {
      files: ['**/*.test.ts', '**/*.spec.ts', 'tests/**/*.ts'],
      env: { node: true },
    },
  ],
};
